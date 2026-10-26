resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name}-pg17"
  family = "postgres17"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # log queries slower than 1s
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name}-pg"
  engine         = "postgres"
  engine_version = "17"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name                     = "omd"
  username                    = "omd_admin"
  manage_master_user_password = true # password lives in Secrets Manager, rotated by RDS

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period         = 7
  backup_window                   = "20:00-21:00" # 01:30-02:30 IST
  maintenance_window              = "sun:21:30-sun:22:30"
  auto_minor_version_upgrade      = true
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = "${local.name}-pg-final"
}
