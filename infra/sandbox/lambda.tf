data "archive_file" "hello" {
  type        = "zip"
  source_file = "${path.module}/lambda/hello.py"
  output_path = "${path.module}/.build/hello.zip"
}

resource "aws_lambda_function" "hello" {
  function_name    = "clickops-sandbox-hello"
  role             = aws_iam_role.app.arn
  runtime          = "python3.12"
  handler          = "hello.handler"
  architectures    = ["arm64"]
  memory_size      = 128
  timeout          = 10
  filename         = data.archive_file.hello.output_path
  source_code_hash = data.archive_file.hello.output_base64sha256

  environment {
    variables = {
      GREETING = "hello"
    }
  }
}
