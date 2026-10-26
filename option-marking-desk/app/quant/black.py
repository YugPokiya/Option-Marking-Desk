"""Black-76 on the forward. European options (NSE index options are European).

All volatilities are annualised decimals (0.15 = 15%), time in years, ``df`` = discount factor.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

SQRT_2PI = math.sqrt(2.0 * math.pi)
IV_LOW, IV_HIGH = 1e-4, 5.0


def _d1_d2(forward, strike, t, vol):
    vol_sqrt_t = vol * np.sqrt(t)
    d1 = (np.log(forward / strike) + 0.5 * vol * vol * t) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def price(forward, strike, t, vol, df, is_call):
    """Undiscounted-forward Black price, discounted with ``df``. Vectorised over any argument."""
    forward, strike, t, vol, df = map(np.asarray, (forward, strike, t, vol, df))
    is_call = np.asarray(is_call, dtype=bool)
    d1, d2 = _d1_d2(forward, strike, t, vol)
    call = df * (forward * ndtr(d1) - strike * ndtr(d2))
    put = df * (strike * ndtr(-d2) - forward * ndtr(-d1))
    return np.where(is_call, call, put)


def vega(forward, strike, t, vol, df):
    """dPrice/dVol (per 1.00 of vol, i.e. per 100 vol points)."""
    d1, _ = _d1_d2(np.asarray(forward), np.asarray(strike), np.asarray(t), np.asarray(vol))
    return df * forward * np.exp(-0.5 * d1 * d1) / SQRT_2PI * np.sqrt(t)


def delta(forward, strike, t, vol, df, is_call):
    """Delta with respect to the forward."""
    d1, _ = _d1_d2(np.asarray(forward), np.asarray(strike), np.asarray(t), np.asarray(vol))
    return np.where(np.asarray(is_call, dtype=bool), df * ndtr(d1), -df * ndtr(-d1))


def intrinsic(forward, strike, df, is_call):
    forward, strike = np.asarray(forward), np.asarray(strike)
    calls = np.maximum(forward - strike, 0.0)
    puts = np.maximum(strike - forward, 0.0)
    return df * np.where(np.asarray(is_call, dtype=bool), calls, puts)


def implied_vol(px: float, forward: float, strike: float, t: float, df: float, is_call: bool) -> float:
    """Implied vol by Brent's method. Returns NaN when the price is outside no-arbitrage bounds."""
    if not (px > 0 and forward > 0 and strike > 0 and t > 0):
        return math.nan
    lower = float(intrinsic(forward, strike, df, is_call))
    upper = df * (forward if is_call else strike)
    if px <= lower + 1e-12 or px >= upper:
        return math.nan

    def f(v: float) -> float:
        return float(price(forward, strike, t, v, df, is_call)) - px

    try:
        return brentq(f, IV_LOW, IV_HIGH, xtol=1e-10, maxiter=200)
    except ValueError:  # no sign change: price is beyond what IV_HIGH produces
        return math.nan
