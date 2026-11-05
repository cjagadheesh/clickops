resource "aws_sqs_queue" "dlq" {
  name                      = "clickops-detector-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
