locals {
  repo_path = "${var.github_owner}/${var.github_repo}"
}

data "aws_iam_policy_document" "ci_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only this repo's main branch and its pull requests.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${local.repo_path}:ref:refs/heads/main",
        "repo:${local.repo_path}:pull_request",
      ]
    }
  }
}

resource "aws_iam_role" "ci" {
  name                 = "clickops-ci"
  assume_role_policy   = data.aws_iam_policy_document.ci_trust.json
  max_session_duration = 3600
}

# Scoped to the resource types the sandbox and detector roots manage.
# Day 24 narrows this to resource-level ARNs.
data "aws_iam_policy_document" "ci" {
  statement {
    sid       = "StateBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.state.arn]
  }

  statement {
    sid       = "StateObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/*"]
  }

  statement {
    sid = "SandboxNetworkAndCompute"
    actions = [
      "ec2:Describe*",
      "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute",
      "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute",
      "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway",
      "ec2:AttachInternetGateway", "ec2:DetachInternetGateway",
      "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute",
      "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable",
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
      "ec2:ModifySecurityGroupRules", "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
      "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
      "ec2:RunInstances", "ec2:StartInstances", "ec2:StopInstances", "ec2:TerminateInstances",
      "ec2:ModifyInstanceAttribute", "ec2:CreateTags", "ec2:DeleteTags",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "SandboxAndDetectorBuckets"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::clickops-*",
      "arn:aws:s3:::clickops-*/*",
    ]
  }

  statement {
    sid     = "ClickopsIamRolesAndPolicies"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::${var.account_id}:role/clickops-*",
      "arn:aws:iam::${var.account_id}:policy/clickops-*",
    ]
  }

  statement {
    sid       = "IamRead"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:ListRoles", "iam:ListPolicies"]
    resources = ["*"]
  }

  statement {
    sid       = "ClickopsLambda"
    actions   = ["lambda:*"]
    resources = ["arn:aws:lambda:*:${var.account_id}:function:clickops-*"]
  }

  statement {
    sid       = "LambdaRead"
    actions   = ["lambda:ListFunctions", "lambda:GetAccountSettings"]
    resources = ["*"]
  }

  statement {
    sid = "Route53"
    actions = [
      "route53:CreateHostedZone", "route53:DeleteHostedZone", "route53:GetHostedZone",
      "route53:ListHostedZones", "route53:ListHostedZonesByName", "route53:ChangeResourceRecordSets",
      "route53:ListResourceRecordSets", "route53:GetChange", "route53:ChangeTagsForResource",
      "route53:ListTagsForResource", "route53:AssociateVPCWithHostedZone",
      "route53:DisassociateVPCFromHostedZone",
    ]
    resources = ["*"]
  }

  statement {
    sid = "DetectorServices"
    actions = [
      "dynamodb:*", "sns:*", "sqs:*", "events:*", "cloudtrail:*",
      "logs:*", "cloudwatch:*",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci" {
  name   = "clickops-ci"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.ci.json
}
