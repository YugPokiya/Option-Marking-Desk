"""End-of-day smile per expiry, then a 30-day constant-maturity smile on a fixed moneyness grid.

Bhavcopy has closes, not quotes, so "liquid" here means: traded today (volume >= min_volume),
out of the money, and with a usable price. The forward comes from the same-expiry future when one
exists (monthlies), else put-call parity on traded pairs, else spot carry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..quant import black
from ..quant.svi import SVIParams, fit_svi, total_variance

K_GRID = (-0.10, -0.05, -0.025, 0.0, 0.025, 0.05, 0.10)
GRID_COLS = [f"iv_{k:+.3f}" for k in K_GRID]
TARGET_DAYS = 30


@dataclass(frozen=True)
class SurfaceConfig:
    rate: float = 0.065
    div_yield: float = 0.012
    min_volume: int = 10
    min_price: float = 0.5
    min_points: int = 6
    min_days: int = 2
    max_days: int = 120
    max_abs_k: float = 0.25


@dataclass
class ExpiryFit:
    expiry: object
    t: float
    forward: float
    forward_source: str
    params: SVIParams
    rmse_vol: float
    n_points: int
    arbitrage_free: bool
    k_min: float
    k_max: float


def _forward(opts: pd.DataFrame, fut: pd.DataFrame, spot: float, t: float, df: float, cfg: SurfaceConfig):
    if len(fut):
        return float(fut["settle"].iloc[0]), "future"
    traded = opts[opts["volume"] >= cfg.min_volume]
    piv = traded.pivot_table(index="strike", columns="opt_type", values="close", aggfunc="first").dropna()
    if {"C", "P"} <= set(piv.columns) and len(piv):
        piv = piv.assign(gap=(piv["C"] - piv["P"]).abs()).nsmallest(3, "gap")
        return float(np.median(piv.index + (piv["C"] - piv["P"]) / df)), "parity"
    return spot * math.exp((cfg.rate - cfg.div_yield) * t), "carry"


def fit_expiry(day: pd.DataFrame, expiry, cfg: SurfaceConfig, x0: SVIParams | None = None) -> ExpiryFit | None:
    d = day["date"].iloc[0]
    t = ((expiry - d).days + 0.0) / 365
    if not (cfg.min_days / 365 <= t <= cfg.max_days / 365):
        return None
    spot = float(day["underlying"].median())
    df = math.exp(-cfg.rate * t)
    opts = day[(day["instr"] == "OPT") & (day["expiry"] == expiry)]
    fut = day[(day["instr"] == "FUT") & (day["expiry"] == expiry)]
    fwd, src = _forward(opts, fut, spot, t, df, cfg)

    q = opts[(opts["volume"] >= cfg.min_volume) & (opts["close"] >= cfg.min_price)]
    otm = q[((q["opt_type"] == "C") & (q["strike"] >= fwd)) | ((q["opt_type"] == "P") & (q["strike"] < fwd))]
    k_list, w_list, wt_list = [], [], []
    for row in otm.itertuples(index=False):
        k = math.log(row.strike / fwd)
        if abs(k) > cfg.max_abs_k:
            continue
        iv = black.implied_vol(row.close, fwd, row.strike, t, df, row.opt_type == "C")
        if math.isfinite(iv) and 0.02 < iv < 3:
            k_list.append(k)
            w_list.append(iv * iv * t)
            wt_list.append(math.sqrt(row.volume))
    if len(k_list) < cfg.min_points:
        return None
    order = np.argsort(k_list)
    k_arr, w_arr, wt = np.array(k_list)[order], np.array(w_list)[order], np.array(wt_list)[order]
    wt = np.minimum(wt, np.percentile(wt, 90))
    fit = fit_svi(k_arr, w_arr, wt, x0=x0)
    resid = np.sqrt(np.maximum(total_variance(k_arr, fit.params), 1e-12) / t) - np.sqrt(w_arr / t)
    rmse = float(np.sqrt(np.average(resid**2, weights=wt)))
    return ExpiryFit(expiry, t, fwd, src, fit.params, rmse, fit.n_points, fit.arbitrage_free, fit.k_min, fit.k_max)


def constant_maturity(fits: list[ExpiryFit], days: int = TARGET_DAYS) -> dict[str, float]:
    """Interpolate total variance linearly in time at each grid k; flat vol outside the expiry range."""
    t_star = days / 365
    fits = sorted(fits, key=lambda f: f.t)
    below = [f for f in fits if f.t <= t_star]
    above = [f for f in fits if f.t > t_star]
    out = {}
    for k, col in zip(K_GRID, GRID_COLS, strict=True):
        if below and above:
            a, b = below[-1], above[0]
            wa, wb = float(total_variance(k, a.params)), float(total_variance(k, b.params))
            w = wa + (wb - wa) * (t_star - a.t) / (b.t - a.t)
        else:
            f = (below or above)[-1 if below else 0]
            w = float(total_variance(k, f.params)) / f.t * t_star
        out[col] = math.sqrt(max(w, 1e-10) / t_star)
    return out


def _bracketing(expiries, d, cfg: SurfaceConfig) -> list:
    """The expiries that bracket TARGET_DAYS (+ one spare on each side in case a fit fails)."""
    eligible = [e for e in sorted(expiries) if cfg.min_days <= (e - d).days <= cfg.max_days]
    below = [e for e in eligible if (e - d).days <= TARGET_DAYS]
    above = [e for e in eligible if (e - d).days > TARGET_DAYS]
    return below[-2:] + above[:2]


def daily_surface(day: pd.DataFrame, cfg: SurfaceConfig = SurfaceConfig(), warm: dict | None = None) -> dict | None:
    """One row per (date, symbol): the 30-day smile on K_GRID plus fit diagnostics and activity stats.

    ``warm`` maps expiry -> yesterday's SVIParams and is updated in place (speeds up daily refits ~5x).
    """
    if day.empty:
        return None
    warm = {} if warm is None else warm
    opts = day[day["instr"] == "OPT"]
    d0 = day["date"].iloc[0]
    fits = []
    for e in _bracketing(opts["expiry"].unique(), d0, cfg):
        f = fit_expiry(day, e, cfg, warm.get(e))
        if f is not None:
            fits.append(f)
            warm[e] = f.params
    below = [f for f in fits if f.t <= TARGET_DAYS / 365]
    above = [f for f in fits if f.t > TARGET_DAYS / 365]
    fits = below[-1:] + above[:1]
    if not fits:
        return None
    d = day["date"].iloc[0]
    front = min(opts["expiry"])
    cm = constant_maturity(fits)
    covered = min(f.k_min for f in fits) <= K_GRID[0] and max(f.k_max for f in fits) >= K_GRID[-1]
    return {
        "date": d,
        "symbol": day["symbol"].iloc[0],
        "spot": float(day["underlying"].median()),
        **cm,
        "n_expiries_fit": len(fits),
        "min_points": min(f.n_points for f in fits),
        "max_rmse_vol": max(f.rmse_vol for f in fits),
        "all_arb_free": all(f.arbitrage_free for f in fits),
        "grid_covered": covered,
        "front_days": (front - d).days,
        "opt_volume": int(opts["volume"].sum()),
        "pcr_volume": float(
            opts.loc[opts["opt_type"] == "P", "volume"].sum()
            / max(opts.loc[opts["opt_type"] == "C", "volume"].sum(), 1)
        ),
        "n_contracts": len(opts),
        "forward_sources": ",".join(sorted({f.forward_source for f in fits})),
    }


def _pcr(opts: pd.DataFrame) -> float:
    puts = opts.loc[opts["opt_type"] == "P", "volume"].sum()
    calls = opts.loc[opts["opt_type"] == "C", "volume"].sum()
    return float(puts / max(calls, 1))


def build_surfaces(frames, cfg: SurfaceConfig = SurfaceConfig()) -> pd.DataFrame:
    """frames: iterable of normalised bhavcopy frames (one or more days, one or more symbols)."""
    rows, warm = [], {}
    for frame in frames:
        for (_, sym), day in frame.groupby(["date", "symbol"]):
            row = daily_surface(day, cfg, warm.setdefault(sym, {}))
            if row:
                rows.append(row)
    return pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True) if rows else pd.DataFrame()
