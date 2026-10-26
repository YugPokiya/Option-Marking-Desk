#!/bin/bash
# ApplicationStop: stop the running release. The instance is already out of the ALB.
source /opt/omd/current/scripts/common.sh 2>/dev/null || exit 0   # first deploy: nothing to stop
if [ -f "$ENV_FILE" ] && docker compose ls -q | grep -qx omd; then
  log "stopping current release"
  compose down --timeout 30
fi
