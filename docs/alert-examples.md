# Example alerts

Rendered from the fixtures by `scripts/render_example_alerts.py`; do not edit by hand.
The messages are what the detector posts to Slack (Block Kit JSON) and, for critical
findings, emails through `clickops-critical`.

## SSH opened to the world on the admin security group

Slack fallback text: 🔴 critical: Terraform-managed resource changed outside Terraform - sg#sg-0b2c3d4e5f6071829 by asha@example.com

```json
{
  "text": "🔴 critical: Terraform-managed resource changed outside Terraform - sg#sg-0b2c3d4e5f6071829 by asha@example.com",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🔴 Terraform-managed resource changed outside Terraform"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Severity*\ncritical"
        },
        {
          "type": "mrkdwn",
          "text": "*Outcome*\nmanaged-drift"
        },
        {
          "type": "mrkdwn",
          "text": "*Resource*\n`sg#sg-0b2c3d4e5f6071829`"
        },
        {
          "type": "mrkdwn",
          "text": "*Who*\nasha@example.com (CLI or API)"
        },
        {
          "type": "mrkdwn",
          "text": "*Event*\nAuthorizeSecurityGroupIngress"
        },
        {
          "type": "mrkdwn",
          "text": "*When (UTC)*\n2026-10-26 10:15:30"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "```ingress:\n  + tcp 22-22 0.0.0.0/0```"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Restore the coded state*\n```terraform apply -target=aws_security_group.admin -target=aws_vpc_security_group_ingress_rule.admin_ssh```"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "live configuration differs from Terraform state; ingress from the world on a port other than 80 or 443"
        }
      ]
    }
  ]
}
```

Email subject: `[clickops critical] managed-drift: sg#sg-0b2c3d4e5f6071829`

```text
Terraform-managed resource changed outside Terraform

Resource: sg#sg-0b2c3d4e5f6071829
Who:      asha@example.com (CLI or API)
Event:    AuthorizeSecurityGroupIngress at 2026-10-26 10:15:30 UTC
Why:      live configuration differs from Terraform state; ingress from the world on a port other than 80 or 443

Changes (- coded, + live):
ingress:
  + tcp 22-22 0.0.0.0/0

To restore the coded state:
terraform apply -target=aws_security_group.admin -target=aws_vpc_security_group_ingress_rule.admin_ssh
```

## AmazonS3FullAccess attached to the sandbox role

Slack fallback text: 🟠 warning: Terraform-managed resource changed outside Terraform - iam-role#clickops-sandbox-app by asha@example.com

```json
{
  "text": "🟠 warning: Terraform-managed resource changed outside Terraform - iam-role#clickops-sandbox-app by asha@example.com",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🟠 Terraform-managed resource changed outside Terraform"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Severity*\nwarning"
        },
        {
          "type": "mrkdwn",
          "text": "*Outcome*\nmanaged-drift"
        },
        {
          "type": "mrkdwn",
          "text": "*Resource*\n`iam-role#clickops-sandbox-app`"
        },
        {
          "type": "mrkdwn",
          "text": "*Who*\nasha@example.com (CLI or API)"
        },
        {
          "type": "mrkdwn",
          "text": "*Event*\nAttachRolePolicy"
        },
        {
          "type": "mrkdwn",
          "text": "*When (UTC)*\n2026-10-26 10:15:30"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "```attached_policy_arns:\n  + arn:aws:iam::aws:policy/AmazonS3FullAccess```"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Restore the coded state*\n```terraform apply -target=aws_iam_role.app -target=aws_iam_role_policy.app -target=aws_iam_role_policy_attachment.app_logs```"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "live configuration differs from Terraform state"
        }
      ]
    }
  ]
}
```
