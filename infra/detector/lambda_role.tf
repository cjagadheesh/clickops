locals {
  function_name = "clickops-detector"
  role_name     = "clickops-detector"
  role_arn      = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.role_name}"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "detector" {
  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

# Grown in later steps (state read, describe calls, SSM, SNS).
data "aws_iam_policy_document" "detector" {
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.detector.arn}:*"]
  }

  statement {
    sid       = "StoreEvents"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.events.arn]
  }

  # Needed for the function's dead-letter queue (failed asynchronous invocations).
  statement {
    sid       = "DeadLetter"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "detector" {
  name   = "clickops-detector"
  role   = aws_iam_role.detector.id
  policy = data.aws_iam_policy_document.detector.json
}
