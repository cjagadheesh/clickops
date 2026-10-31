import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cloudtrail"

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

ALL = sorted(FIXTURES.rglob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("path", ALL, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_fixture_is_valid_cloudtrail_event(path: Path) -> None:
    event = _load(path)
    assert event["_source"] in {"real", "synthetic"}
    assert event["detail-type"] == "AWS API Call via CloudTrail"
    detail = event["detail"]
    for key in ("eventID", "eventName", "eventSource", "eventTime", "awsRegion", "userIdentity"):
        assert detail[key], f"{path.name}: missing {key}"
    assert "errorCode" not in detail
    assert detail["readOnly"] is False
    assert detail["eventSource"] == f"{path.parent.name}.amazonaws.com"
    assert event["source"] == f"aws.{path.parent.name}"
    assert detail["eventName"] == path.stem.split(".")[0]


@pytest.mark.parametrize(("service", "name"), [(s, n) for s, ns in COVERAGE.items() for n in ns])
def test_every_watched_event_has_a_fixture(service: str, name: str) -> None:
    names = {_load(p)["detail"]["eventName"] for p in (FIXTURES / service).glob("*.json")}
    if service == "lambda":
        assert any(n.startswith(name) for n in names), f"no fixture for {name}"
    else:
        assert name in names, f"no fixture for {name}"


def test_fixture_event_ids_are_unique_per_file() -> None:
    ids = [_load(p)["detail"]["eventID"] for p in ALL]
    assert len(ids) == len(set(ids))


def test_at_least_two_console_human_fixtures() -> None:
    console = [
        p
        for p in ALL
        if _load(p)["detail"]["userIdentity"]["sessionContext"]["attributes"].get(
            "sessionCredentialFromConsole"
        )
        == "true"
    ]
    assert len(console) >= 2


def test_iam_and_route53_events_arrive_in_us_east_1() -> None:
    for service in ("iam", "route53"):
        for path in (FIXTURES / service).glob("*.json"):
            assert _load(path)["detail"]["awsRegion"] == "us-east-1"
