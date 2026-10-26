"""CLI:  python -m app.forecast <command>

backfill   --symbols NIFTY,BANKNIFTY --from 2023-01-01 [--to DATE] [--source-dir DIR]
train      --symbols NIFTY
run-daily  [--symbols ...] [--date DATE] [--source-dir DIR] [--no-review]
payload    --symbol NIFTY      print what Claude would receive for the latest day (no API call)
synthetic  --out DIR --days 400 [--random-walk]
"""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from ..config import get_settings
from ..db import dispose_engine, get_engine
from ..logging import setup_logging


def _symbols(v: str | None) -> list[str]:
    return [s.strip().upper() for s in (v or get_settings().forecast_symbols).split(",") if s.strip()]


async def _main(a: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession

    from . import pipeline as p
    from .review import bedrock_client

    s = get_settings()
    fetch = p.dir_fetcher(Path(a.source_dir)) if getattr(a, "source_dir", None) else p.nse_fetcher(s.bhav_cache_dir)
    try:
        async with get_engine().connect() as conn:
            if a.cmd == "backfill":
                async with AsyncSession(bind=conn) as session:
                    for sym in _symbols(a.symbols):
                        days = await p.ingest_range(session, {sym}, a.start, a.end or date.today(), fetch)
                        n = await p.update_surfaces(session, sym, p.SurfaceConfig(rate=s.risk_free_rate))
                        print(f"{sym}: ingested {len(days)} days, built {n} surfaces")
            elif a.cmd == "train":
                async with AsyncSession(bind=conn) as session:
                    for sym in _symbols(a.symbols):
                        m = await p.train(session, sym)
                        print(
                            json.dumps(
                                {
                                    "symbol": sym,
                                    "model_id": m.id,
                                    "algo": m.algo,
                                    "skill": {k: round(v["mean_skill"], 3) for k, v in m.backtest.items()},
                                }
                            )
                        )
            elif a.cmd == "run-daily":
                client = None if a.no_review else bedrock_client(s.bedrock_region)
                fcs = await p.run_daily(
                    conn, _symbols(a.symbols), fetch=fetch, today=a.date, client=client, review_enabled=not a.no_review
                )
                for f in fcs:
                    print(
                        json.dumps(
                            {
                                "symbol": f.symbol,
                                "as_of": str(f.as_of),
                                "status": f.review_status,
                                "tokens": [f.review.get("input_tokens"), f.review.get("output_tokens")],
                            }
                        )
                    )
                if any(f.review_status == "block" for f in fcs):
                    return 2
            elif a.cmd == "payload":
                async with AsyncSession(bind=conn) as session:
                    f = await p.forecast(session, a.symbol.upper(), review_enabled=False)
                    print(json.dumps(f.review["payload"], indent=2, default=str))
    finally:
        await dispose_engine()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app.forecast")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--symbols")
    b.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    b.add_argument("--to", dest="end", type=date.fromisoformat)
    b.add_argument("--source-dir")
    t = sub.add_parser("train")
    t.add_argument("--symbols")
    r = sub.add_parser("run-daily")
    r.add_argument("--symbols")
    r.add_argument("--date", type=date.fromisoformat)
    r.add_argument("--source-dir")
    r.add_argument("--no-review", action="store_true")
    pl = sub.add_parser("payload")
    pl.add_argument("--symbol", default="NIFTY")
    sy = sub.add_parser("synthetic")
    sy.add_argument("--out", required=True)
    sy.add_argument("--days", type=int, default=400)
    sy.add_argument("--random-walk", action="store_true")
    a = ap.parse_args()
    setup_logging(get_settings().log_level)
    if a.cmd == "synthetic":
        from .synthetic import generate

        days = generate(Path(a.out), days=a.days, predictable=not a.random_walk)
        print(f"wrote {len(days)} bhavcopy files to {a.out} ({days[0]} .. {days[-1]})")
        return 0
    return asyncio.run(_main(a))


if __name__ == "__main__":
    raise SystemExit(main())
