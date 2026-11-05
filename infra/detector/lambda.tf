resource "aws_cloudwatch_log_group" "detector" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "detector" {
  function_name    = local.function_name
  role             = aws_iam_role.detector.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "clickops.handler.handler"
  memory_size      = 256
  timeout          = 30
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  environment {
    variables = {
      CLICKOPS_TABLE         = aws_dynamodb_table.events.name
      CLICKOPS_SELF_ROLE_ARN = local.role_arn
      CLICKOPS_TRUSTED_ROLES = join(",", var.trusted_role_arns)
    }
  }

  depends_on = [aws_cloudwatch_log_group.detector, aws_iam_role_policy.detector]
}
