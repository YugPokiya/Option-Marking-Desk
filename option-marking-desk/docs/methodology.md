# Methodology

Code: `app/quant/`. Everything is a pure function of the chain plus a `MarkingConfig`, so a run can be reproduced from what's stored.

## 1. Time, discounting, forward

- **Time to expiry:** `T` is ACT/365 in seconds from `as_of` to `expiry` (NSE index options expire at 15:30 IST).
- **Discount factor:** `df = exp(-r·T)`, with `r` continuously compounded.
- **Forward from parity:** for liquid strikes that have both a call and a put mid, `F = K + (C − P) / df`. The estimate is the median over the three strikes where `|C − P|` is smallest, which are the most at-the-money and least sensitive to the spread.
- **Fallback:** if no such pair exists, `F = S·exp((r − q)·T)`. The run records which source was used.

## 2. Liquidity

A quote is **liquid** only if it has none of these flags:

| Flag | Rule (defaults) |
|---|---|
| `no_bid` / `no_ask` | missing or zero |
| `crossed` | ask < bid |
| `wide_spread` | (ask − bid) / mid > `max_spread_pct` (10%) |
| `low_volume` | volume < `min_volume` (1) |
| `stale` | `as_of − quote_time` > `max_quote_age_minutes` (15) |

## 3. Implied vol

The pricing model is Black-76 on the forward. Implied vol uses Brent's method on [0.01%, 500%]. Prices outside no-arbitrage bounds return no IV rather than a misleading one: below discounted intrinsic, or at or above `df·F` (calls) or `df·K` (puts).

## 4. Smile fit

The fit uses **liquid, out-of-the-money** quotes only (calls with K ≥ F, puts with K < F). Their mids carry the most time value and the least early-exercise or carry noise.

Raw SVI in total variance, with `k = ln(K/F)`:

```
w(k) = a + b·(ρ·(k − m) + √((k − m)² + σ²)),   IV(k) = √(w(k)/T)
```

**Objective:** weighted least squares on `w` (scaled by its median), with weights `1 / max(spread in vol, 0.2 vp)`. Tighter quotes count more.

**Constraints:**
- **Parameter bounds:** `b > 0`, `|ρ| < 1`, `σ > 0`.
- **Butterfly penalty:** a soft penalty on Gatheral's density condition

  ```
  g(k) = (1 − k·w'/(2w))² − (w'²/4)·(1/w + 1/4) + w''/2 ≥ 0
  ```

  is applied on a grid one data-span **beyond** each side of the data, so the wings we extrapolate into are arbitrage-free too. The same penalty applies to `w < 0`.

**Starting points:** six combinations of (ρ, σ), keeping the best.

**Reported:** fit RMSE in vol points (weighted), `min g(k)`, and `arbitrage_free = min g ≥ 0`.

With fewer than 5 points the fit falls back to a quadratic in `k` on `w` (3–4 points) or a flat vol at the most-ATM point (1–2). Both are flagged in `method`.

## 5. Marks and bands

For every quote:

- **Model value:** `model_iv = IV(k)` and `model_price = Black76(F, K, T, model_iv)`.
- **Band:** `band_vol = max(z·RMSE, min_band_vol) × (1 + distance outside the fitted k-range / k-span)`, and × 1.5 for non-SVI fits. `lower` and `upper` are the prices at `model_iv ∓ band_vol`.
- **Mark:**
  - liquid → mid (`market_mid`)
  - illiquid → `model_price`, raised to the bid (`model_clipped_bid`) or lowered to the ask (`model_clipped_ask`) if it falls outside a live quote
  - never below discounted intrinsic (`intrinsic_floor`)

## Validation

`tests/unit/test_marking.py` builds a chain from known SVI parameters with realistic liquidity decay: spreads widen, volume falls, quotes go stale and bids vanish in the wings. It then checks:

- the forward from parity matches the carry forward to within 2 bp
- model IV on every illiquid strike is within 0.5 vol points of the truth (it typically lands within 0.11)
- marks respect bid, ask and intrinsic
- bands contain the model price and widen into the wings
- the quadratic and flat fallbacks and the carry forward kick in when data is thin

## Not covered yet

- **Calendar arbitrage:** total variance increasing with T across expiries.
- **Dividends:** discrete dividends and American exercise (single stocks).
- **Weighting:** by open interest, or blending in the last trade when it is recent.
