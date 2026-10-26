"""End-to-end through the API against real Postgres + Redis."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.cache import get_redis
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_demo_chain_mark_and_read_back(client):
    r = await client.post("/chains/demo", params={"seed": 11})
    assert r.status_code == 201, r.text
    chain = r.json()
    cid = chain["id"]
    assert chain["n_quotes"] > 50 and chain["latest_fit"] is None

    # no marking run yet
    assert (await client.get(f"/chains/{cid}/marks")).status_code == 404

    r = await client.post(f"/chains/{cid}/mark", json={"max_spread_pct": 0.08})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["fit"]["method"] == "svi" and run["fit"]["arbitrage_free"]
    assert run["fit"]["config"]["max_spread_pct"] == 0.08
    illiquid = [m for m in run["marks"] if not m["liquid"]]
    assert illiquid and all(m["method"] != "market_mid" for m in illiquid)

    # cached in Redis, and the cached copy is what GET returns
    assert await get_redis().exists(f"omd:chain:{cid}:latest")
    assert (await client.get(f"/chains/{cid}/marks")).json() == run

    smile = (await client.get(f"/chains/{cid}/smile", params={"points": 50})).json()
    assert len(smile["curve"]) == 50 and smile["market"]

    # a second run is kept as history; summary shows the latest
    await client.post(f"/chains/{cid}/mark")
    fits = (await client.get(f"/chains/{cid}/fits")).json()
    assert len(fits) == 2 and fits[0]["id"] > fits[1]["id"]
    detail = (await client.get(f"/chains/{cid}")).json()
    assert detail["latest_fit"]["id"] == fits[0]["id"] and len(detail["quotes"]) == chain["n_quotes"]
    old = (await client.get(f"/chains/{cid}/marks", params={"fit_id": fits[1]["id"]})).json()
    assert old["fit"]["id"] == fits[1]["id"]

    listed = (await client.get("/chains")).json()
    assert any(c["id"] == cid and c["latest_fit"] for c in listed)

    assert (await client.delete(f"/chains/{cid}")).status_code == 204
    assert (await client.get(f"/chains/{cid}")).status_code == 404
    assert not await get_redis().exists(f"omd:chain:{cid}:latest")


async def test_csv_upload_then_mark(client):
    rows = ["strike,option_type,bid,ask,last,volume,open_interest,quote_time"]
    # a tiny, tight chain around 25000: enough for a quadratic fit
    for k, c, p in [(24600, 470, 40), (24800, 300, 75), (25000, 170, 140), (25200, 85, 250), (25400, 38, 400)]:
        rows.append(f"{k},CE,{c - 1},{c + 1},{c},500,2000,2026-11-02T10:00:00+05:30")
        rows.append(f"{k},PE,{p - 1},{p + 1},{p},500,2000,2026-11-02T10:00:00+05:30")
    rows.append("26500,CE,,9.5,,0,10,2026-11-02T09:20:00+05:30")  # illiquid far call, no bid
    files = {"file": ("chain.csv", "\n".join(rows).encode(), "text/csv")}
    form = {
        "underlying": "nifty",
        "expiry": "2026-11-26T15:30:00+05:30",
        "as_of": "2026-11-02T10:05:00+05:30",
        "spot": "25000",
        "rate": "0.065",
    }
    r = await client.post("/chains/upload", files=files, data=form)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["underlying"] == "NIFTY" and r.json()["n_quotes"] == 11

    run = (await client.post(f"/chains/{cid}/mark")).json()
    far = next(m for m in run["marks"] if m["strike"] == 26500)
    assert not far["liquid"] and set(far["reasons"]) >= {"no_bid", "low_volume", "stale"}
    assert 0 < far["mark"] <= 9.5
    await client.delete(f"/chains/{cid}")


async def test_bad_upload_is_422(client):
    files = {"file": ("x.csv", b"strike,bid\n1,2\n", "text/csv")}
    r = await client.post(
        "/chains/upload", files=files, data={"underlying": "X", "expiry": "2026-11-26T15:30:00+05:30", "spot": "1"}
    )
    assert r.status_code == 422 and "missing columns" in r.text


async def test_unknown_chain_is_404(client):
    assert (await client.post("/chains/999999/mark")).status_code == 404
