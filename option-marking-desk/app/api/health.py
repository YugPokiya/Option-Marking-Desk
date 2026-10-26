import asyncio

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from ..cache import get_redis
from ..db import get_engine

router = APIRouter(tags=["ops"])


@router.get("/healthz", summary="Liveness: the process is up (no dependency checks)")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: Postgres and Redis reachable")
async def readyz(response: Response) -> dict:
    checks = {}

    async def db():
        async with get_engine().connect() as conn:
            await conn.execute(text("select 1"))

    for name, fn in (("postgres", db), ("redis", lambda: get_redis().ping())):
        try:
            await asyncio.wait_for(fn(), timeout=3)
            checks[name] = "ok"
        except Exception as e:
            checks[name] = f"error: {type(e).__name__}"
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "unavailable", "checks": checks}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
