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

# Resource-scoped permissions for the sandbox and detector roots. The policies are templates in
# policies/ (one per area, each under the 6,144-character limit for managed policies) so tests and
# Access Analyzer can read them. Resources are named exactly where AWS supports it; the rest are
# limited to this account and region, and the few "*" resources are read-only or create-only calls.
locals {
  ci_policy_vars = {
    account_id   = var.account_id
    region       = var.region
    state_bucket = aws_s3_bucket.state.bucket
  }

  ci_policies = {
    "clickops-ci-state-s3"          = "ci_state_s3"
    "clickops-ci-ec2"               = "ci_ec2"
    "clickops-ci-iam-lambda"        = "ci_iam_lambda"
    "clickops-ci-data-events"       = "ci_data_events"
    "clickops-ci-observability-dns" = "ci_observability_dns"
  }
}

resource "aws_iam_policy" "ci" {
  for_each = local.ci_policies

  name   = each.key
  policy = templatefile("${path.module}/policies/${each.value}.json.tftpl", local.ci_policy_vars)
}

resource "aws_iam_role_policy_attachment" "ci" {
  for_each = aws_iam_policy.ci

  role       = aws_iam_role.ci.name
  policy_arn = each.value.arn
}
