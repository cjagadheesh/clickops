terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.81"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Bucket and region come from backend.hcl (gitignored): terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "sandbox/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "clickops"
      owner   = "agent"
    }
  }
}

data "aws_caller_identity" "current" {}
