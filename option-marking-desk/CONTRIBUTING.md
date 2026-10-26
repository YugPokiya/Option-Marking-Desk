# Contributing

```bash
make setup          # venv + npm ci
make services       # Postgres + Redis (Docker)
make migrate
make api            # :8000
make web            # :5173
```

Before opening a PR, run `make lint test test-integration`.

- **Quant changes** (`app/quant/`) need a unit test showing the numbers, e.g. that a fit recovers known parameters.
- **Schema changes** need an Alembic migration: `alembic revision --autogenerate -m "..."`. CI runs `alembic check` to catch drift.
- **Commits:** keep them small and say *why* in the message.
