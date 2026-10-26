import math
from datetime import UTC, datetime

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import services
from ..config import get_settings
from ..db import get_session
from ..quant.svi import SVIParams, total_variance
from ..schemas import (
    ChainCreate,
    ChainDetail,
    ChainSummary,
    FitSummary,
    MarketPoint,
    MarkingConfigIn,
    MarkRunOut,
    SmileOut,
    SmilePoint,
)

router = APIRouter(prefix="/chains", tags=["chains"])
Session = Depends(get_session)


def _not_found(e: Exception) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("", response_model=list[ChainSummary], summary="List chains, newest first")
async def list_chains(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: AsyncSession = Session
):
    return await services.list_chains(session, limit, offset)


@router.post("", response_model=ChainSummary, status_code=201, summary="Create a chain from JSON")
async def create_chain(data: ChainCreate, session: AsyncSession = Session):
    chain = await services.create_chain(session, data)
    return ChainSummary.model_validate(chain).model_copy(update={"n_quotes": len(data.quotes)})


@router.post("/upload", response_model=ChainSummary, status_code=201, summary="Create a chain from a CSV file")
async def upload_chain(
    file: UploadFile = File(..., description="strike,option_type,bid,ask[,last,volume,open_interest,quote_time]"),
    underlying: str = Form(...),
    expiry: str = Form(..., examples=["2026-11-26T15:30:00+05:30"]),
    spot: float = Form(..., gt=0),
    as_of: str | None = Form(None),
    rate: float = Form(0.065),
    div_yield: float = Form(0.0),
    session: AsyncSession = Session,
):
    raw = await file.read(get_settings().max_upload_bytes + 1)
    if len(raw) > get_settings().max_upload_bytes:
        raise HTTPException(413, "file too large")
    try:
        data = ChainCreate(
            underlying=underlying,
            spot=spot,
            rate=rate,
            div_yield=div_yield,
            expiry=services.parse_dt(expiry, "expiry"),
            as_of=services.parse_dt(as_of, "as_of") if as_of else datetime.now(UTC),
            quotes=services.parse_quotes_csv(raw),
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    chain = await services.create_chain(session, data, source="upload")
    return ChainSummary.model_validate(chain).model_copy(update={"n_quotes": len(data.quotes)})


@router.post("/demo", response_model=ChainSummary, status_code=201, summary="Create a synthetic NIFTY chain")
async def demo(
    seed: int = Query(7, ge=0, le=10_000), days: int = Query(30, ge=1, le=365), session: AsyncSession = Session
):
    if not get_settings().enable_demo:
        raise HTTPException(404, "demo data is disabled")
    data = services.demo_chain_create(seed=seed, days=days)
    chain = await services.create_chain(session, data, source="demo")
    return ChainSummary.model_validate(chain).model_copy(update={"n_quotes": len(data.quotes)})


@router.get("/{chain_id}", response_model=ChainDetail)
async def get_chain(chain_id: int, session: AsyncSession = Session):
    try:
        chain = await services.get_chain(session, chain_id)
    except services.NotFound as e:
        raise _not_found(e) from e
    return ChainDetail.model_validate(chain).model_copy(
        update={
            "n_quotes": len(chain.quotes),
            "latest_fit": FitSummary.model_validate(chain.fits[0]) if chain.fits else None,
        }
    )


@router.delete("/{chain_id}", status_code=204)
async def delete_chain(chain_id: int, session: AsyncSession = Session):
    try:
        await services.delete_chain(session, chain_id)
    except services.NotFound as e:
        raise _not_found(e) from e


@router.post("/{chain_id}/mark", response_model=MarkRunOut, summary="Fit the smile and mark every strike")
async def mark(chain_id: int, cfg: MarkingConfigIn | None = None, session: AsyncSession = Session):
    try:
        return await services.run_marking(session, chain_id, cfg or MarkingConfigIn())
    except services.NotFound as e:
        raise _not_found(e) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/{chain_id}/marks", response_model=MarkRunOut, summary="Latest (or a given) marking run")
async def get_marks(chain_id: int, fit_id: int | None = None, session: AsyncSession = Session):
    try:
        return await services.get_marks(session, chain_id, fit_id)
    except services.NotFound as e:
        raise _not_found(e) from e


@router.get("/{chain_id}/fits", response_model=list[FitSummary], summary="Marking history (audit trail)")
async def list_fits(chain_id: int, session: AsyncSession = Session):
    try:
        return await services.list_fits(session, chain_id)
    except services.NotFound as e:
        raise _not_found(e) from e


@router.get("/{chain_id}/smile", response_model=SmileOut, summary="Fitted curve + market IVs for charting")
async def smile(
    chain_id: int, fit_id: int | None = None, points: int = Query(121, ge=10, le=1000), session: AsyncSession = Session
):
    try:
        run = await services.get_marks(session, chain_id, fit_id)
    except services.NotFound as e:
        raise _not_found(e) from e
    f = run.fit
    strikes = [m.strike for m in run.marks]
    k = np.linspace(math.log(min(strikes) / f.forward), math.log(max(strikes) / f.forward), points)
    if f.method == "svi":
        w = total_variance(k, SVIParams(**f.params))
    elif f.method == "quadratic":
        w = f.params["c0"] + f.params["c1"] * k + f.params["c2"] * k * k
    else:
        w = np.full_like(k, f.params["w"])
    iv = np.sqrt(np.maximum(w, 1e-10) / f.t)
    return SmileOut(
        fit_id=f.id,
        forward=f.forward,
        curve=[
            SmilePoint(strike=float(f.forward * math.exp(x)), k=float(x), model_iv=float(v))
            for x, v in zip(k, iv, strict=True)
        ],
        market=[
            MarketPoint(strike=m.strike, option_type=m.option_type, market_iv=m.market_iv, liquid=m.liquid)
            for m in run.marks
            if m.market_iv is not None
        ],
    )
