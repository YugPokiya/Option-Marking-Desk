"""Synthetic NSE bhavcopy files (UDiFF columns) with realistic implied-vol dynamics.

Used for tests and demos only. The 30-day ATM vol follows a mean-reverting process with a
leverage effect (vol up when the index falls), skew and curvature mean-revert too, so part of
tomorrow's smile change is predictable from today's state. With ``predictable=False`` the vol
state is a pure random walk, which lets tests check that the model does NOT invent skill.
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..quant import black
from .bhavcopy import filename

COLS = [
    "TradDt",
    "BizDt",
    "Sgmt",
    "Src",
    "FinInstrmTp",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "XpryDt",
    "FininstrmActlXpryDt",
    "StrkPric",
    "OptnTp",
    "FinInstrmNm",
    "OpnPric",
    "HghPric",
    "LwPric",
    "ClsPric",
    "LastPric",
    "PrvsClsgPric",
    "UndrlygPric",
    "SttlmPric",
    "OpnIntrst",
    "ChngInOpnIntrst",
    "TtlTradgVol",
    "TtlTrfVal",
    "TtlNbOfTxsExctd",
    "SsnId",
    "NewBrdLotQty",
    "Rmks",
    "Rsvd1",
    "Rsvd2",
    "Rsvd3",
    "Rsvd4",
]


@dataclass
class VolState:
    atm: float = 0.14  # 30-day ATM vol
    skew: float = 0.025  # iv(k=-5%) - iv(k=+5%)
    curv: float = 0.9  # convexity, vol per k^2


def _expiries(d: date) -> list[date]:
    """Weekly Tuesdays for 4 weeks + the last Tuesday of the next 3 months."""
    out = set()
    nxt = d + timedelta(days=(1 - d.weekday()) % 7 or 7) if d.weekday() != 1 else d + timedelta(days=7)
    for i in range(4):
        out.add(nxt + timedelta(days=7 * i))
    y, m = d.year, d.month
    for i in range(3):
        mm, yy = (m + i - 1) % 12 + 1, y + (m + i - 1) // 12
        last = date(yy + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1)
        last -= timedelta(days=(last.weekday() - 1) % 7)
        if last > d:
            out.add(last)
    return sorted(e for e in out if e > d)


def _monthlies(exps: list[date]) -> set[date]:
    return {e for e in exps if (e + timedelta(days=7)).month != e.month}


def generate(
    out_dir: Path,
    start: date = date(2024, 1, 1),
    days: int = 400,
    *,
    symbol: str = "NIFTY",
    spot0: float = 21500.0,
    rate: float = 0.065,
    div: float = 0.012,
    strike_step: float = 100.0,
    width: float = 0.08,
    predictable: bool = True,
    seed: int = 42,
) -> list[date]:
    """Write ``days`` business days of bhavcopy zips into ``out_dir``. Returns the trading dates."""
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    st, spot = VolState(), spot0
    trading, d = [], start
    holidays = {start + timedelta(days=int(x)) for x in rng.integers(5, max(int(days * 1.45), 6), size=days // 60)}
    prev_close: dict[tuple, float] = {}

    while len(trading) < days:
        d += timedelta(days=1)
        if d.weekday() >= 5 or d in holidays:
            continue
        # --- evolve the market
        realised = st.atm * 0.9  # implied trades over realised (variance risk premium)
        ret = (rate - div) / 252 + realised / math.sqrt(252) * rng.standard_normal()
        spot *= math.exp(ret)
        shock = rng.standard_normal(3)
        if predictable:
            st.atm += 0.06 * (0.14 - st.atm) - 1.6 * ret + 0.0045 * shock[0]
            st.skew += 0.08 * (0.025 - st.skew) - 0.25 * ret + 0.0015 * shock[1]
            st.curv += 0.10 * (0.9 - st.curv) + 0.05 * shock[2]
        else:
            st.atm += 0.0055 * shock[0]
            st.skew += 0.0017 * shock[1]
            st.curv += 0.05 * shock[2]
        st.atm, st.skew, st.curv = min(max(st.atm, 0.07), 0.6), min(max(st.skew, 0.0), 0.08), min(max(st.curv, 0.2), 3)
        trading.append(d)

        rows = []
        exps = _expiries(d)
        monthly = _monthlies(exps)
        for e in exps:
            t = ((e - d).days + 0.4) / 365
            fwd = spot * math.exp((rate - div) * t)
            df = math.exp(-rate * t)
            atm_t = st.atm * (t / (30 / 365)) ** -0.06
            scale = math.sqrt((30 / 365) / t)
            lo, hi = spot * (1 - width * (1 + 2 * t)), spot * (1 + width * (1 + 2 * t))
            for k_strike in np.arange(math.ceil(lo / strike_step) * strike_step, hi, strike_step):
                k = math.log(k_strike / fwd)
                iv = atm_t + (-st.skew / 0.1) * k * scale + st.curv * k * k * scale
                iv = max(iv, 0.04)
                dist = abs(k) / (0.03 + 0.5 * t)
                for opt in ("CE", "PE"):
                    fair = float(black.price(fwd, k_strike, t, iv, df, opt == "CE"))
                    if fair < 0.05:
                        continue
                    vol_traded = int(
                        max(0, rng.normal(30000 * math.exp(-1.5 * dist) * (1.5 if e == exps[0] else 1), 300))
                    )
                    noise = rng.normal(0, 0.002 + 0.03 * min(dist, 3) ** 1.5) if vol_traded else 0
                    key = (e, k_strike, opt)
                    close = (
                        round(max(fair * (1 + noise), 0.05) / 0.05) * 0.05
                        if vol_traded
                        else prev_close.get(key, round(fair / 0.05) * 0.05)
                    )
                    prev_close[key] = close
                    rows.append(
                        _row(
                            d,
                            symbol,
                            "IDO",
                            e,
                            k_strike,
                            opt,
                            close,
                            round(fair / 0.05) * 0.05,
                            spot,
                            int(vol_traded * rng.uniform(3, 8)),
                            vol_traded,
                        )
                    )
            if e in monthly:
                fut = round(fwd * (1 + rng.normal(0, 0.0002)) / 0.05) * 0.05
                rows.append(_row(d, symbol, "IDF", e, None, None, fut, fut, spot, 1_000_000, 150_000))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLS)
        w.writerows(rows)
        with zipfile.ZipFile(out_dir / filename(d), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(filename(d).removesuffix(".zip"), buf.getvalue())
    return trading


def _row(d, symbol, typ, e, strike, opt, close, settle, spot, oi, vol):
    r = dict.fromkeys(COLS, "")
    r.update(
        {
            "TradDt": d.isoformat(),
            "BizDt": d.isoformat(),
            "Sgmt": "FO",
            "Src": "NSE",
            "FinInstrmTp": typ,
            "TckrSymb": symbol,
            "XpryDt": e.isoformat(),
            "FininstrmActlXpryDt": e.isoformat(),
            "StrkPric": "" if strike is None else f"{strike:.2f}",
            "OptnTp": opt or "",
            "ClsPric": f"{close:.2f}",
            "LastPric": f"{close:.2f}",
            "SttlmPric": f"{settle:.2f}",
            "UndrlygPric": f"{spot:.2f}",
            "OpnIntrst": oi,
            "TtlTradgVol": vol,
            "NewBrdLotQty": 75,
            "SsnId": "F1",
        }
    )
    return [r[c] for c in COLS]


def surface_frame(
    days: int = 500,
    *,
    kappa: float = 0.06,
    leverage: float = 1.6,
    noise: float = 0.0045,
    seed: int = 0,
    symbol: str = "NIFTY",
) -> pd.DataFrame:
    """Daily 30-day smiles straight from the vol process (no bhavcopy, no SVI): fast, for model tests.

    kappa = daily mean-reversion speed of ATM vol (the predictable part); 0 gives a pure random walk.
    """
    from .surface import GRID_COLS, K_GRID

    rng = np.random.default_rng(seed)
    st, spot, d, rows = VolState(), 21500.0, date(2023, 1, 2), []
    while len(rows) < days:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        ret = st.atm * 0.9 / math.sqrt(252) * rng.standard_normal()
        spot *= math.exp(ret)
        z = rng.standard_normal(2)
        st.atm = min(max(st.atm + kappa * (0.14 - st.atm) - leverage * ret + noise * z[0], 0.07), 0.6)
        st.skew = min(max(st.skew + kappa * (0.025 - st.skew) + 0.0015 * z[1], 0.0), 0.08)
        row = {"date": d, "symbol": symbol, "spot": spot}
        for k, c in zip(K_GRID, GRID_COLS, strict=True):
            row[c] = max(st.atm + (-st.skew / 0.1) * k + st.curv * k * k, 0.04)
        row.update(
            n_expiries_fit=2,
            min_points=30,
            max_rmse_vol=0.002,
            all_arb_free=True,
            grid_covered=True,
            front_days=(1 - d.weekday()) % 7 or 7,
            opt_volume=int(5e6 * rng.uniform(0.7, 1.3)),
            pcr_volume=float(rng.uniform(0.8, 1.2)),
            n_contracts=450,
            forward_sources="future",
        )
        rows.append(row)
    return pd.DataFrame(rows)
