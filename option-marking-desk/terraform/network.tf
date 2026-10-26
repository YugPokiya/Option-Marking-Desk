module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets   = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, i)]      # ALB (+ app when no NAT)
  private_subnets  = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, 10 + i)] # app when NAT is on, Redis
  database_subnets = [for i in range(2) : cidrsubnet(var.vpc_cidr, 8, 20 + i)] # RDS, no internet route

  create_database_subnet_group = true
  enable_nat_gateway           = var.use_nat_gateway
  single_nat_gateway           = true
  enable_dns_hostnames         = true
  enable_dns_support           = true

  # the default SG of the VPC: deny everything (nothing should use it)
  manage_default_security_group  = true
  default_security_group_ingress = []
  default_security_group_egress  = []

  enable_flow_log                                 = true
  create_flow_log_cloudwatch_log_group            = true
  create_flow_log_cloudwatch_iam_role             = true
  flow_log_max_aggregation_interval               = 60
  flow_log_cloudwatch_log_group_retention_in_days = var.log_retention_days
  flow_log_cloudwatch_log_group_kms_key_id        = aws_kms_key.main.arn
}
