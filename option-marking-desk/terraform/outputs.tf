output "app_url" {
  description = "Load balancer URL (point your domain's alias record here)."
  value       = "${var.certificate_arn == "" ? "http" : "https"}://${aws_lb.app.dns_name}"
}

output "ecr_registry" {
  description = "Value for the ECR_REGISTRY GitHub variable."
  value       = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
}

output "codedeploy_bucket" {
  description = "Value for the CODEDEPLOY_BUCKET GitHub variable."
  value       = aws_s3_bucket.artifacts.bucket
}

output "codedeploy_app" {
  description = "Value for the CODEDEPLOY_APP GitHub variable."
  value       = aws_codedeploy_app.app.name
}

output "codedeploy_group" {
  description = "Value for the CODEDEPLOY_GROUP GitHub variable."
  value       = aws_codedeploy_deployment_group.app.deployment_group_name
}

output "github_role_arn" {
  description = "Value for the AWS_ROLE_ARN GitHub variable."
  value       = var.github_repo == "" ? null : aws_iam_role.github[0].arn
}

output "param_path" {
  description = "SSM path holding runtime config."
  value       = local.param_path
}

output "log_group" {
  description = "CloudWatch log group for container logs."
  value       = aws_cloudwatch_log_group.app.name
}

output "db_endpoint" {
  description = "RDS endpoint (private)."
  value       = aws_db_instance.postgres.address
}

output "db_secret_arn" {
  description = "Secrets Manager secret holding the DB master credentials."
  value       = aws_db_instance.postgres.master_user_secret[0].secret_arn
}
