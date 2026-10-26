#!/bin/bash
# ValidateService: the instance only rejoins the ALB if the API can reach Postgres + Redis.
source /opt/omd/current/scripts/common.sh
for _ in $(seq 1 40); do
  if curl -fsS -o /dev/null http://127.0.0.1/api/readyz; then log "ready"; exit 0; fi
  sleep 3
done
log "not ready after 120s"
compose ps
compose logs --tail 80 api
exit 1
