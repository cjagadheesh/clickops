terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.81"
    }
  }
}

# Local state on purpose: this root creates the bucket that holds every other root's state.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "clickops"
      owner   = "agent"
    }
  }
}
