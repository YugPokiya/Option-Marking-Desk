"""Glue between the API, the database and the quant core."""

import asyncio
import csv
import io
import logging
import time
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import cache
from .metrics import FIT_SECONDS, FITS
from .models import Chain, Mark, Quote, SmileFit
from .quant.demo import demo_chain
from .quant.marking import ChainIn, MarkingConfig, QuoteIn, mark_chain
from .schemas import ChainCreate, FitOut, MarkingConfigIn, MarkOut, MarkRunOut, QuoteBase

log = logging.getLogger(__name__)
CSV_COLUMNS = ["strike", "option_type", "bid", "ask", "last", "volume", "open_interest", "quote_time"]


class NotFound(Exception):
    pass


async def create_chain(session: AsyncSession, data: ChainCreate, source: str = "api") -> Chain:
    chain = Chain(
        underlying=data.underlying.upper(),
        expiry=data.expiry,
        as_of=data.as_of,
        spot=data.spot,
        rate=data.rate,
        div_yield=data.div_yield,
        source=source,
        quotes=[Quote(**q.model_dump()) for q in data.quotes],
    )
    session.add(chain)
    await session.commit()
    return chain


def demo_chain_create(underlying: str = "NIFTY", seed: int = 7, days: int = 30) -> ChainCreate:
    ch = demo_chain(seed=seed, days=days)
    return ChainCreate(
        underlying=underlying,
        expiry=ch.expiry,
        as_of=ch.as_of,
        spot=ch.spot,
        rate=ch.rate,
        div_yield=ch.div_yield,
        quotes=[QuoteBase(**asdict(q)) for q in ch.quotes],
    )


def parse_quotes_csv(raw: bytes) -> list[QuoteBase]:
    """CSV with header: strike,option_type,bid,ask,last,volume,open_interest,quote_time (last 4 optional)."""
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"strike", "option_type", "bid", "ask"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    out = []
    for i, row in enumerate(reader, start=2):
        clean = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k in CSV_COLUMNS}
        clean = {k: v for k, v in clean.items() if v not in ("", None, "-")}
        try:
            out.append(QuoteBase(**clean))
        except Exception as e:
            raise ValueError(f"row {i}: {e}") from e
    if not out:
        raise ValueError("CSV has no rows")
    return out


async def list_chains(session: AsyncSession, limit: int, offset: int) -> list[dict]:
    n_quotes = select(Quote.chain_id, func.count().label("n")).group_by(Quote.chain_id).subquery()
    rows = (
        await session.execute(
            select(Chain, func.coalesce(n_quotes.c.n, 0))
            .outerjoin(n_quotes, n_quotes.c.chain_id == Chain.id)
            .options(selectinload(Chain.fits))
            .order_by(Chain.as_of.desc(), Chain.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    out = []
    for chain, n in rows:
        d = {
            c: getattr(chain, c)
            for c in ("id", "underlying", "expiry", "as_of", "spot", "rate", "div_yield", "source", "created_at")
        }
        d["n_quotes"] = n
        d["latest_fit"] = chain.fits[0] if chain.fits else None
        out.append(d)
    return out


async def get_chain(session: AsyncSession, chain_id: int, with_quotes: bool = True) -> Chain:
    opts = [selectinload(Chain.fits)] + ([selectinload(Chain.quotes)] if with_quotes else [])
    chain = (await session.execute(select(Chain).where(Chain.id == chain_id).options(*opts))).scalar_one_or_none()
    if chain is None:
        raise NotFound(f"chain {chain_id} not found")
    return chain


async def delete_chain(session: AsyncSession, chain_id: int) -> None:
    chain = await get_chain(session, chain_id, with_quotes=False)
    await session.delete(chain)
    await session.commit()
    await cache.invalidate(chain_id)


def _to_quant(chain: Chain) -> ChainIn:
    return ChainIn(
        spot=chain.spot,
        as_of=chain.as_of,
        expiry=chain.expiry,
        rate=chain.rate,
        div_yield=chain.div_yield,
        quotes=tuple(
            QuoteIn(
                strike=q.strike,
                option_type=q.option_type,
                bid=q.bid,
                ask=q.ask,
                last=q.last,
                volume=q.volume,
                open_interest=q.open_interest,
                quote_time=q.quote_time,
            )
            for q in chain.quotes
        ),
    )


async def run_marking(session: AsyncSession, chain_id: int, cfg_in: MarkingConfigIn) -> MarkRunOut:
    chain = await get_chain(session, chain_id)
    cfg = MarkingConfig(**cfg_in.model_dump())
    start = time.perf_counter()
    # CPU-bound (scipy): keep the event loop free for other requests
    result = await asyncio.to_thread(mark_chain, _to_quant(chain), cfg)
    elapsed = time.perf_counter() - start
    f = result.fit
    fit = SmileFit(
        chain_id=chain.id,
        method=f.method,
        params=f.params,
        forward=f.forward,
        forward_source=f.forward_source,
        discount_factor=f.df,
        t=f.t,
        rmse_vol=f.rmse_vol,
        n_points=f.n_points,
        arbitrage_free=f.arbitrage_free,
        min_g=f.min_g,
        k_min=f.k_min,
        k_max=f.k_max,
        config=cfg_in.model_dump(),
        duration_ms=elapsed * 1000,
        marks=[Mark(**asdict(m)) for m in result.marks],
    )
    session.add(fit)
    await session.commit()
    await session.refresh(fit, attribute_names=["created_at"])
    FITS.labels(f.method, str(f.arbitrage_free).lower()).inc()
    FIT_SECONDS.observe(elapsed)
    log.info(
        "marked chain",
        extra={"chain_id": chain.id, "fit_id": fit.id, "method": f.method, "duration_ms": round(elapsed * 1000, 1)},
    )
    out = MarkRunOut(fit=FitOut.model_validate(fit), marks=[MarkOut.model_validate(m) for m in fit.marks])
    await cache.set_latest(chain.id, out.model_dump(mode="json"))
    return out


async def get_marks(session: AsyncSession, chain_id: int, fit_id: int | None = None) -> MarkRunOut:
    if fit_id is None:
        cached = await cache.get_latest(chain_id)
        if cached:
            return MarkRunOut.model_validate(cached)
    q = select(SmileFit).where(SmileFit.chain_id == chain_id).options(selectinload(SmileFit.marks))
    q = q.where(SmileFit.id == fit_id) if fit_id is not None else q.order_by(SmileFit.id.desc()).limit(1)
    fit = (await session.execute(q)).scalar_one_or_none()
    if fit is None:
        await get_chain(session, chain_id, with_quotes=False)  # 404 if the chain itself is missing
        which = f"run {fit_id}" if fit_id else "run"
        raise NotFound(f"no marking {which} for chain {chain_id}; POST /chains/{chain_id}/mark first")
    out = MarkRunOut(fit=FitOut.model_validate(fit), marks=[MarkOut.model_validate(m) for m in fit.marks])
    if fit_id is None:
        await cache.set_latest(chain_id, out.model_dump(mode="json"))
    return out


async def list_fits(session: AsyncSession, chain_id: int) -> list[SmileFit]:
    await get_chain(session, chain_id, with_quotes=False)
    return list(
        (
            await session.execute(
                select(SmileFit).where(SmileFit.chain_id == chain_id).order_by(SmileFit.id.desc()).limit(100)
            )
        ).scalars()
    )


def parse_dt(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"{field} must be ISO-8601, e.g. 2026-11-26T15:30:00+05:30") from e
