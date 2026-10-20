# Host checks that do not depend on the Production host itself (Prometheus on
# that host cannot report its own outage). An optional email subscription
# receives the alarms; AWS sends a confirmation link first.

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-host-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Missing data means the instance is stopped (for example, a Learner Lab
# session ended), not failing, so it does not raise the alarm.
resource "aws_cloudwatch_metric_alarm" "status_check" {
  for_each = aws_instance.host

  alarm_name          = "${var.name}-${each.key}-status-check"
  alarm_description   = "EC2 system or instance status check failing on the ${each.key} host"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = each.value.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "production_cpu" {
  alarm_name          = "${var.name}-production-cpu-high"
  alarm_description   = "Production CPU above 70 percent for 10 minutes (brief target: under 70)"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  dimensions          = { InstanceId = aws_instance.host["production"].id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 70
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
