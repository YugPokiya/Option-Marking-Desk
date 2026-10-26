import math
from dataclasses import replace
from datetime import timedelta

import pytest

from app.quant.demo import TRUE_PARAMS, demo_chain
from app.quant.marking import MarkingConfig, QuoteIn, classify, mark_chain
from app.quant.svi import total_variance


@pytest.fixture(scope="module")
def result():
    return mark_chain(demo_chain())


def test_forward_from_parity(result):
    ch = demo_chain()
    carry = ch.spot * math.exp((ch.rate - ch.div_yield) * result.fit.t)
    assert result.fit.forward_source == "parity"
    assert result.fit.forward == pytest.approx(carry, rel=2e-4)


def test_svi_fit_tracks_true_smile_on_illiquid_strikes(result):
    f = result.fit
    assert f.method == "svi" and f.arbitrage_free
    for m in result.marks:
        if not m.liquid:
            true_iv = math.sqrt(total_variance(math.log(m.strike / f.forward), TRUE_PARAMS) / f.t)
            assert abs(m.model_iv - true_iv) < 0.005, (m.strike, m.option_type)


def test_liquid_marked_at_mid_illiquid_from_model(result):
    for m in result.marks:
        if m.liquid:
            assert m.method == "market_mid" and m.mark == pytest.approx(m.mid)
        else:
            assert m.method.startswith("model") or m.method == "intrinsic_floor"


def test_marks_respect_quotes_and_intrinsic(result):
    df, fwd = result.fit.df, result.fit.forward
    for m in result.marks:
        if m.bid:
            assert m.mark >= m.bid - 1e-9
        if m.ask:
            assert m.mark <= m.ask + 1e-9
        intrinsic = df * max((fwd - m.strike) if m.option_type == "C" else (m.strike - fwd), 0.0)
        assert m.mark >= intrinsic - 1e-9


def test_band_contains_model_and_widens_in_wings(result):
    for m in result.marks:
        assert m.lower <= m.model_price <= m.upper
    calls = [m for m in result.marks if m.option_type == "C"]
    atm = min(calls, key=lambda m: abs(m.strike - result.fit.forward))
    wing = max(calls, key=lambda m: m.strike)
    rel = lambda m: (m.upper - m.lower) / max(m.model_price, 1e-9)  # noqa: E731
    assert rel(wing) > rel(atm)


def test_classification_reasons():
    as_of = demo_chain().as_of
    cfg = MarkingConfig()
    q = QuoteIn(strike=1, option_type="C", bid=None, ask=10, volume=0, quote_time=as_of - timedelta(hours=1))
    assert set(classify(q, as_of, cfg)) == {"no_bid", "low_volume", "stale"}
    wide = QuoteIn(strike=1, option_type="C", bid=8, ask=12, volume=100, quote_time=as_of)
    assert classify(wide, as_of, cfg) == ["wide_spread"]
    assert classify(replace(wide, bid=9.9, ask=10.1), as_of, cfg) == []


def test_falls_back_to_carry_forward_and_simpler_fits():
    ch = demo_chain()
    # keep only 3 liquid OTM calls -> quadratic, and no puts -> no parity forward
    # (strikes > 1.01 x spot so they are above the carry forward, i.e. out of the money)
    otm_calls = (q for q in ch.quotes if q.option_type == "C" and q.strike > ch.spot * 1.01)
    calls = sorted(otm_calls, key=lambda q: q.strike)[:3]
    tight = tuple(replace(q, bid=round(q.ask * 0.99, 2), volume=1000, quote_time=ch.as_of) for q in calls)
    r = mark_chain(replace(ch, quotes=tight))
    assert r.fit.forward_source == "carry" and r.fit.method == "quadratic"
    r1 = mark_chain(replace(ch, quotes=tight[:1]))
    assert r1.fit.method == "flat"


def test_rejects_expired_or_empty_chain():
    ch = demo_chain()
    with pytest.raises(ValueError):
        mark_chain(replace(ch, quotes=()))
    with pytest.raises(ValueError):
        mark_chain(replace(ch, expiry=ch.as_of - timedelta(days=1)))
