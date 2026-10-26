# Option Marking Desk

Marks **illiquid options** from a fitted, arbitrage-checked **volatility smile**.

When a strike barely trades, its last price and its quotes are stale or wide, so neither is a fair value. This service sorts each quote into liquid or illiquid and fits an SVI smile to the liquid out-of-the-money quotes. Each illiquid strike is then priced off that curve, with an uncertainty band, and every run is kept as an audit trail.

![Dashboard (dark)](docs/screenshots/dashboard-dark.png)

| | |
|---|---|
| ![Smile tooltip](docs/screenshots/smile-tooltip.png) | ![Dashboard (light)](docs/screenshots/dashboard-light.png) |

## What it does

1. **Forward and discounting:** the forward comes from put-call parity on the most at-the-money liquid pairs. If there are none, it falls back to spot carry.
2. **Liquidity classification:** each quote is flagged `no_bid`, `no_ask`, `crossed`, `wide_spread`, `low_volume` or `stale`. All thresholds can be set per run.
3. **Smile fit:** raw SVI by weighted least squares (weights = 1 / bid-ask spread in vol), with a penalty that keeps Gatheral's butterfly condition g(k) ≥ 0 over and beyond the data. With fewer than 5 quotes it falls back to a quadratic (3–4) or a flat vol (1–2).
4. **Marks:**
   - Liquid strikes are marked at mid.
   - Illiquid strikes get the model price, kept inside [bid, ask] when those exist and never below intrinsic.
   - Every mark carries a band that widens outside the fitted range.
5. **Audit:** each run stores its parameters, config, fit error and all marks.
6. **Next-session IV forecast:** a daily job turns the free NSE bhavcopy into a 30-day smile and forecasts tomorrow's with ML (only when a model beats "no change" out of sample). Rule checks and **Claude on Amazon Bedrock** review the data and forecast before publishing. See [`docs/forecasting.md`](docs/forecasting.md).

On the synthetic NIFTY chain, the fit recovers the true smile to within **0.11 vol points** on every strike (median 0.008). See [`docs/methodology.md`](docs/methodology.md).

## Stack

| Layer | Tech |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 |
| Quant | NumPy, SciPy (Brent IV solver, `least_squares` SVI fit) |
| Forecast | pandas, scikit-learn (ridge, gradient boosting, walk-forward backtest), Claude via Amazon Bedrock (boto3 Converse) |
| Data | PostgreSQL 17 (chains, quotes, fits, marks), Redis (latest-run cache) |
| Web | React 19, TypeScript, Vite; hand-built SVG chart with crosshair tooltip; light and dark themes |
| Ops | Prometheus metrics, JSON logs, `/healthz` + `/readyz` (checks Postgres and Redis) |
| CI/CD | GitHub Actions: ruff, pytest (unit + integration on real Postgres/Redis), Vitest, SonarQube quality gate, Trivy, ECR, then deploy |
| Deploy | **EC2 t3.micro + CodeDeploy** via Terraform (default), or **EKS + Istio** via Kustomize |

## Quick start

**Everything in Docker** (http://localhost:8080):

```bash
docker compose up --build
```

**Local development:**

```bash
make setup         # venv + npm ci
make services      # Postgres + Redis in Docker
cp .env.example .env
make migrate
make api           # http://localhost:8000/docs
make web           # http://localhost:5173
```

Then click **New demo chain** and **Fit & mark**, or upload [`samples/nifty_chain_sample.csv`](samples/).

## API

Behind the gateway every route is under `/api` (the prefix is stripped); locally they are at the root.

| Method | Path | |
|---|---|---|
| `POST` | `/chains` | create a chain from JSON |
| `POST` | `/chains/upload` | create from CSV (`strike,option_type,bid,ask[,last,volume,open_interest,quote_time]`) |
| `POST` | `/chains/demo` | synthetic NIFTY chain (`ENABLE_DEMO=true`) |
| `GET` | `/chains`, `/chains/{id}` | list, or one chain with its quotes |
| `POST` | `/chains/{id}/mark` | fit and mark; body sets the liquidity rules (all optional) |
| `GET` | `/chains/{id}/marks?fit_id=` | latest run (served from Redis) or a given one |
| `GET` | `/chains/{id}/fits` | run history |
| `GET` | `/chains/{id}/smile` | fitted curve + market IVs for charting |
| `POST` | `/price` | Black-76 price, delta and vega for one option |
| `GET` | `/forecasts/latest?symbol=NIFTY` | latest next-session IV forecast, model skill, and the rule + Claude review |
| `GET` | `/forecasts?symbol=NIFTY` | forecast history |
| `GET` | `/healthz`, `/readyz`, `/metrics` | ops |

Interactive docs are at `/docs`.

## Configuration

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://omd:omd@localhost:5432/omd` | |
| `REDIS_URL` | `redis://localhost:6379/0` | `rediss://` for TLS (ElastiCache) |
| `API_ROOT_PATH` | `""` | `/api` behind Istio or nginx, so the docs links work |
| `APP_ENV`, `LOG_LEVEL` | `dev`, `info` | |
| `ENABLE_DEMO` | `true` | turn off in production if you don't want demo data |
| `CACHE_TTL_SECONDS` | `3600` | |
| `FORECAST_SYMBOLS` | `NIFTY,BANKNIFTY` | daily forecast job |
| `BEDROCK_REGION`, `BEDROCK_MODEL_ID` | `ap-south-1`, `in.anthropic.claude-sonnet-5` | Claude review (India-only inference profile) |
| `REVIEW_ENABLED`, `REVIEW_REQUIRED` | `true`, `true` | when required, a failed or missing review blocks publication |

## Repository layout

```
app/            FastAPI service
  quant/        pricing, IV, SVI, marking (pure NumPy, no I/O)
  forecast/     bhavcopy ingest, daily surfaces, features, models, checks, Claude review, CLI
  api/          routes
alembic/        migrations
tests/          unit (no services) + integration (Postgres + Redis)
web/            React dashboard
samples/        example CSV
deploy/         Dockerfiles, Kubernetes + Istio, EKS scripts, CodeDeploy bundle
terraform/      EC2 t3.micro + CodeDeploy infrastructure
docs/           methodology, CI/CD, screenshots
```

## Deploying

- **AWS EC2 (cheapest):** [`terraform/README.md`](terraform/README.md). Run `terraform apply`, set 5 GitHub variables, then push to `main`.
- **Kubernetes + Istio (EKS):** [`deploy/README.md`](deploy/README.md).
- **Pipeline details:** [`docs/ci-cd.md`](docs/ci-cd.md).

## Limitations

- **One expiry at a time:** calendar arbitrage across expiries isn't checked yet.
- **European exercise only:** marking uses Black-76 on the forward, which fits NSE index options but not American single-stock options.
- **IV forecast:** tested on synthetic markets only so far, so real skill is unknown until you backfill real data. It's research output, not trading advice.
- **No authentication:** the API has no auth, so put it behind your gateway's auth before exposing it.

## License

[MIT](LICENSE)
