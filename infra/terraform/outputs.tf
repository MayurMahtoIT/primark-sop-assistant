output "url" {
  value = "https://${var.domain_name}"
}
output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}
output "ecs_cluster" {
  value = aws_ecs_cluster.this.name
}
output "ecs_service" {
  value = aws_ecs_service.api.name
}
output "api_task_family" {
  value = aws_ecs_task_definition.api.family
}
output "ingest_task_family" {
  value = aws_ecs_task_definition.ingest.family
}
output "sop_bucket" {
  value = aws_s3_bucket.sops.bucket
}
output "chroma_private_endpoint" {
  value = "http://chroma.${aws_service_discovery_private_dns_namespace.chroma.name}:8000"
}
output "chroma_efs_id" {
  value = aws_efs_file_system.chroma.id
}
output "guardrail_id" {
  value = aws_bedrock_guardrail.sop.guardrail_id
}
