#!/bin/bash
# ApplicationStart: run migrations (idempotent; OneAtATime means one instance at a time), then start.
source /opt/omd/current/scripts/common.sh
log "migrating"
compose run --rm --no-deps api alembic upgrade head
log "starting"
compose up -d --remove-orphans --wait --wait-timeout 120
docker image prune -af --filter "until=72h" >/dev/null || true   # 20 GB disk: drop old releases

log "installing the daily forecast timer"
install -m 0644 "$APP_DIR/omd-forecast.service" "$APP_DIR/omd-forecast.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now omd-forecast.timer
