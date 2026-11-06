import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cloudtrail"


def fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.rglob("*.json"))


def load_fixture(service: str, name: str) -> dict[str, Any]:
    data = json.loads((FIXTURE_DIR / service / f"{name}.json").read_text())
    assert isinstance(data, dict)
    return data


# Event names from the plan's resource coverage table, by service directory.
# Lambda names carry API-version suffixes, so they are matched by prefix.
COVERAGE: dict[str, list[str]] = {
    "ec2": [
        "CreateSecurityGroup",
        "DeleteSecurityGroup",
        "AuthorizeSecurityGroupIngress",
        "AuthorizeSecurityGroupEgress",
        "RevokeSecurityGroupIngress",
        "RevokeSecurityGroupEgress",
        "ModifySecurityGroupRules",
        "RunInstances",
        "TerminateInstances",
        "ModifyInstanceAttribute",
        "StartInstances",
        "StopInstances",
    ],
    "iam": [
        "CreateRole",
        "DeleteRole",
        "UpdateAssumeRolePolicy",
        "PutRolePolicy",
        "DeleteRolePolicy",
        "AttachRolePolicy",
        "DetachRolePolicy",
        "CreatePolicy",
        "CreatePolicyVersion",
    ],
    "s3": [
        "CreateBucket",
        "DeleteBucket",
        "PutBucketPolicy",
        "DeleteBucketPolicy",
        "PutBucketPublicAccessBlock",
        "DeleteBucketPublicAccessBlock",
        "PutBucketVersioning",
        "PutBucketEncryption",
    ],
    "lambda": [
        "CreateFunction",
        "DeleteFunction",
        "UpdateFunctionConfiguration",
        "UpdateFunctionCode",
        "AddPermission",
    ],
    "route53": ["ChangeResourceRecordSets", "CreateHostedZone", "DeleteHostedZone"],
}
