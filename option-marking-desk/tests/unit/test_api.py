"""API tests that need no database or Redis."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_openapi_lists_core_routes():
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/chains", "/chains/{chain_id}/mark", "/chains/{chain_id}/smile", "/price", "/readyz"):
        assert p in paths


def test_price_put_call_parity():
    body = {"spot": 25000, "strike": 25500, "days": 30, "vol": 0.15, "rate": 0.065, "div_yield": 0.012}
    c = client.post("/price", json={**body, "option_type": "C"}).json()
    p = client.post("/price", json={**body, "option_type": "P"}).json()
    t = 30 / 365
    import math

    df = math.exp(-0.065 * t)
    assert abs((c["price"] - p["price"]) - df * (c["forward"] - 25500)) < 1e-6
    assert 0 < c["delta"] < 1 and -1 < p["delta"] < 0


def test_chain_validation_errors_are_422():
    bad = {
        "underlying": "NIFTY",
        "expiry": "2026-01-01T15:30:00+05:30",
        "as_of": "2026-02-01T09:15:00+05:30",
        "spot": 25000,
        "quotes": [{"strike": 25000, "option_type": "C", "bid": 10, "ask": 11}],
    }
    r = client.post("/chains", json=bad)
    assert r.status_code == 422 and "expiry must be after as_of" in r.text


def test_option_type_aliases():
    from app.schemas import QuoteBase

    assert QuoteBase(strike=1, option_type="ce").option_type == "C"
    assert QuoteBase(strike=1, option_type="PUT").option_type == "P"


def test_csv_parser_reports_bad_rows():
    import pytest

    from app.services import parse_quotes_csv

    ok = parse_quotes_csv(b"strike,option_type,bid,ask,volume\n25000,CE,10,11,5\n25000,PE,9,10,\n")
    assert [q.option_type for q in ok] == ["C", "P"] and ok[1].volume == 0
    with pytest.raises(ValueError, match="missing columns"):
        parse_quotes_csv(b"strike,bid\n1,2\n")
    with pytest.raises(ValueError, match="row 2"):
        parse_quotes_csv(b"strike,option_type,bid,ask\n-5,C,1,2\n")
