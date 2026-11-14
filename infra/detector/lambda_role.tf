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

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
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

  # PutItem stores findings; GetItem and UpdateItem keep the alert repeat counters.
  statement {
    sid       = "StoreEvents"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.events.arn]
  }

  statement {
    sid       = "ReadSlackWebhook"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter${var.slack_webhook_parameter}"]
  }

  # SecureString parameters are encrypted with the AWS-managed SSM key.
  statement {
    sid       = "DecryptSlackWebhook"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }

  statement {
    sid       = "PublishCriticalAlerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.critical.arn]
  }

  # Terraform state is read for the sandbox and detector roots only (GET also covers HEAD).
  statement {
    sid     = "ReadTerraformState"
    actions = ["s3:GetObject"]
    resources = [
      "arn:aws:s3:::clickops-tfstate-${data.aws_caller_identity.current.account_id}/sandbox/terraform.tfstate",
      "arn:aws:s3:::clickops-tfstate-${data.aws_caller_identity.current.account_id}/detector/terraform.tfstate",
    ]
  }

  # Read-only calls the comparators make, each listed explicitly. EC2 describe calls do not support
  # resource-level permissions.
  statement {
    sid       = "CompareEc2"
    actions   = ["ec2:DescribeSecurityGroups", "ec2:DescribeInstances"]
    resources = ["*"]
  }

  statement {
    sid = "CompareIam"
    actions = [
      "iam:GetRole",
      "iam:ListRolePolicies",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/*",
    ]
  }

  statement {
    sid = "CompareS3"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
    ]
    resources = ["arn:aws:s3:::*"]
  }

  statement {
    sid       = "CompareLambda"
    actions   = ["lambda:GetFunctionConfiguration"]
    resources = ["arn:aws:lambda:*:${data.aws_caller_identity.current.account_id}:function:*"]
  }

  statement {
    sid       = "CompareRoute53"
    actions   = ["route53:ListResourceRecordSets"]
    resources = ["arn:aws:route53:::hostedzone/*"]
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
