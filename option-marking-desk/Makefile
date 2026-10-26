.DEFAULT_GOAL := help
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup:  ## create venv + install Python and web deps
	$(PY) -m venv $(VENV) && $(BIN)/pip install -r requirements.txt -r requirements-dev.txt
	cd web && npm ci

services:  ## start Postgres + Redis in Docker
	docker compose up -d db redis

migrate:  ## apply DB migrations
	$(BIN)/alembic upgrade head

api:  ## run the API with reload on :8000
	$(BIN)/uvicorn app.main:app --reload --port 8000

web:  ## run the dashboard on :5173 (proxies /api to :8000)
	cd web && npm run dev

lint:  ## ruff + typecheck
	$(BIN)/ruff check app tests && $(BIN)/ruff format --check app tests
	cd web && npm run typecheck

test:  ## unit tests (no services needed)
	$(BIN)/pytest tests/unit --cov=app
	cd web && npm test

test-integration:  ## integration tests (needs `make services` + `make migrate`)
	$(BIN)/pytest -m integration tests/integration

up:  ## full stack in Docker on http://localhost:8080
	docker compose up --build
