data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  param_path = "/${var.project}/${var.environment}"

  # where the app instances run (see var.use_nat_gateway)
  app_subnet_ids = var.use_nat_gateway ? module.vpc.private_subnets : module.vpc.public_subnets

  ecr_repo_names = ["${var.project}-api", "${var.project}-web"]

  # "in.anthropic.claude-sonnet-5" -> "anthropic.claude-sonnet-5" (cross-region profiles route to the
  # foundation model in several regions, so both ARNs must be allowed)
  bedrock_fm    = replace(var.bedrock_model_id, "/^(in|global|us|eu|apac|au)\\./", "")
  ecr_repo_arns = [for n in local.ecr_repo_names : "arn:aws:ecr:${var.region}:${local.account_id}:repository/${n}"]

  tags = {
    Project     = "option-marking-desk"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
