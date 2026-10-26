resource "random_password" "redis_auth" {
  length  = 40
  special = false
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.name}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${local.name}-redis"
  description          = "Cache for fitted vol smiles and marks"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.cache_node_type
  num_cache_clusters   = 1
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.main.arn
  transit_encryption_enabled = true # clients use rediss://
  auth_token                 = random_password.redis_auth.result
  automatic_failover_enabled = false
  snapshot_retention_limit   = 1
}
