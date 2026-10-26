terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.28" # the VPC module v6 needs >= 6.28
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state (recommended). Create the bucket once, then uncomment and `terraform init -migrate-state`.
  # backend "s3" {
  #   bucket       = "omd-tfstate-<account-id>"
  #   key          = "omd/prod/terraform.tfstate"
  #   region       = "ap-south-1"
  #   encrypt      = true
  #   use_lockfile = true   # S3-native locking, no DynamoDB table needed
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
