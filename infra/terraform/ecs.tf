resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = local.is_prod ? 90 : 30
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/ecs/${local.name}/ingest"
  retention_in_days = local.is_prod ? 90 : 30
}

locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  shared_env = [
    { name = "ENV", value = var.environment },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "CHROMA_MODE", value = "http" },
    { name = "CHROMA_HOST", value = "chroma.${aws_service_discovery_private_dns_namespace.chroma.name}" },
    { name = "CHROMA_PORT", value = "8000" },
    { name = "CHROMA_SSL", value = "false" },
    { name = "CHROMA_COLLECTION", value = "primark-sop-chunks-v2" },
    { name = "CHROMA_PERSIST_DIR", value = "/data/chroma" },
    { name = "EMBEDDING_MODEL_NAME", value = "text-embedding-3-small" },
    { name = "EMBEDDING_DIMENSIONS", value = "1536" },
    { name = "SOP_BUCKET", value = aws_s3_bucket.sops.bucket },
  ]

  api_env = concat(local.shared_env, [
    { name = "MESH_BASE_URL", value = "https://api.meshapi.ai/v1" },
    { name = "GENERATION_MODEL_ID", value = "openai/gpt-oss-20b" },
    { name = "REWRITE_MODEL_ID", value = "openai/gpt-oss-20b" },
    { name = "GUARDRAIL_ID", value = aws_bedrock_guardrail.sop.guardrail_id },
    { name = "GUARDRAIL_VERSION", value = aws_bedrock_guardrail_version.sop.version },
    { name = "SESSIONS_TABLE", value = aws_dynamodb_table.sessions.name },
    { name = "JWT_ISSUER", value = var.jwt_issuer },
    { name = "JWT_AUDIENCE", value = var.jwt_audience },
    { name = "JWKS_URL", value = var.jwks_url },
  ])
}

# ---------------------------- API ----------------------------
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name                   = "api"
    image                  = local.image
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
    environment            = local.api_env
    secrets                = [{ name = "MESH_API_KEY", valueFrom = var.mesh_api_key_secret_arn }]
    stopTimeout            = 30
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status==200 else 1)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_min_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8080
  }

  # CI/CD owns the running task-definition revision; autoscaling owns the count.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.https, aws_ecs_service.chroma]
}

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.api.name}"
  min_capacity       = var.api_min_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  resource_id        = aws_appautoscaling_target.api.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "requests" {
  name               = "${local.name}-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  resource_id        = aws_appautoscaling_target.api.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 150 # requests per task per minute (LLM calls are slow; scale early)
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.this.arn_suffix}/${aws_lb_target_group.api.arn_suffix}"
    }
  }
}

# ------------------------ Ingestion (one-shot task) ------------------------
resource "aws_ecs_task_definition" "ingest" {
  family                   = "${local.name}-ingest"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 4096
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.ingest_task.arn

  container_definitions = jsonencode([{
    name                   = "ingest"
    image                  = local.image
    essential              = true
    readonlyRootFilesystem = true
    command                = ["python", "-m", "app.ingestion", "--prefix", "sops/Primark/"]
    environment            = local.shared_env
    secrets                = [{ name = "MESH_API_KEY", valueFrom = var.mesh_api_key_secret_arn }]
    # The shared image contains an API /healthz check; this one-shot job is not a web server.
    healthCheck = {
      command     = ["CMD-SHELL", "exit 0"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 5
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ingest.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ingest"
      }
    }
  }])
}

locals {
  s3_triggers = {
    upsert = { detail_type = "Object Created", flag = "--s3-key" }
    delete = { detail_type = "Object Deleted", flag = "--delete-key" }
  }
}

# Optional per-object automation: enable only after the initial S3 bulk ingestion succeeds.
resource "aws_cloudwatch_event_rule" "sop_change" {
  for_each = var.enable_sop_auto_ingestion ? local.s3_triggers : {}
  name     = "${local.name}-sop-${each.key}"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = [each.value.detail_type]
    detail = {
      bucket = { name = [aws_s3_bucket.sops.bucket] }
      object = { key = [{ prefix = "sops/Primark/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "run_ingest" {
  for_each = var.enable_sop_auto_ingestion ? local.s3_triggers : {}
  rule     = aws_cloudwatch_event_rule.sop_change[each.key].name
  arn      = aws_ecs_cluster.this.arn
  role_arn = aws_iam_role.events_run_task.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.ingest.arn_without_revision # always the latest revision
    launch_type         = "FARGATE"
    task_count          = 1
    network_configuration {
      subnets          = module.vpc.private_subnets
      security_groups  = [aws_security_group.app.id]
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths = { key = "$.detail.object.key" }
    input_template = "{\"containerOverrides\":[{\"name\":\"ingest\",\"command\":[\"python\",\"-m\",\"app.ingestion\",\"${each.value.flag}\",\"<key>\"]}]}"
  }
}
