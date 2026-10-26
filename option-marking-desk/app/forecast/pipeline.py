"""Daily job: ingest bhavcopy -> surfaces -> (re)train -> forecast -> checks + Claude review -> store."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from ..config import get_settings
from ..models import BhavContract, ForecastModel, IVForecast, IVSurface
from . import bhavcopy
from .features import FEATURE_COLS, make_features, training_frame
from .model import backtest_all, choose, dumps, fit_final, loads
from .review import build_payload, review
from .sanity import run_checks
from .surface import GRID_COLS, K_GRID, SurfaceConfig, daily_surface

log = logging.getLogger(__name__)
Fetcher = Callable[[date], bytes | None]


def lock_key(name: str) -> int:
    return int(hashlib.blake2b(name.encode(), digest_size=7).hexdigest(), 16)  # stable 56-bit lock id


async def try_lock(conn: AsyncConnection, name: str) -> bool:
    """Session-level advisory lock (held until the connection closes, independent of transactions)."""
    got = bool((await conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": lock_key(name)})).scalar())
    # end the implicit transaction the query opened: otherwise Sessions bound to this connection
    # would only create savepoints, and their commits would be rolled back when the connection closes
    await conn.commit()
    return got


# ------------------------------------------------------------------ ingest
async def last_ingested(session: AsyncSession, symbol: str) -> date | None:
    return (
        await session.execute(
            select(BhavContract.date).where(BhavContract.symbol == symbol).order_by(BhavContract.date.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def ingest_frame(session: AsyncSession, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    rows = frame.assign(strike=frame["strike"].fillna(0.0), opt_type=frame["opt_type"].fillna("F")).to_dict("records")
    for r in rows:
        for k in ("close", "settle", "last", "underlying"):
            if r[k] is not None and not np.isfinite(r[k]):
                r[k] = None
    for i in range(0, len(rows), 2000):
        await session.execute(
            insert(BhavContract).values(rows[i : i + 2000]).on_conflict_do_nothing(constraint="uq_bhav_contract")
        )
    await session.commit()
    return len(rows)


async def ingest_range(session: AsyncSession, symbols: set[str], start: date, end: date, fetch: Fetcher) -> list[date]:
    got = []
    for d in bhavcopy.business_days(start, end):
        raw = fetch(d)
        if raw is None:
            continue
        frame = bhavcopy.parse(raw, symbols)
        if not frame.empty:
            await ingest_frame(session, frame)
            got.append(d)
            log.info("ingested %s (%d contracts)", d, len(frame))
    return got


def dir_fetcher(path: Path) -> Fetcher:
    """Read zips from a folder (manual downloads, a cache, or synthetic data)."""
    return lambda d: (path / bhavcopy.filename(d)).read_bytes() if (path / bhavcopy.filename(d)).exists() else None


def nse_fetcher(cache_dir: str = "") -> Fetcher:
    dl = bhavcopy.Downloader(Path(cache_dir) if cache_dir else None)
    return dl.fetch


# ------------------------------------------------------------------ surfaces
async def _contracts(session: AsyncSession, symbol: str, d: date) -> pd.DataFrame:
    res = await session.execute(select(BhavContract).where(BhavContract.symbol == symbol, BhavContract.date == d))
    rows = [{c: getattr(r, c) for c in bhavcopy.COLUMNS} for r in res.scalars()]
    df = pd.DataFrame(rows, columns=bhavcopy.COLUMNS)
    df.loc[df["instr"] == "FUT", ["strike", "opt_type"]] = [None, None]
    return df


async def update_surfaces(session: AsyncSession, symbol: str, cfg: SurfaceConfig) -> int:
    have = set((await session.execute(select(IVSurface.date).where(IVSurface.symbol == symbol))).scalars())
    dates = sorted(
        set(
            (await session.execute(select(BhavContract.date).where(BhavContract.symbol == symbol).distinct())).scalars()
        )
        - have
    )
    warm: dict = {}
    n = 0
    for d in dates:
        row = daily_surface(await _contracts(session, symbol, d), cfg, warm)
        if row is None:
            log.warning("no usable smile for %s %s", symbol, d)
            continue
        session.add(
            IVSurface(
                symbol=symbol,
                date=d,
                spot=row["spot"],
                ivs={c: row[c] for c in GRID_COLS},
                stats={k: v for k, v in row.items() if k not in [*GRID_COLS, "date", "symbol", "spot"]},
            )
        )
        n += 1
        if n % 50 == 0:
            await session.commit()
    await session.commit()
    return n


async def load_surfaces(session: AsyncSession, symbol: str) -> pd.DataFrame:
    res = await session.execute(select(IVSurface).where(IVSurface.symbol == symbol).order_by(IVSurface.date))
    rows = [{"date": s.date, "symbol": s.symbol, "spot": s.spot, **s.ivs, **s.stats} for s in res.scalars()]
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ model
async def latest_model(session: AsyncSession, symbol: str) -> ForecastModel | None:
    return (
        await session.execute(
            select(ForecastModel).where(ForecastModel.symbol == symbol).order_by(ForecastModel.id.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def train(session: AsyncSession, symbol: str, *, min_train: int = 200, refit_every: int = 20) -> ForecastModel:
    tr = training_frame(make_features(await load_surfaces(session, symbol)))
    if len(tr) < min_train + 40:
        raise ValueError(f"{symbol}: {len(tr)} usable days; need at least {min_train + 40} to train and backtest")
    skills = backtest_all(tr, min_train=min_train, refit_every=refit_every)
    algo = choose(skills)
    m = ForecastModel(
        symbol=symbol,
        algo=algo,
        train_start=tr["date"].iloc[0],
        train_end=tr["date"].iloc[-1],
        n_train=len(tr),
        features=FEATURE_COLS,
        backtest={a: s.as_dict() for a, s in skills.items()},
        blob=dumps(fit_final(tr, algo)),
    )
    session.add(m)
    await session.commit()
    log.info("trained %s model for %s: %s", algo, symbol, {a: round(s.mean_skill, 3) for a, s in skills.items()})
    return m


def model_meta(m: ForecastModel) -> dict:
    chosen = m.backtest.get(m.algo, {})
    return {
        "algo": m.algo,
        "version": m.id,
        "train_end": str(m.train_end),
        "n_test": chosen.get("n_test"),
        "mean_skill": chosen.get("mean_skill"),
        "rmse_vp": chosen.get("rmse_vp"),
        "rmse_rw_vp": m.backtest.get("rw", {}).get("rmse_rw_vp") or chosen.get("rmse_rw_vp"),
    }


# ------------------------------------------------------------------ forecast
async def forecast(
    session: AsyncSession, symbol: str, *, today: date | None = None, client=None, review_enabled: bool | None = None
) -> IVForecast:
    s = get_settings()
    today = today or datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    surf = await load_surfaces(session, symbol)
    if surf.empty:
        raise ValueError(f"no surfaces for {symbol}; run backfill first")
    feat = make_features(surf)
    m = await latest_model(session, symbol)
    if m is None or (surf["date"].iloc[-1] - m.train_end).days > s.model_max_age_days + 1:
        m = await train(session, symbol)
    meta = model_meta(m)

    last = feat.iloc[-1]
    x = last[FEATURE_COLS].astype(float).to_numpy()[None, :]
    if np.isnan(x).any():
        raise ValueError(f"features incomplete for {last['date']}: need ~20 sessions of history")
    delta = dict(zip(GRID_COLS, loads(m.blob).predict(x)[0].tolist(), strict=True))
    surf_row = surf.iloc[-1].to_dict()

    checks = run_checks(
        today=today,
        surf_row=surf_row,
        history=surf,
        feat_row=last,
        feat_hist=feat.iloc[:-1],
        predicted_delta=delta,
        model_meta=meta,
    )
    payload = build_payload(
        surf_row=surf_row,
        prev_row=surf.iloc[-2].to_dict() if len(surf) > 1 else None,
        recent=surf.tail(10).to_dict("records"),
        predicted=delta,
        model_meta=meta,
        checks=checks,
        feature_row=last.to_dict(),
    )
    enabled = s.review_enabled if review_enabled is None else review_enabled
    result = review(
        payload, checks, client=client, model_id=s.bedrock_model_id, enabled=enabled, required=s.review_required
    )
    if not enabled:  # explicit opt-out (local runs): rules still decide
        result.error = "claude review disabled"

    await session.execute(delete(IVForecast).where(IVForecast.symbol == symbol, IVForecast.as_of == surf_row["date"]))
    fc = IVForecast(
        symbol=symbol,
        as_of=surf_row["date"],
        model_id=m.id,
        grid=list(K_GRID),
        current=[surf_row[c] for c in GRID_COLS],
        predicted=[surf_row[c] + delta[c] for c in GRID_COLS],
        review_status=result.status,
        review=result.as_dict() | {"payload": payload},
    )
    session.add(fc)
    await session.commit()
    log.info(
        "forecast %s %s: status=%s tokens=%d/%d",
        symbol,
        fc.as_of,
        result.status,
        result.input_tokens,
        result.output_tokens,
    )
    return fc


async def run_daily(
    conn: AsyncConnection,
    symbols: Iterable[str],
    *,
    fetch: Fetcher,
    today: date | None = None,
    backfill_from: date | None = None,
    client=None,
    review_enabled: bool | None = None,
) -> list[IVForecast]:
    """The scheduled entry point. Safe to start on every instance: only one wins the advisory lock."""
    if not await try_lock(conn, "omd-forecast-daily"):
        log.info("another instance holds the forecast lock; exiting")
        return []
    s = get_settings()
    cfg = SurfaceConfig(rate=s.risk_free_rate)
    today = today or datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    out = []
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        for sym in symbols:
            start = backfill_from
            if start is None:
                last = await last_ingested(session, sym)
                start = (last + timedelta(days=1)) if last else today - timedelta(days=30)
            new_days = await ingest_range(session, {sym}, start, today, fetch)
            await update_surfaces(session, sym, cfg)
            latest = (
                await session.execute(
                    select(IVSurface.date).where(IVSurface.symbol == sym).order_by(IVSurface.date.desc()).limit(1)
                )
            ).scalar_one_or_none()
            done = (
                await session.execute(select(IVForecast).where(IVForecast.symbol == sym, IVForecast.as_of == latest))
            ).scalar_one_or_none()
            if done is not None and not new_days and done.review_status != "block":
                log.info(
                    "%s: forecast for %s already published and no new data; skipping (no tokens spent)", sym, latest
                )
                out.append(done)
                continue
            out.append(await forecast(session, sym, today=today, client=client, review_enabled=review_enabled))
    return out
