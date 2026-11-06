locals {
  account_id      = data.aws_caller_identity.current.account_id
  default_bus_arn = "arn:aws:events:${var.region}:${local.account_id}:event-bus/default"
}

# --- ap-south-1: ec2, s3 and lambda events ---------------------------------------------------

resource "aws_cloudwatch_event_rule" "regional" {
  name           = "clickops-regional"
  description    = "Watched write calls from ec2, s3 and lambda"
  event_pattern  = file("${path.module}/patterns/regional.json")
  event_bus_name = "default"
}

resource "aws_cloudwatch_event_target" "regional" {
  rule = aws_cloudwatch_event_rule.regional.name
  arn  = aws_lambda_function.detector.arn

  dead_letter_config {
    arn = aws_sqs_queue.dlq.arn
  }

  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 3600
  }
}

resource "aws_lambda_permission" "regional" {
  statement_id  = "AllowEventBridgeRegional"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.regional.arn
}

# --- ap-south-1: iam and route53 events forwarded from us-east-1 -------------------------------

resource "aws_cloudwatch_event_rule" "global" {
  name           = "clickops-global"
  description    = "IAM and Route 53 write calls forwarded from us-east-1"
  event_pattern  = file("${path.module}/patterns/global.json")
  event_bus_name = "default"
}

resource "aws_cloudwatch_event_target" "global" {
  rule = aws_cloudwatch_event_rule.global.name
  arn  = aws_lambda_function.detector.arn

  dead_letter_config {
    arn = aws_sqs_queue.dlq.arn
  }

  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 3600
  }
}

resource "aws_lambda_permission" "global" {
  statement_id  = "AllowEventBridgeGlobal"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.global.arn
}

# EventBridge needs permission to put failed deliveries on the DLQ.
data "aws_iam_policy_document" "dlq" {
  statement {
    sid       = "AllowEventBridgeDeadLetters"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_event_rule.regional.arn,
        aws_cloudwatch_event_rule.global.arn,
      ]
    }
  }
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy    = data.aws_iam_policy_document.dlq.json
}

# --- us-east-1: forward iam and route53 events to the ap-south-1 default bus -------------------

data "aws_iam_policy_document" "forwarder_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "forwarder" {
  name               = "clickops-event-forwarder"
  assume_role_policy = data.aws_iam_policy_document.forwarder_trust.json
}

data "aws_iam_policy_document" "forwarder" {
  statement {
    sid       = "PutEventsToMumbaiBus"
    actions   = ["events:PutEvents"]
    resources = [local.default_bus_arn]
  }
}

resource "aws_iam_role_policy" "forwarder" {
  name   = "put-events"
  role   = aws_iam_role.forwarder.id
  policy = data.aws_iam_policy_document.forwarder.json
}

resource "aws_cloudwatch_event_rule" "forward" {
  provider       = aws.use1
  name           = "clickops-forward-global"
  description    = "Forward IAM and Route 53 write calls to the ${var.region} default bus"
  event_pattern  = file("${path.module}/patterns/global.json")
  event_bus_name = "default"
}

resource "aws_cloudwatch_event_target" "forward" {
  provider = aws.use1
  rule     = aws_cloudwatch_event_rule.forward.name
  arn      = local.default_bus_arn
  role_arn = aws_iam_role.forwarder.arn
}
