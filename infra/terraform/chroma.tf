# Private Chroma server for vector storage. EFS provides persistence across ECS task replacements.
resource "aws_security_group" "chroma" {
  name_prefix = "${local.name}-chroma-"
  vpc_id      = module.vpc.vpc_id
  description = "Private Chroma vector database"

  ingress {
    description     = "Chroma HTTP from API and ingestion tasks"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "chroma_https" {
  security_group_id = aws_security_group.chroma.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS for Docker Hub image pull and AWS logging endpoints"
}

resource "aws_security_group" "chroma_efs" {
  name_prefix = "${local.name}-chroma-efs-"
  vpc_id      = module.vpc.vpc_id
  description = "EFS storage for private Chroma service"

  ingress {
    description     = "NFS only from Chroma task"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.chroma.id]
  }

  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_security_group_egress_rule" "chroma_to_efs" {
  security_group_id            = aws_security_group.chroma.id
  referenced_security_group_id = aws_security_group.chroma_efs.id
  ip_protocol                  = "tcp"
  from_port                    = 2049
  to_port                      = 2049
  description                  = "Chroma task to encrypted EFS storage"
}

resource "aws_efs_file_system" "chroma" {
  encrypted       = true
  throughput_mode = "bursting"

  tags = { Name = "${local.name}-chroma-data" }
}

resource "aws_efs_access_point" "chroma" {
  file_system_id = aws_efs_file_system.chroma.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/chroma-data"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
}

resource "aws_efs_mount_target" "chroma" {
  for_each        = toset(module.vpc.private_subnets)
  file_system_id  = aws_efs_file_system.chroma.id
  subnet_id       = each.value
  security_groups = [aws_security_group.chroma_efs.id]
}

resource "aws_service_discovery_private_dns_namespace" "chroma" {
  name        = "${local.name}.internal"
  description = "Private namespace for SOP assistant services"
  vpc         = module.vpc.vpc_id
}

resource "aws_service_discovery_service" "chroma" {
  name = "chroma"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.chroma.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config { failure_threshold = 1 }
}

resource "aws_cloudwatch_log_group" "chroma" {
  name              = "/ecs/${local.name}/chroma"
  retention_in_days = local.is_prod ? 90 : 30
}

resource "aws_iam_role" "chroma_task" {
  name               = "${local.name}-chroma-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_ecs_task_definition" "chroma" {
  family                   = "${local.name}-chroma"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.chroma_cpu
  memory                   = var.chroma_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.chroma_task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "chroma-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.chroma.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.chroma.id
        iam             = "DISABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name                   = "chroma"
    image                  = "chromadb/chroma:1.5.9"
    essential              = true
    readonlyRootFilesystem = false
    portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
    mountPoints            = [{ sourceVolume = "chroma-data", containerPath = "/data", readOnly = false }]
  
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.chroma.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "chroma"
      }
    }
  }])
}

resource "aws_ecs_service" "chroma" {
  name            = "chroma"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.chroma.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  enable_execute_command             = false

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.chroma.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.chroma.arn
    container_name = "chroma"
    container_port = 8000
  }

  lifecycle { ignore_changes = [task_definition] }

  depends_on = [aws_efs_mount_target.chroma, aws_iam_role_policy_attachment.execution]
}
