data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---- execution role (pull image, write logs) ----
resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_mesh_secret" {
  name = "${local.name}-read-mesh-api-key"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.mesh_api_key_secret_arn
    }]
  })
}

# ---- API task role (least privilege) ----
resource "aws_iam_role" "api_task" {
  name               = "${local.name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "api_task" {
  statement {
    sid     = "InvokeModels"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*",
    ]
  }
  statement {
    sid       = "ApplyGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.sop.guardrail_arn]
  }
  statement {
    sid       = "Sessions"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
}

resource "aws_iam_role_policy" "api_task" {
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

# ---- Ingestion task role ----
resource "aws_iam_role" "ingest_task" {
  name               = "${local.name}-ingest-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "ingest_task" {
  statement {
    sid       = "ReadSops"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.sops.arn, "${aws_s3_bucket.sops.arn}/*"]
  }
}

resource "aws_iam_role_policy" "ingest_task" {
  role   = aws_iam_role.ingest_task.id
  policy = data.aws_iam_policy_document.ingest_task.json
}

# ---- EventBridge -> run the ingestion task ----
data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events_run_task" {
  name               = "${local.name}-events-run-task"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

data "aws_iam_policy_document" "events_run_task" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.ingest.arn_without_revision, "${aws_ecs_task_definition.ingest.arn_without_revision}:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.ingest_task.arn]
  }
}

resource "aws_iam_role_policy" "events_run_task" {
  role   = aws_iam_role.events_run_task.id
  policy = data.aws_iam_policy_document.events_run_task.json
}
