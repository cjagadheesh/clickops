"""Render the two headline alerts from fixtures into docs/alert-examples.md.

uv run python scripts/render_example_alerts.py          # rewrite the doc
uv run python scripts/render_example_alerts.py --check  # fail if the doc is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from clickops import alerts
from clickops.actors import classify
from clickops.events import normalize
from clickops.models import Finding, Outcome, ResourceRef, Severity

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "cloudtrail"
DOC = ROOT / "docs" / "alert-examples.md"
ADMIN = "203.0.113.10/32"


def _event(service: str, name: str) -> Any:
    event = normalize(json.loads((FIXTURES / service / f"{name}.json").read_text()))
    assert event is not None
    return event


def scenarios() -> list[tuple[str, Finding, str, list[str]]]:
    ssh = _event("ec2", "AuthorizeSecurityGroupIngress")
    attach = _event("iam", "AttachRolePolicy")
    return [
        (
            "SSH opened to the world on the admin security group",
            Finding(
                event=ssh,
                actor=classify(ssh),
                resource=ResourceRef(type="sg", id="sg-0b2c3d4e5f6071829"),
                outcome=Outcome.MANAGED_DRIFT,
                severity=Severity.CRITICAL,
                diff={
                    "ingress": {
                        "state": [f"tcp 22-22 {ADMIN}"],
                        "live": ["tcp 22-22 0.0.0.0/0", f"tcp 22-22 {ADMIN}"],
                    }
                },
            ),
            "live configuration differs from Terraform state; "
            "ingress from the world on a port other than 80 or 443",
            ["aws_security_group.admin", "aws_vpc_security_group_ingress_rule.admin_ssh"],
        ),
        (
            "AmazonS3FullAccess attached to the sandbox role",
            Finding(
                event=attach,
                actor=classify(attach),
                resource=ResourceRef(type="iam-role", id="clickops-sandbox-app"),
                outcome=Outcome.MANAGED_DRIFT,
                severity=Severity.WARNING,
                diff={
                    "attached_policy_arns": {
                        "state": [
                            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                        ],
                        "live": [
                            "arn:aws:iam::aws:policy/AmazonS3FullAccess",
                            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                        ],
                    }
                },
            ),
            "live configuration differs from Terraform state",
            [
                "aws_iam_role.app",
                "aws_iam_role_policy.app",
                "aws_iam_role_policy_attachment.app_logs",
            ],
        ),
    ]


def render() -> str:
    parts = [
        "# Example alerts",
        "",
        "Rendered from the fixtures by `scripts/render_example_alerts.py`; do not edit by hand.",
        "The messages are what the detector posts to Slack (Block Kit JSON) and, for critical",
        "findings, emails through `clickops-critical`.",
    ]
    for title, finding, reason, targets in scenarios():
        payload = alerts.render_slack(finding, reason, targets)
        parts += [
            "",
            f"## {title}",
            "",
            f"Slack fallback text: {payload['text']}",
            "",
            "```json",
            json.dumps(payload, indent=2, ensure_ascii=False),
            "```",
        ]
        if finding.severity is Severity.CRITICAL:
            subject, body = alerts.render_email(finding, reason, targets)
            parts += ["", f"Email subject: `{subject}`", "", "```text", body, "```"]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not DOC.exists() or DOC.read_text() != text:
            print(f"{DOC} is out of date; run scripts/render_example_alerts.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
