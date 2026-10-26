"""Integration tests against the real Postgres + Redis started by CI (or docker locally)."""

import os

import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import app

pytestmark = pytest.mark.integration


async def test_postgres_roundtrip_and_migrations_applied():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as conn:
        assert (await conn.execute(text("select 1"))).scalar() == 1
        version = (await conn.execute(text("select version_num from alembic_version"))).scalar()
        assert version, "alembic upgrade head should have run"
    await engine.dispose()


async def test_redis_roundtrip():
    r = aioredis.from_url(os.environ["REDIS_URL"])
    await r.set("omd:test", "ok", ex=10)
    assert await r.get("omd:test") == b"ok"
    await r.aclose()


def test_readyz_sees_db_and_redis():
    with TestClient(app) as client:  # runs lifespan startup (pools, caches)
        assert client.get("/readyz").status_code == 200
