#!/bin/bash
# Shared by the hook scripts.
set -euo pipefail
APP_DIR=/opt/omd/current
ENV_FILE=/opt/omd/.env
compose() { docker compose -f "$APP_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }
log() { echo "[omd $(date -u +%H:%M:%S)] $*"; }
