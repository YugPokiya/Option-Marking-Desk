import pytest_asyncio

from app.cache import close_redis
from app.db import dispose_engine


@pytest_asyncio.fixture(autouse=True)
async def _fresh_pools():
    """Each test runs on its own event loop: never reuse pools across loops."""
    yield
    await dispose_engine()
    await close_redis()
