resource "aws_dynamodb_table" "events" {
  name         = "clickops-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "resource_key"
  range_key    = "sk"

  attribute {
    name = "resource_key"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "day"
    type = "S"
  }

  attribute {
    name = "ts"
    type = "S"
  }

  global_secondary_index {
    name            = "day-ts"
    hash_key        = "day"
    range_key       = "ts"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
