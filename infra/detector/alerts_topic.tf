resource "aws_sns_topic" "critical" {
  name = "clickops-critical"
}

# The recipient confirms the subscription by clicking the link in the confirmation email.
resource "aws_sns_topic_subscription" "critical_email" {
  topic_arn = aws_sns_topic.critical.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
