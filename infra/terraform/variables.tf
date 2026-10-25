variable "project" {
  type    = string
  default = "primark-sop"
}

variable "environment" {
  type        = string
  description = "staging | prod"
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod."
  }
}

variable "aws_region" {
  type    = string
  default = "eu-west-1" # Ireland - EU data residency
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "domain_name" {
  type        = string
  description = "Public hostname, e.g. storeassist.example.com"
}

variable "route53_zone_id" {
  type        = string
  description = "Hosted zone that contains domain_name"
}

variable "image_tag" {
  type        = string
  default     = "bootstrap"
  description = "Initial image tag only; CI/CD rolls out new task definition revisions."
}

variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "api_min_count" {
  type    = number
  default = 2
}

variable "api_max_count" {
  type    = number
  default = 10
}

variable "generation_model_id" {
  type    = string
  default = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "rewrite_model_id" {
  type    = string
  default = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
}


variable "mesh_api_key_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret containing the Mesh API key as SecretString."
}

variable "jwt_issuer" {
  type = string
}

variable "jwt_audience" {
  type = string
}

variable "jwks_url" {
  type = string
}

variable "alarm_email" {
  type = string
}

variable "chroma_cpu" {
  type        = number
  default     = 512
  description = "Fargate CPU units for the single Chroma server"
}

variable "chroma_memory" {
  type        = number
  default     = 1024
  description = "MiB of memory for the single Chroma server"
}

locals {
  name = "${var.project}-${var.environment}"
  tags = {
    Project     = "storeassist-sop-chatbot"
    Environment = var.environment
    ManagedBy   = "terraform"
    Repo        = "primark-sop-assistant"
  }
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
  is_prod    = var.environment == "prod"
}

variable "enable_sop_auto_ingestion" {
  type        = bool
  default     = false
  description = "Enable per-object S3 EventBridge ingestion tasks. Leave false for the initial bulk upload; enable after baseline ingestion is complete."
}
