"""Validate IAM policies with IAM Access Analyzer; fail on any ERROR or SECURITY_WARNING finding.

Policies come from a Terraform plan (``terraform show -json tfplan > plan.json``) and/or the policy
templates in infra/bootstrap/policies (rendered with placeholder values).

    uv run python scripts/validate_policies.py --plan plan.json
    uv run python scripts/validate_policies.py --templates infra/bootstrap/policies
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FAILING = {"ERROR", "SECURITY_WARNING"}
PLACEHOLDERS = {
    "account_id": "111122223333",
    "region": "ap-south-1",
    "state_bucket": "clickops-tfstate-111122223333",
}
# Resource type -> (attribute holding the document, policy kind)
POLICY_ATTRIBUTES: dict[str, list[tuple[str, str]]] = {
    "aws_iam_policy": [("policy", "identity")],
    "aws_iam_role_policy": [("policy", "identity")],
    "aws_iam_user_policy": [("policy", "identity")],
    "aws_iam_group_policy": [("policy", "identity")],
    "aws_iam_role": [("assume_role_policy", "trust")],
    "aws_s3_bucket_policy": [("policy", "resource")],
    "aws_sqs_queue_policy": [("policy", "resource")],
    "aws_sns_topic_policy": [("policy", "resource")],
}


@dataclass(frozen=True)
class PolicyDoc:
    source: str
    kind: str  # identity, trust or resource
    document: str


def plan_policies(plan: dict[str, Any]) -> list[PolicyDoc]:
    """Policy documents in a ``terraform show -json`` plan whose values are known at plan time."""
    found = []
    for change in plan.get("resource_changes", []):
        attributes = POLICY_ATTRIBUTES.get(change.get("type", ""))
        after = (change.get("change") or {}).get("after") or {}
        for attribute, kind in attributes or []:
            document = after.get(attribute)
            if isinstance(document, str) and document.strip().startswith("{"):
                found.append(PolicyDoc(f"{change['address']}.{attribute}", kind, document))
    return found


def template_policies(directory: Path) -> list[PolicyDoc]:
    found = []
    for path in sorted(directory.glob("*.json.tftpl")):
        text = re.sub(r"\$\{(\w+)\}", lambda m: PLACEHOLDERS[m.group(1)], path.read_text())
        found.append(PolicyDoc(str(path), "identity", text))
    return found


def validate(client: Any, policy: PolicyDoc) -> list[dict[str, Any]]:
    """Failing findings for one policy."""
    kwargs: dict[str, Any] = {"policyDocument": policy.document}
    if policy.kind == "identity":
        kwargs["policyType"] = "IDENTITY_POLICY"
    elif policy.kind == "trust":
        kwargs["policyType"] = "RESOURCE_POLICY"
        kwargs["validatePolicyResourceType"] = "AWS::IAM::AssumeRolePolicyDocument"
    else:
        kwargs["policyType"] = "RESOURCE_POLICY"
    findings: list[dict[str, Any]] = []
    for page in client.get_paginator("validate_policy").paginate(**kwargs):
        findings += [f for f in page["findings"] if f["findingType"] in FAILING]
    return findings


def run(client: Any, policies: Iterable[PolicyDoc]) -> int:
    """Print every failing finding; return the number of failing policies."""
    failing = 0
    count = 0
    for policy in policies:
        count += 1
        findings = validate(client, policy)
        for finding in findings:
            print(
                f"{finding['findingType']} {policy.source}: {finding['issueCode']}: "
                f"{finding['findingDetails']}"
            )
        failing += bool(findings)
    print(f"validated {count} policies, {failing} with errors or security warnings")
    return failing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, help="terraform show -json output")
    parser.add_argument("--templates", type=Path, help="folder of *.json.tftpl policy templates")
    parser.add_argument("--region", default="ap-south-1")
    args = parser.parse_args(argv)
    if not args.plan and not args.templates:
        parser.error("give --plan and/or --templates")

    policies: list[PolicyDoc] = []
    if args.plan:
        policies += plan_policies(json.loads(args.plan.read_text()))
    if args.templates:
        policies += template_policies(args.templates)

    import boto3

    client = boto3.client("accessanalyzer", region_name=args.region)
    return 1 if run(client, policies) else 0


if __name__ == "__main__":
    sys.exit(main())
