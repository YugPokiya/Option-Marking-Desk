variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
  default     = "omd"
}

variable "environment" {
  description = "Environment name (prod, staging, ...)."
  type        = string
  default     = "prod"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "use_nat_gateway" {
  description = <<-EOT
    false (default, cheapest): app instances sit in public subnets with a public IP, but their
    security group only accepts traffic from the load balancer and there is no SSH (use SSM).
    true: instances in private subnets behind one NAT gateway (roughly +USD 35/month plus data).
  EOT
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "EC2 instance type for the app servers."
  type        = string
  default     = "t3.micro"
}

variable "asg_min_size" {
  description = "Minimum number of app instances."
  type        = number
  default     = 2
}

variable "asg_desired_capacity" {
  description = "Desired number of app instances at creation (later managed by autoscaling)."
  type        = number
  default     = 2
}

variable "asg_max_size" {
  description = "Maximum number of app instances."
  type        = number
  default     = 4
}

variable "asg_health_check_type" {
  description = <<-EOT
    "EC2" until the first CodeDeploy deployment has succeeded (new instances have no app yet, so
    ELB checks would make the ASG replace them in a loop). Switch to "ELB" afterwards.
  EOT
  type        = string
  default     = "EC2"

  validation {
    condition     = contains(["EC2", "ELB"], var.asg_health_check_type)
    error_message = "asg_health_check_type must be EC2 or ELB."
  }
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "db_multi_az" {
  description = "Run RDS Multi-AZ (doubles the DB cost)."
  type        = bool
  default     = false
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS. Empty = HTTP only (fine for a first test, not for real use)."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Protect the ALB and RDS from deletion; RDS takes a final snapshot on destroy."
  type        = bool
  default     = true
}

variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications (empty = no subscription)."
  type        = string
  default     = ""
}

variable "github_repo" {
  description = "owner/repo allowed to deploy through GitHub Actions OIDC (empty = no CI role)."
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one (e.g. from deploy/aws/github-oidc.sh)."
  type        = bool
  default     = true
}

variable "create_ecr_repositories" {
  description = "Create the omd-api / omd-web ECR repositories. Set false if they already exist."
  type        = bool
  default     = true
}

variable "compose_version" {
  description = "Docker Compose plugin version installed on the instances."
  type        = string
  default     = "v5.6.1"
}

variable "bedrock_model_id" {
  description = <<-EOT
    Claude model / inference profile for the daily forecast review. Default: the India-only
    cross-region profile (requests stay in ap-south-1/ap-south-2). For Sonnet 5.5 from Mumbai use
    "global.anthropic.claude-sonnet-5-5" (global routing). Enable model access in the Bedrock console first.
  EOT
  type        = string
  default     = "in.anthropic.claude-sonnet-5"
}

variable "forecast_symbols" {
  description = "Underlyings for the daily IV forecast."
  type        = string
  default     = "NIFTY,BANKNIFTY"
}

variable "log_retention_days" {
  description = "CloudWatch log retention for app and VPC flow logs."
  type        = number
  default     = 30
}
