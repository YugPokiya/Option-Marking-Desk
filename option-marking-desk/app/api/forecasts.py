import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_session
from ..models import IVForecast
from ..schemas import ForecastOut, ForecastSummary, ModelInfo

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


def _clean(d: dict | None) -> dict:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in (d or {}).items()}


def _out(f: IVForecast) -> ForecastOut:
    m = f.model
    chosen = m.backtest.get(m.algo, {})
    rw = m.backtest.get("rw", {})
    review = {k: v for k, v in f.review.items() if k != "payload"}  # payload is internal; keep the API small
    return ForecastOut(
        id=f.id,
        symbol=f.symbol,
        as_of=f.as_of,
        review_status=f.review_status,
        created_at=f.created_at,
        grid=f.grid,
        current=f.current,
        predicted=f.predicted,
        review=review,
        model=ModelInfo(
            id=m.id,
            algo=m.algo,
            train_start=m.train_start,
            train_end=m.train_end,
            n_train=m.n_train,
            mean_skill=chosen.get("mean_skill"),
            skill_by_k=chosen.get("skill", {}),
            rmse_vp=chosen.get("rmse_vp", {}),
            rmse_rw_vp=rw.get("rmse_rw_vp", chosen.get("rmse_rw_vp", {})),
            hit_rate=_clean(chosen.get("hit_rate")),
            all_algos={a: v.get("mean_skill") for a, v in m.backtest.items()},
        ),
    )


@router.get("", response_model=list[ForecastSummary], summary="Forecast history")
async def list_forecasts(
    symbol: str = "NIFTY", limit: int = Query(30, ge=1, le=500), session: AsyncSession = Depends(get_session)
):
    res = await session.execute(
        select(IVForecast).where(IVForecast.symbol == symbol.upper()).order_by(IVForecast.as_of.desc()).limit(limit)
    )
    return list(res.scalars())


@router.get("/latest", response_model=ForecastOut, summary="Latest next-session IV forecast + review")
async def latest(symbol: str = "NIFTY", session: AsyncSession = Depends(get_session)):
    f = (
        await session.execute(
            select(IVForecast)
            .where(IVForecast.symbol == symbol.upper())
            .options(selectinload(IVForecast.model))
            .order_by(IVForecast.as_of.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(404, f"no forecasts for {symbol.upper()} yet; run `python -m app.forecast run-daily`")
    return _out(f)


@router.get("/{forecast_id}", response_model=ForecastOut)
async def get_forecast(forecast_id: int, session: AsyncSession = Depends(get_session)):
    f = (
        await session.execute(
            select(IVForecast).where(IVForecast.id == forecast_id).options(selectinload(IVForecast.model))
        )
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(404, "forecast not found")
    return _out(f)
