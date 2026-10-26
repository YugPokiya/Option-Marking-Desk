import math

import numpy as np
import pytest

from app.quant import black

F, K, T, DF = 25000.0, 25500.0, 30 / 365, math.exp(-0.065 * 30 / 365)


def test_put_call_parity():
    c = black.price(F, K, T, 0.15, DF, True)
    p = black.price(F, K, T, 0.15, DF, False)
    assert c - p == pytest.approx(DF * (F - K), abs=1e-8)


@pytest.mark.parametrize("vol", [0.05, 0.12, 0.35, 1.2])
@pytest.mark.parametrize("strike", [20000.0, 24000.0, 25000.0, 27000.0])
@pytest.mark.parametrize("is_call", [True, False])
def test_implied_vol_round_trip(vol, strike, is_call):
    px = float(black.price(F, strike, T, vol, DF, is_call))
    if px - float(black.intrinsic(F, strike, DF, is_call)) < 1e-4:
        pytest.skip("no time value left: implied vol is not identifiable")
    assert black.implied_vol(px, F, strike, T, DF, is_call) == pytest.approx(vol, abs=1e-6)


def test_implied_vol_rejects_prices_outside_bounds():
    intrinsic = float(black.intrinsic(F, 24000.0, DF, True))
    assert math.isnan(black.implied_vol(intrinsic * 0.99, F, 24000.0, T, DF, True))
    assert math.isnan(black.implied_vol(DF * F * 1.01, F, 24000.0, T, DF, True))
    assert math.isnan(black.implied_vol(0.0, F, 24000.0, T, DF, True))


def test_vega_matches_finite_difference():
    h = 1e-5
    fd = (black.price(F, K, T, 0.2 + h, DF, True) - black.price(F, K, T, 0.2 - h, DF, True)) / (2 * h)
    assert float(black.vega(F, K, T, 0.2, DF)) == pytest.approx(float(fd), rel=1e-6)


def test_vectorised():
    strikes = np.array([24000.0, 25000.0, 26000.0])
    out = black.price(F, strikes, T, 0.15, DF, np.array([True, False, True]))
    assert out.shape == (3,) and np.all(out > 0)
