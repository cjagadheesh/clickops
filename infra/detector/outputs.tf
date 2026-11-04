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
