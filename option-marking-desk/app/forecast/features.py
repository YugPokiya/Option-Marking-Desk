"""Features known at today's close, and targets = tomorrow's change in the 30-day smile."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .surface import GRID_COLS

ATM, PUT5, CALL5, PUT10 = "iv_+0.000", "iv_-0.050", "iv_+0.050", "iv_-0.100"
TARGET_COLS = [f"d_{c}" for c in GRID_COLS]


def make_features(surf: pd.DataFrame) -> pd.DataFrame:
    """surf: one symbol, sorted by date. Returns features (+ targets where tomorrow is known)."""
    s = surf.sort_values("date").reset_index(drop=True).copy()
    dates = pd.to_datetime(s["date"])
    f = pd.DataFrame({"date": s["date"], "symbol": s["symbol"]})
    for c in GRID_COLS:
        f[c] = s[c]
    f["skew"] = s[PUT5] - s[CALL5]
    f["wing"] = s[PUT10] - s[ATM]
    f["curv"] = 0.5 * (s[PUT5] + s[CALL5]) - s[ATM]
    f["d1_atm"] = s[ATM].diff()
    f["d5_atm"] = s[ATM].diff(5)
    f["d1_skew"] = f["skew"].diff()
    f["atm_vs_60d"] = s[ATM] - s[ATM].rolling(60, min_periods=20).mean()
    logret = np.log(s["spot"]).diff()
    f["ret_1d"] = logret
    f["ret_5d"] = np.log(s["spot"]).diff(5)
    f["rv_10d"] = logret.rolling(10).std() * np.sqrt(252)
    f["rv_20d"] = logret.rolling(20).std() * np.sqrt(252)
    f["vrp_20d"] = s[ATM] - f["rv_20d"]
    f["front_days"] = s["front_days"]
    f["log_vol_ratio"] = np.log(s["opt_volume"].clip(lower=1) / s["opt_volume"].rolling(20, min_periods=5).mean())
    f["pcr_volume"] = s["pcr_volume"]
    f["dow"] = dates.dt.day_of_week
    gap = dates.shift(-1) - dates
    # tomorrow's gap is a calendar fact (weekends/holidays); assume next business day for the live row
    f["next_gap_days"] = gap.dt.days.fillna(np.where(dates.iloc[-1].day_of_week == 4, 3, 1) if len(dates) else 1)
    for c, t in zip(GRID_COLS, TARGET_COLS, strict=True):
        f[t] = s[c].shift(-1) - s[c]
    return f


FEATURE_COLS = [
    *GRID_COLS,
    "skew",
    "wing",
    "curv",
    "d1_atm",
    "d5_atm",
    "d1_skew",
    "atm_vs_60d",
    "ret_1d",
    "ret_5d",
    "rv_10d",
    "rv_20d",
    "vrp_20d",
    "front_days",
    "log_vol_ratio",
    "pcr_volume",
    "dow",
    "next_gap_days",
]


def training_frame(feat: pd.DataFrame) -> pd.DataFrame:
    return feat.dropna(subset=FEATURE_COLS + TARGET_COLS).reset_index(drop=True)
