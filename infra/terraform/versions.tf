terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Remote state in the bucket created by ./bootstrap, with S3-native locking.
  # The bucket name is account-specific, so pass it at init time:
  #   terraform init -backend-config="bucket=roombook-tfstate-<account id>"
  backend "s3" {
    key          = "roombook/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.name
      ManagedBy = "terraform"
      Course    = "SWE40006"
    }
  }
}
