"""Full daily pipeline on synthetic bhavcopy files against real Postgres, with a fake Bedrock."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_engine
from app.forecast import pipeline as p
from app.forecast.surface import SurfaceConfig
from app.forecast.synthetic import generate
from app.main import app
from app.models import BhavContract, ForecastModel, IVForecast, IVSurface
from tests.forecast_fakes import PASS, FakeBedrock

pytestmark = pytest.mark.integration
SYM = "TESTIDX"


@pytest.fixture(scope="module")
def bhav(tmp_path_factory):
    d = tmp_path_factory.mktemp("bhav")
    days = generate(d, days=170, symbol=SYM, strike_step=200, width=0.07, seed=9)
    return d, days


async def _clean(session):
    await session.execute(delete(IVForecast).where(IVForecast.symbol == SYM))
    await session.execute(delete(ForecastModel).where(ForecastModel.symbol == SYM))
    await session.execute(delete(IVSurface).where(IVSurface.symbol == SYM))
    await session.execute(delete(BhavContract).where(BhavContract.symbol == SYM))
    await session.commit()


async def test_daily_pipeline_end_to_end(bhav):
    src, days = bhav
    fetch = p.dir_fetcher(src)
    async with get_engine().connect() as conn:
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            await _clean(s)
            # history up to the day before "today"
            await p.ingest_range(s, {SYM}, days[0], days[-2], fetch)
            assert await p.update_surfaces(s, SYM, SurfaceConfig()) >= len(days) - 3
            m = await p.train(s, SYM, min_train=100, refit_every=30)
            assert m.algo in ("rw", "ridge", "gbr") and set(m.backtest) == {"rw", "ridge", "gbr"}
            # idempotent ingest
            await p.ingest_range(s, {SYM}, days[-3], days[-2], fetch)

        fake = FakeBedrock(verdict=PASS)
        fcs = await p.run_daily(conn, [SYM], fetch=fetch, today=days[-1], client=fake)
        assert len(fcs) == 1 and len(fake.calls) == 1
        fc = fcs[0]
        assert fc.as_of == days[-1] and fc.review_status in ("pass", "warn")
        assert len(fc.predicted) == len(fc.grid) == 7
        assert fc.review["input_tokens"] == 1234 and fc.review["payload"]["date"] == str(days[-1])

    # a second instance must not run concurrently
    async with get_engine().connect() as holder, get_engine().connect() as other:
        await holder.execute(text("select pg_advisory_lock(:k)"), {"k": p.lock_key("omd-forecast-daily")})
        assert await p.run_daily(other, [SYM], fetch=fetch, today=days[-1], client=FakeBedrock(verdict=PASS)) == []
        await holder.execute(text("select pg_advisory_unlock(:k)"), {"k": p.lock_key("omd-forecast-daily")})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/forecasts/latest", params={"symbol": SYM})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["as_of"] == str(days[-1]) and "payload" not in body["review"]
        assert set(body["model"]["all_algos"]) == {"rw", "ridge", "gbr"}
        assert (await c.get("/forecasts", params={"symbol": SYM})).json()[0]["id"] == body["id"]


async def test_block_when_review_unavailable(bhav):
    _, days = bhav
    down = FakeBedrock(exc=ConnectionError("down"))
    async with get_engine().connect() as conn, AsyncSession(bind=conn, expire_on_commit=False) as s:
        fc = await p.forecast(s, SYM, today=days[-1], client=down)
        assert fc.review_status == "block" and "review unavailable" in fc.review["error"]
        await _clean(s)
