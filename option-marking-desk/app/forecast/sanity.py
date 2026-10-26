"""Deterministic pre-publication checks. These always run; Claude's review is layered on top."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .features import FEATURE_COLS
from .surface import GRID_COLS

SEVERITY = {"info": 0, "warn": 1, "fail": 2}


@dataclass
class Check:
    check: str
    severity: str  # info | warn | fail
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def expected_latest_trading_day(today: date) -> date:
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def run_checks(
    *,
    today: date,
    surf_row: dict,
    history: pd.DataFrame,
    feat_row: pd.Series,
    feat_hist: pd.DataFrame,
    predicted_delta: dict[str, float],
    model_meta: dict,
    max_stale_days: int = 4,
) -> list[Check]:
    out: list[Check] = []
    d = surf_row["date"]

    lag = (expected_latest_trading_day(today) - d).days
    if lag > max_stale_days:
        out.append(Check("freshness", "fail", f"latest data is {d}, {lag} days behind {today}"))
    elif lag > 0:
        out.append(Check("freshness", "info", f"latest data is {d} (holiday or not yet published?)"))

    recent = history.tail(20)
    if len(recent) >= 5:
        med = float(recent["n_contracts"].median())
        ratio = surf_row["n_contracts"] / med if med else 1
        if ratio < 0.3:
            out.append(
                Check("contract_count", "fail", f"{surf_row['n_contracts']} contracts vs 20-day median {med:.0f}")
            )
        elif ratio < 0.6:
            out.append(
                Check("contract_count", "warn", f"{surf_row['n_contracts']} contracts vs 20-day median {med:.0f}")
            )

    if surf_row["max_rmse_vol"] > 0.03:
        out.append(Check("fit_quality", "fail", f"smile fit error {surf_row['max_rmse_vol'] * 100:.2f} vp"))
    elif surf_row["max_rmse_vol"] > 0.01 or surf_row["min_points"] < 10:
        out.append(
            Check(
                "fit_quality",
                "warn",
                f"fit error {surf_row['max_rmse_vol'] * 100:.2f} vp on as few as {surf_row['min_points']} quotes",
            )
        )
    if not surf_row["all_arb_free"]:
        out.append(Check("arbitrage", "warn", "a fitted expiry admits butterfly arbitrage"))
    if not surf_row["grid_covered"]:
        out.append(Check("coverage", "info", "the ±10% grid points are extrapolated beyond traded strikes"))
    if "carry" in str(surf_row.get("forward_sources", "")):
        out.append(Check("forward", "warn", "forward taken from spot carry (no future or traded parity pair)"))

    dhist = history[GRID_COLS].diff().abs().tail(250)
    if len(history) >= 2 and len(dhist.dropna()) >= 20:
        atm_move = abs(surf_row["iv_+0.000"] - history["iv_+0.000"].iloc[-2])
        typical = float(dhist["iv_+0.000"].median())
        if typical and atm_move > 6 * typical:
            out.append(
                Check(
                    "iv_jump", "warn", f"ATM vol moved {atm_move * 100:.2f} vp today (typical {typical * 100:.2f} vp)"
                )
            )
    if abs(feat_row.get("ret_1d", 0) or 0) > 0.04:
        out.append(Check("spot_jump", "warn", f"index moved {feat_row['ret_1d'] * 100:+.1f}% today"))

    for col, delta in predicted_delta.items():
        rmse = model_meta.get("rmse_rw_vp", {}).get(col)
        lim = max(3 * (rmse or 0) / 100, 0.015)
        level = surf_row[col] + delta
        if not 0.03 < level < 1.5:
            out.append(Check("prediction_level", "fail", f"{col} forecast {level * 100:.1f}% is implausible"))
        elif abs(delta) > 2 * lim:
            out.append(Check("prediction_size", "fail", f"{col} forecast change {delta * 100:+.2f} vp is extreme"))
        elif abs(delta) > lim:
            out.append(Check("prediction_size", "warn", f"{col} forecast change {delta * 100:+.2f} vp is large"))

    if model_meta.get("algo") == "rw":
        out.append(Check("model", "info", "no model beat the random walk out of sample; forecasting 'no change'"))

    fh = feat_hist[FEATURE_COLS].tail(250)
    if len(fh) >= 60:
        mu, sd = fh.mean(), fh.std().replace(0, np.nan)
        z = ((feat_row[FEATURE_COLS].astype(float) - mu) / sd).abs()
        wild = z[z > 6].sort_values(ascending=False)
        if len(wild):
            out.append(Check("feature_outlier", "warn", ", ".join(f"{k} (z={v:.0f})" for k, v in wild.head(4).items())))
    return out


def worst(checks: list[Check]) -> str:
    return max((c.severity for c in checks), key=SEVERITY.get, default="info")
