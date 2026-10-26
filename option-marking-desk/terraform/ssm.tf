# Runtime config read by deploy/codedeploy/scripts/configure.sh on every deployment.
# All SecureString with the project key (the script reads with --with-decryption).
locals {
  app_params = {
    APP_ENV         = var.environment
    LOG_LEVEL       = "info"
    API_ROOT_PATH   = "/api"
    UVICORN_WORKERS = "1" # 1 GiB RAM per instance
    DB_HOST         = aws_db_instance.postgres.address
    DB_PORT         = tostring(aws_db_instance.postgres.port)
    DB_NAME         = aws_db_instance.postgres.db_name
    DB_SECRET_ARN   = aws_db_instance.postgres.master_user_secret[0].secret_arn
    # daily IV forecast + Claude review
    FORECAST_SYMBOLS = var.forecast_symbols
    BEDROCK_REGION   = var.region
    BEDROCK_MODEL_ID = var.bedrock_model_id
    REVIEW_REQUIRED  = "true"
  }
}

resource "aws_ssm_parameter" "app" {
  for_each = local.app_params

  name   = "${local.param_path}/${each.key}"
  type   = "SecureString"
  key_id = aws_kms_key.main.arn
  value  = each.value
}

resource "aws_ssm_parameter" "redis_url" {
  name   = "${local.param_path}/REDIS_URL"
  type   = "SecureString"
  key_id = aws_kms_key.main.arn
  value  = "rediss://:${random_password.redis_auth.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
}
