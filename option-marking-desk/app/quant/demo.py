"""Synthetic NIFTY-style chain with realistic liquidity decay into the wings (for demos and tests)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from . import black
from .marking import ChainIn, QuoteIn, year_fraction
from .svi import SVIParams, total_variance

IST = timezone(timedelta(hours=5, minutes=30))
TRUE_PARAMS = SVIParams(a=0.0009, b=0.022, rho=-0.55, m=0.01, sigma=0.06)


def demo_chain(
    *,
    spot: float = 24850.0,
    days: int = 30,
    rate: float = 0.065,
    div_yield: float = 0.012,
    step: float = 100.0,
    n_each_side: int = 28,
    seed: int = 7,
    params: SVIParams = TRUE_PARAMS,
    as_of: datetime | None = None,
) -> ChainIn:
    rng = np.random.default_rng(seed)
    as_of = as_of or datetime.now(IST).replace(microsecond=0)
    expiry = (as_of + timedelta(days=days)).replace(hour=15, minute=30, second=0)
    t = year_fraction(as_of, expiry)
    df = math.exp(-rate * t)
    fwd = spot * math.exp((rate - div_yield) * t)
    atm = round(spot / step) * step
    strikes = atm + step * np.arange(-n_each_side, n_each_side + 1)

    quotes: list[QuoteIn] = []
    for strike in strikes:
        k = math.log(strike / fwd)
        vol = math.sqrt(total_variance(k, params) / t)
        dist = abs(k) / 0.04  # ~0 at the money, >3 deep in the wings
        for opt in ("C", "P"):
            is_call = opt == "C"
            fair = float(black.price(fwd, strike, t, vol, df, is_call))
            if fair < 0.05:
                continue
            tick = 0.05
            half_spread = max(tick, fair * (0.004 + 0.02 * dist**1.6)) + rng.uniform(0, tick)
            noise = rng.normal(0, 0.15 * half_spread)
            bid = max(round(round((fair - half_spread + noise) / tick) * tick, 2), 0.0)
            ask = round(round((fair + half_spread + noise) / tick) * tick, 2)
            volume = int(max(0.0, rng.normal(40000 * math.exp(-1.2 * dist), 500)))
            oi = int(volume * rng.uniform(2, 6)) + int(rng.uniform(0, 300))
            age_min = float(rng.exponential(1 + 6 * dist))
            if dist > 2.5 and rng.random() < 0.35:
                bid = 0.0  # no bid in the far wings
            quotes.append(
                QuoteIn(
                    strike=float(strike),
                    option_type=opt,
                    bid=bid or None,
                    ask=ask or None,
                    last=round(round(fair / tick) * tick, 2) if volume else None,
                    volume=volume,
                    open_interest=oi,
                    quote_time=as_of - timedelta(minutes=age_min),
                )
            )
    return ChainIn(spot=spot, as_of=as_of, expiry=expiry, rate=rate, div_yield=div_yield, quotes=tuple(quotes))
