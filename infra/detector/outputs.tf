output "events_table" {
  value = aws_dynamodb_table.events.name
}

output "events_table_arn" {
  value = aws_dynamodb_table.events.arn
}

output "critical_topic_arn" {
  value = aws_sns_topic.critical.arn
}

output "trail_bucket" {
  value = aws_s3_bucket.trail.bucket
}

output "detector_function" {
  value = aws_lambda_function.detector.function_name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "event_rules" {
  value = {
    regional = aws_cloudwatch_event_rule.regional.name
    global   = aws_cloudwatch_event_rule.global.name
    forward  = aws_cloudwatch_event_rule.forward.name
  }
}
