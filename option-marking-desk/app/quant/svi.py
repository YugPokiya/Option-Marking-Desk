"""Raw SVI smile (Gatheral 2004) with a butterfly-arbitrage penalty.

Total implied variance as a function of log-moneyness k = ln(K/F):

    w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

Implied vol is sqrt(w(k) / T).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def as_array(self) -> np.ndarray:
        return np.array([self.a, self.b, self.rho, self.m, self.sigma])


def total_variance(k, p: SVIParams):
    k = np.asarray(k, dtype=float)
    x = k - p.m
    return p.a + p.b * (p.rho * x + np.sqrt(x * x + p.sigma * p.sigma))


def _derivatives(k, p: SVIParams):
    x = np.asarray(k, dtype=float) - p.m
    r = np.sqrt(x * x + p.sigma * p.sigma)
    w = p.a + p.b * (p.rho * x + r)
    w1 = p.b * (p.rho + x / r)
    w2 = p.b * p.sigma * p.sigma / r**3
    return w, w1, w2


def butterfly_g(k, p: SVIParams):
    """Gatheral's g(k). The smile is free of butterfly arbitrage where g(k) >= 0 (and w > 0)."""
    w, w1, w2 = _derivatives(k, p)
    w = np.maximum(w, 1e-12)
    return (1 - k * w1 / (2 * w)) ** 2 - (w1 * w1 / 4) * (1 / w + 0.25) + w2 / 2


@dataclass(frozen=True)
class SVIFit:
    params: SVIParams
    rmse_w: float  # weighted RMSE in total variance
    min_g: float  # min of g(k) over the check grid
    arbitrage_free: bool
    k_min: float
    k_max: float
    n_points: int


def fit_svi(k, w, weights=None, *, penalty: float = 50.0, x0: SVIParams | None = None) -> SVIFit:
    """Fit raw SVI to market total variances ``w`` at log-moneyness ``k``.

    Weighted least squares with bounds, a soft penalty on negative g(k) on a grid wider than
    the data (so the wings we extrapolate into stay arbitrage-free), and several starting points.
    """
    k = np.asarray(k, dtype=float)
    w = np.asarray(w, dtype=float)
    if k.size < 5:
        raise ValueError("SVI needs at least 5 points")
    weights = np.ones_like(k) if weights is None else np.asarray(weights, dtype=float)
    weights = weights / weights.mean()
    sw = np.sqrt(weights)

    span = max(k.max() - k.min(), 0.05)
    grid = np.linspace(k.min() - span, k.max() + span, 81)
    w_scale = max(float(np.median(w)), 1e-6)

    lb = [-w.max(), 1e-6, -0.999, k.min() - span, 1e-4]
    ub = [w.max() * 2, 10 * w_scale / span + 1.0, 0.999, k.max() + span, 2.0]

    def residuals(x, lam):
        p = SVIParams(*x)
        fit = (total_variance(k, p) - w) / w_scale * sw
        if lam == 0:
            return fit
        g = butterfly_g(grid, p)
        wg = total_variance(grid, p)
        arb = lam * np.concatenate([np.minimum(g, 0.0), np.minimum(wg / w_scale, 0.0)])
        return np.concatenate([fit, arb])

    atm = float(np.interp(0.0, k, w)) if k.min() <= 0 <= k.max() else float(w.min())
    starts = []
    for rho0 in (-0.6, -0.2, 0.2):
        for sigma0 in (0.05, 0.2):
            starts.append([max(atm * 0.5, 1e-6), max(atm, 1e-4) / max(sigma0, 0.05), rho0, 0.0, sigma0])
    if x0 is not None:  # warm start (e.g. yesterday's fit): try it first plus one generic start
        starts = [list(x0.as_array()), starts[0]]

    def jac_smooth(x, lam):
        # exact Jacobian of the smooth residuals (lam == 0): d w(k) / d(a, b, rho, m, sigma)
        _a, b, rho, m, sig = x
        xk = k - m
        r = np.sqrt(xk * xk + sig * sig)
        cols = [np.ones_like(k), rho * xk + r, b * xk, b * (-rho - xk / r), b * sig / r]
        return np.column_stack(cols) * (sw / w_scale)[:, None]

    def solve(lam, start, nfev):
        start = np.clip(start, np.array(lb) + 1e-9, np.array(ub) - 1e-9)
        return least_squares(
            residuals,
            start,
            jac=jac_smooth if lam == 0 else "2-point",
            args=(lam,),
            bounds=(lb, ub),
            method="trf",
            x_scale="jac",
            max_nfev=nfev,
            ftol=1e-7,
            xtol=1e-7,
        )

    def arbitrage_ok(x):
        p = SVIParams(*x)
        return butterfly_g(grid, p).min() >= -1e-6 and total_variance(grid, p).min() > 0

    # Stage 1: the smooth least-squares problem (fast). Stage 2: only if that solution admits
    # butterfly arbitrage, refine it with the penalty (non-smooth, slower).
    best = min((solve(0.0, s0, 200) for s0 in starts), key=lambda r: r.cost)
    if not arbitrage_ok(best.x):
        best = solve(penalty, best.x, 3000)

    p = SVIParams(*map(float, best.x))
    resid = total_variance(k, p) - w
    rmse_w = float(np.sqrt(np.average(resid * resid, weights=weights)))
    g = butterfly_g(grid, p)
    min_g = float(g.min())
    return SVIFit(
        params=p,
        rmse_w=rmse_w,
        min_g=min_g,
        arbitrage_free=bool(min_g >= -1e-6 and total_variance(grid, p).min() > 0),
        k_min=float(k.min()),
        k_max=float(k.max()),
        n_points=int(k.size),
    )
