#!/bin/bash
# AfterInstall: build /opt/omd/.env from SSM Parameter Store + the RDS secret, then pull images.
source /opt/omd/current/scripts/common.sh
# shellcheck source=/dev/null
source "$APP_DIR/release.env"            # ECR_REGISTRY, IMAGE_TAG, AWS_REGION, PARAM_PATH, LOG_GROUP
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"

log "reading config from $PARAM_PATH"
umask 077
tmp=$(mktemp)
aws ssm get-parameters-by-path --path "$PARAM_PATH" --with-decryption \
  --query 'Parameters[*].[Name,Value]' --output text |
  while IFS=$'\t' read -r name value; do printf '%s=%s\n' "${name##*/}" "$value"; done > "$tmp"

get() { grep -E "^$1=" "$tmp" | head -1 | cut -d= -f2-; }
DB_SECRET_ARN=$(get DB_SECRET_ARN)
secret=$(aws secretsmanager get-secret-value --secret-id "$DB_SECRET_ARN" --query SecretString --output text)
DATABASE_URL=$(DB_SECRET="$secret" DB_HOST=$(get DB_HOST) DB_PORT=$(get DB_PORT) DB_NAME=$(get DB_NAME) python3 -c '
import json, os, urllib.parse as u
s = json.loads(os.environ["DB_SECRET"])
print("postgresql+asyncpg://%s:%s@%s:%s/%s?ssl=require" % (
    u.quote(s["username"], safe=""), u.quote(s["password"], safe=""),
    os.environ["DB_HOST"], os.environ["DB_PORT"], os.environ["DB_NAME"]))')

{
  grep -vE '^(DB_SECRET_ARN)=' "$tmp"
  echo "DATABASE_URL=$DATABASE_URL"
  echo "ECR_REGISTRY=$ECR_REGISTRY"
  echo "IMAGE_TAG=$IMAGE_TAG"
  echo "AWS_REGION=$AWS_REGION"
  echo "LOG_GROUP=$LOG_GROUP"
} > "$ENV_FILE"
rm -f "$tmp"
chmod 600 "$ENV_FILE"

log "pulling $IMAGE_TAG"
aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
compose pull --quiet
