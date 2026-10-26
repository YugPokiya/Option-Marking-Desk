# Build from the repo root:  docker build -f deploy/docker/api.Dockerfile -t registry.digitalocean.com/omd/omd-api:0.1.0 .
# Assumes: app/main.py exposes `app`, requirements.txt, alembic.ini + alembic/ for migrations.
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd -g 10001 app && useradd -u 10001 -g app -s /sbin/nologin -M app
COPY --from=build /install /usr/local
WORKDIR /srv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
USER 10001
EXPOSE 8000
# workers from UVICORN_WORKERS; set FastAPI(root_path=os.getenv("API_ROOT_PATH", "")) in app/main.py
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2} --proxy-headers --forwarded-allow-ips='*'"]
