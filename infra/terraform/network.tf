module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.16"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway     = true
  single_nat_gateway     = !local.is_prod # one NAT per AZ in prod
  one_nat_gateway_per_az = local.is_prod

  enable_dns_hostnames = true
  enable_dns_support   = true

  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role  = true
  flow_log_max_aggregation_interval    = 60
}

# ---------- security groups ----------
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  vpc_id      = module.vpc.vpc_id
  description = "Public ALB"

  ingress {
    description = "HTTPS from the internet (WAF-protected)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTP for redirect only"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description     = "To app tasks"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "app" {
  name_prefix = "${local.name}-app-"
  vpc_id      = module.vpc.vpc_id
  description = "ECS API and ingestion tasks"

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS to AWS APIs and the configured JWKS endpoint"
}

resource "aws_security_group_rule" "app_from_alb" {
  type                     = "ingress"
  description              = "ALB to API"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "app_to_chroma" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.chroma.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  description                  = "API and ingestion tasks to private Chroma service"
}

resource "aws_security_group" "endpoints" {
  name_prefix = "${local.name}-vpce-"
  vpc_id      = module.vpc.vpc_id
  description = "Interface VPC endpoints"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  lifecycle { create_before_destroy = true }
}

# ---------- VPC endpoints: keep Bedrock / ECR / logs traffic on the AWS network ----------
locals {
  interface_endpoints = ["bedrock-runtime", "ecr.api", "ecr.dkr", "logs"]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(local.interface_endpoints)
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = module.vpc.private_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}
