"""Mark an option chain: liquid strikes at market mid, illiquid ones from the fitted smile.

Pipeline
  1. discount factor + forward (put-call parity on liquid pairs, else carry from spot)
  2. classify each quote: liquid, or illiquid with reasons
  3. market implied vols (mid, and bid/ask where present)
  4. fit the smile on liquid out-of-the-money quotes, weighted by 1 / (bid-ask spread in vol)
     - >= 5 points: raw SVI with butterfly-arbitrage penalty
     - 3-4 points:  quadratic in k on total variance
     - 1-2 points:  flat at the ATM-most vol
  5. model vol + price for every strike, with an uncertainty band that widens in the wings
  6. mark = mid if liquid; otherwise model price, kept inside [bid, ask] when those exist,
     and never below intrinsic
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from . import black
from .svi import SVIParams, fit_svi, total_variance

SECONDS_PER_YEAR = 365.0 * 24 * 3600


@dataclass(frozen=True)
class QuoteIn:
    strike: float
    option_type: str  # "C" or "P"
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int = 0
    open_interest: int = 0
    quote_time: datetime | None = None

    @property
    def is_call(self) -> bool:
        return self.option_type.upper() == "C"


@dataclass(frozen=True)
class ChainIn:
    spot: float
    as_of: datetime
    expiry: datetime
    rate: float  # continuously compounded, decimal
    div_yield: float = 0.0
    quotes: tuple[QuoteIn, ...] = ()


@dataclass(frozen=True)
class MarkingConfig:
    max_spread_pct: float = 0.10  # (ask - bid) / mid above this is "wide"
    min_volume: int = 1  # fewer contracts traded today is "low_volume"
    max_quote_age_minutes: float = 15  # older than this vs as_of is "stale"
    band_z: float = 2.0  # band = z * fit RMSE (in vol), widened in the wings
    min_band_vol: float = 0.005  # never claim better than 0.5 vol points


@dataclass
class MarkOut:
    strike: float
    option_type: str
    bid: float | None
    ask: float | None
    mid: float | None
    liquid: bool
    reasons: list[str]
    market_iv: float | None
    model_iv: float
    model_price: float
    mark: float
    mark_iv: float | None
    lower: float
    upper: float
    method: str  # market_mid | model | model_clipped_bid | model_clipped_ask | intrinsic_floor


@dataclass
class FitOut:
    method: str  # svi | quadratic | flat
    params: dict[str, float]
    forward: float
    forward_source: str  # parity | carry
    df: float
    t: float
    rmse_vol: float
    n_points: int
    arbitrage_free: bool
    min_g: float | None
    k_min: float
    k_max: float


@dataclass
class MarkingResult:
    fit: FitOut
    marks: list[MarkOut] = field(default_factory=list)

    def model_iv(self, k):
        return _model_iv(self.fit, np.asarray(k, dtype=float))


def year_fraction(as_of: datetime, expiry: datetime) -> float:
    return max((expiry - as_of).total_seconds(), 0.0) / SECONDS_PER_YEAR


def _mid(q: QuoteIn) -> float | None:
    if q.bid and q.ask and q.bid > 0 and q.ask >= q.bid:
        return 0.5 * (q.bid + q.ask)
    return None


def classify(q: QuoteIn, as_of: datetime, cfg: MarkingConfig) -> list[str]:
    reasons: list[str] = []
    if not q.bid or q.bid <= 0:
        reasons.append("no_bid")
    if not q.ask or q.ask <= 0:
        reasons.append("no_ask")
    if q.bid and q.ask and q.bid > 0 and q.ask > 0:
        if q.ask < q.bid:
            reasons.append("crossed")
        elif (q.ask - q.bid) / (0.5 * (q.ask + q.bid)) > cfg.max_spread_pct:
            reasons.append("wide_spread")
    if q.volume < cfg.min_volume:
        reasons.append("low_volume")
    if q.quote_time is not None and (as_of - q.quote_time).total_seconds() > cfg.max_quote_age_minutes * 60:
        reasons.append("stale")
    return reasons


def implied_forward(quotes: list[QuoteIn], liquid: dict[tuple[float, str], bool], df: float) -> float | None:
    """F = K + (C - P) / df on the liquid strikes where C and P are closest (most ATM)."""
    by_strike: dict[float, dict[str, float]] = {}
    for q in quotes:
        m = _mid(q)
        if m is not None and liquid[(q.strike, q.option_type.upper())]:
            by_strike.setdefault(q.strike, {})[q.option_type.upper()] = m
    pairs = [(k, v["C"], v["P"]) for k, v in by_strike.items() if "C" in v and "P" in v]
    if not pairs:
        return None
    pairs.sort(key=lambda x: abs(x[1] - x[2]))
    estimates = [k + (c - p) / df for k, c, p in pairs[:3]]
    return float(np.median(estimates))


def _model_iv(fit: FitOut, k: np.ndarray) -> np.ndarray:
    if fit.method == "svi":
        w = total_variance(k, SVIParams(**fit.params))
    elif fit.method == "quadratic":
        w = fit.params["c0"] + fit.params["c1"] * k + fit.params["c2"] * k * k
    else:
        w = np.full_like(k, fit.params["w"])
    return np.sqrt(np.maximum(w, 1e-10) / fit.t)


def mark_chain(chain: ChainIn, cfg: MarkingConfig | None = None) -> MarkingResult:
    cfg = cfg or MarkingConfig()
    quotes = list(chain.quotes)
    if not quotes:
        raise ValueError("chain has no quotes")
    t = year_fraction(chain.as_of, chain.expiry)
    if t <= 0:
        raise ValueError("expiry must be after as_of")
    df = math.exp(-chain.rate * t)

    reasons = {(q.strike, q.option_type.upper()): classify(q, chain.as_of, cfg) for q in quotes}
    liquid = {key: not r for key, r in reasons.items()}

    fwd = implied_forward(quotes, liquid, df)
    fwd_source = "parity"
    if fwd is None or not math.isfinite(fwd) or fwd <= 0:
        fwd = chain.spot * math.exp((chain.rate - chain.div_yield) * t)
        fwd_source = "carry"

    # market IVs
    rows = []
    for q in quotes:
        mid = _mid(q)
        iv_mid = black.implied_vol(mid, fwd, q.strike, t, df, q.is_call) if mid else math.nan
        iv_bid = black.implied_vol(q.bid, fwd, q.strike, t, df, q.is_call) if q.bid else math.nan
        iv_ask = black.implied_vol(q.ask, fwd, q.strike, t, df, q.is_call) if q.ask else math.nan
        rows.append((q, mid, iv_mid, iv_bid, iv_ask))

    # fit set: liquid, out-of-the-money, valid IV
    fk, fw, fwt = [], [], []
    for q, _mid_px, iv_mid, iv_bid, iv_ask in rows:
        otm = (q.is_call and q.strike >= fwd) or (not q.is_call and q.strike < fwd)
        if liquid[(q.strike, q.option_type.upper())] and otm and math.isfinite(iv_mid):
            k = math.log(q.strike / fwd)
            spread_vol = iv_ask - iv_bid if math.isfinite(iv_ask) and math.isfinite(iv_bid) else 0.02
            fk.append(k)
            fw.append(iv_mid * iv_mid * t)
            fwt.append(1.0 / max(spread_vol, 0.002))
    order = np.argsort(fk)
    fk, fw, fwt = np.array(fk)[order], np.array(fw)[order], np.array(fwt)[order]

    if fk.size >= 5:
        svi = fit_svi(fk, fw, fwt)
        fit = FitOut(
            "svi",
            svi.params.as_dict(),
            fwd,
            fwd_source,
            df,
            t,
            0.0,
            svi.n_points,
            svi.arbitrage_free,
            svi.min_g,
            svi.k_min,
            svi.k_max,
        )
    elif fk.size >= 3:
        c2, c1, c0 = np.polyfit(fk, fw, 2, w=np.sqrt(fwt))
        fit = FitOut(
            "quadratic",
            {"c0": float(c0), "c1": float(c1), "c2": float(c2)},
            fwd,
            fwd_source,
            df,
            t,
            0.0,
            int(fk.size),
            bool(c2 >= 0),
            None,
            float(fk.min()),
            float(fk.max()),
        )
    elif fk.size >= 1:
        i = int(np.argmin(np.abs(fk)))
        fit = FitOut(
            "flat",
            {"w": float(fw[i])},
            fwd,
            fwd_source,
            df,
            t,
            0.0,
            int(fk.size),
            True,
            None,
            float(fk.min()),
            float(fk.max()),
        )
    else:
        raise ValueError("no liquid out-of-the-money quotes with a valid implied vol to fit")

    if fk.size:
        resid = _model_iv(fit, fk) - np.sqrt(fw / t)
        fit.rmse_vol = float(np.sqrt(np.average(resid * resid, weights=fwt)))

    span = max(fit.k_max - fit.k_min, 0.05)
    base_band = max(cfg.band_z * fit.rmse_vol, cfg.min_band_vol)

    result = MarkingResult(fit=fit)
    for q, mid, iv_mid, _iv_bid, _iv_ask in rows:
        k = math.log(q.strike / fwd)
        m_iv = float(_model_iv(fit, np.array([k]))[0])
        m_px = float(black.price(fwd, q.strike, t, m_iv, df, q.is_call))
        # extrapolation: band grows linearly with distance outside the fitted range
        outside = max(fit.k_min - k, k - fit.k_max, 0.0)
        band_vol = base_band * (1.0 + outside / span) * (1.0 if fit.method == "svi" else 1.5)
        lo = float(black.price(fwd, q.strike, t, max(m_iv - band_vol, 1e-4), df, q.is_call))
        hi = float(black.price(fwd, q.strike, t, m_iv + band_vol, df, q.is_call))

        key = (q.strike, q.option_type.upper())
        floor = float(black.intrinsic(fwd, q.strike, df, q.is_call))
        if liquid[key] and mid is not None:
            mark, method = mid, "market_mid"
        else:
            mark, method = m_px, "model"
            if q.bid and q.bid > 0 and mark < q.bid:
                mark, method = q.bid, "model_clipped_bid"
            if q.ask and q.ask > 0 and mark > q.ask and not (q.bid and q.ask < q.bid):
                mark, method = q.ask, "model_clipped_ask"
        if mark < floor:
            mark, method = floor, "intrinsic_floor"
        mark_iv = black.implied_vol(mark, fwd, q.strike, t, df, q.is_call)

        result.marks.append(
            MarkOut(
                strike=q.strike,
                option_type=q.option_type.upper(),
                bid=q.bid,
                ask=q.ask,
                mid=mid,
                liquid=liquid[key],
                reasons=reasons[key],
                market_iv=iv_mid if math.isfinite(iv_mid) else None,
                model_iv=m_iv,
                model_price=m_px,
                mark=float(mark),
                mark_iv=mark_iv if math.isfinite(mark_iv) else None,
                lower=min(lo, hi),
                upper=max(lo, hi),
                method=method,
            )
        )
    result.marks.sort(key=lambda m: (m.strike, m.option_type))
    return result
