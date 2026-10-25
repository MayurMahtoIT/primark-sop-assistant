resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "latency_p95" {
  alarm_name          = "${local.name}-latency-p95"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = 20
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix }
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${local.name}-unhealthy-hosts"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { LoadBalancer = aws_lb.this.arn_suffix, TargetGroup = aws_lb_target_group.api.arn_suffix }
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "chroma_running_tasks" {
  alarm_name          = "${local.name}-chroma-running-tasks"
  namespace           = "ECS/ContainerInsights"
  metric_name         = "RunningTaskCount"
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = aws_ecs_service.chroma.name
  }
  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

# Guardrail trips / fail-closed events surfaced from structured logs.
resource "aws_cloudwatch_log_metric_filter" "guardrail_unavailable" {
  name           = "${local.name}-guardrail-unavailable"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.msg = \"guardrail_unavailable\" }"
  metric_transformation {
    name      = "GuardrailUnavailable"
    namespace = "StoreAssist/${var.environment}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "guardrail_unavailable" {
  alarm_name          = "${local.name}-guardrail-unavailable"
  namespace           = "StoreAssist/${var.environment}"
  metric_name         = "GuardrailUnavailable"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}
