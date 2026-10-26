import numpy as np
import pytest

from app.quant.svi import SVIParams, butterfly_g, fit_svi, total_variance

TRUE = SVIParams(a=0.0009, b=0.022, rho=-0.55, m=0.01, sigma=0.06)


def test_fit_recovers_smile_from_clean_data():
    k = np.linspace(-0.15, 0.12, 25)
    fit = fit_svi(k, total_variance(k, TRUE))
    assert fit.arbitrage_free
    assert np.max(np.abs(total_variance(k, fit.params) - total_variance(k, TRUE))) < 2e-6


def test_fit_is_robust_to_noise():
    rng = np.random.default_rng(1)
    k = np.linspace(-0.15, 0.12, 25)
    w = total_variance(k, TRUE) * (1 + rng.normal(0, 0.01, k.size))
    fit = fit_svi(k, w)
    t = 30 / 365
    vol_err = np.sqrt(total_variance(k, fit.params) / t) - np.sqrt(total_variance(k, TRUE) / t)
    assert np.max(np.abs(vol_err)) < 0.003  # 0.3 vol points
    assert fit.arbitrage_free


def test_butterfly_check_flags_an_arbitrageable_smile():
    bad = SVIParams(a=-0.01, b=0.5, rho=-0.99, m=0.0, sigma=0.01)  # violates g(k) >= 0
    assert butterfly_g(np.linspace(-0.3, 0.3, 61), bad).min() < 0


def test_needs_five_points():
    with pytest.raises(ValueError):
        fit_svi([0.0, 0.1, 0.2, 0.3], [0.001] * 4)
