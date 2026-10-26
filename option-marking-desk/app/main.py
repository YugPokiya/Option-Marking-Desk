"""Option Marking Desk API.

Behind the gateway (Istio or nginx) every route is served under /api with the prefix stripped,
so routes here are declared at the root: /chains, /healthz, ...
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .api import chains, forecasts, health, pricing
from .cache import close_redis
from .config import get_settings
from .db import dispose_engine
from .logging import setup_logging
from .metrics import MetricsMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="Option Marking Desk",
        version=__version__,
        summary="Marks illiquid options from a fitted, arbitrage-checked volatility smile.",
        root_path=settings.api_root_path,
        lifespan=lifespan,
    )
    app.add_middleware(MetricsMiddleware)
    app.include_router(health.router)
    app.include_router(chains.router)
    app.include_router(pricing.router)
    app.include_router(forecasts.router)
    return app


app = create_app()
