terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Remote state: configure per environment at init time, e.g.
  #   terraform init -backend-config="bucket=<state-bucket>" \
  #                  -backend-config="key=sop-assistant/prod.tfstate" \
  #                  -backend-config="region=eu-west-1" \
  #                  -backend-config="dynamodb_table=<lock-table>" -backend-config="encrypt=true"
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}
