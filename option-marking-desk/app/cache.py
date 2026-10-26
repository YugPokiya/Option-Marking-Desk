"""Redis cache for the latest marking run per chain. Best-effort: a Redis outage never fails a request."""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from .config import get_settings

log = logging.getLogger(__name__)
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
    return _client


def _key(chain_id: int) -> str:
    return f"omd:chain:{chain_id}:latest"


async def get_latest(chain_id: int) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(_key(chain_id))
        return json.loads(raw) if raw else None
    except Exception:
        log.warning("cache read failed", exc_info=True)
        return None


async def set_latest(chain_id: int, value: dict[str, Any]) -> None:
    try:
        await get_redis().set(_key(chain_id), json.dumps(value, default=str), ex=get_settings().cache_ttl_seconds)
    except Exception:
        log.warning("cache write failed", exc_info=True)


async def invalidate(chain_id: int) -> None:
    try:
        await get_redis().delete(_key(chain_id))
    except Exception:
        log.warning("cache delete failed", exc_info=True)


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
