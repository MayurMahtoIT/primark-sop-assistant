# ---------------- ECR ----------------
resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = !local.is_prod

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 30 }
      action       = { type = "expire" }
    }]
  })
}

# ---------------- S3: the 100 SOP documents ----------------
resource "aws_s3_bucket" "sops" {
  bucket        = "${local.name}-documents-${local.account_id}"
  force_destroy = !local.is_prod
}

resource "aws_s3_bucket_versioning" "sops" {
  bucket = aws_s3_bucket.sops.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sops" {
  bucket = aws_s3_bucket.sops.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "sops" {
  bucket                  = aws_s3_bucket.sops.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "sops" {
  bucket = aws_s3_bucket.sops.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 365 } # keep a year of SOP history for audit
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket_policy" "sops_tls_only" {
  bucket = aws_s3_bucket.sops.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.sops.arn, "${aws_s3_bucket.sops.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# Upload / delete in S3 -> EventBridge -> ECS ingestion task (see ecs.tf)
resource "aws_s3_bucket_notification" "sops" {
  bucket      = aws_s3_bucket.sops.id
  eventbridge = true
}

# ---------------- DynamoDB: sessions + feedback ----------------
resource "aws_dynamodb_table" "sessions" {
  name         = "${local.name}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  deletion_protection_enabled = local.is_prod
}
