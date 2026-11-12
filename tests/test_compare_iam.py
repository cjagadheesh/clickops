import json
from typing import Any

import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import iam
from clickops.compare.base import normalize_policy
from clickops.models import ResourceRef
from clickops.resolvers.base import IAM_POLICY, IAM_ROLE, find_in_state

TRUST = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}
INLINE = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}],
}
# moto does not ship AWS-managed policies, so the attached policies are created in the fixture.
S3_FULL = "arn:aws:iam::123456789012:policy/s3-full"
LOGS = "arn:aws:iam::123456789012:policy/logs"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("iam", region_name="us-east-1")
        client.create_role(RoleName="app", AssumeRolePolicyDocument=json.dumps(TRUST))
        client.put_role_policy(RoleName="app", PolicyName="read", PolicyDocument=json.dumps(INLINE))
        for name in ("s3-full", "logs"):
            client.create_policy(PolicyName=name, PolicyDocument=json.dumps(INLINE))
        client.attach_role_policy(RoleName="app", PolicyArn=LOGS)
        yield client


def _compare_role(**overrides: Any):  # type: ignore[no-untyped-def]
    attrs = {"id": "app", "name": "app", "assume_role_policy": json.dumps(TRUST)}
    attrs.update(overrides)
    index = index_of(
        resource("aws_iam_role", "app", **attrs),
        resource(
            "aws_iam_role_policy",
            "read",
            id="app:read",
            name="read",
            role="app",
            policy=json.dumps(INLINE),
        ),
        resource("aws_iam_role_policy_attachment", "logs", id="app-1", role="app", policy_arn=LOGS),
    )
    ref = ResourceRef(type=IAM_ROLE, id="app")
    state = find_in_state(index, ref)
    assert state is not None
    return iam.compare_role(ref, index, state)


def test_matching_role_has_no_diff(aws) -> None:  # type: ignore[no-untyped-def]
    assert not _compare_role().drifted


def test_changed_trust_policy_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    other = {
        **TRUST,
        "Statement": [{**TRUST["Statement"][0], "Principal": {"Service": "ec2.amazonaws.com"}}],
    }
    aws.update_assume_role_policy(RoleName="app", PolicyDocument=json.dumps(other))
    diff = _compare_role().diff()
    assert list(diff) == ["trust_policy"]
    assert diff["trust_policy"]["live"]["Statement"][0]["Principal"] == {
        "Service": ["ec2.amazonaws.com"]
    }


def test_changed_inline_policy_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    wider = {**INLINE, "Statement": [{**INLINE["Statement"][0], "Action": "s3:*"}]}
    aws.put_role_policy(RoleName="app", PolicyName="read", PolicyDocument=json.dumps(wider))
    assert list(_compare_role().diff()) == ["inline_policies"]


def test_added_inline_policy_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    aws.put_role_policy(RoleName="app", PolicyName="extra", PolicyDocument=json.dumps(INLINE))
    live = _compare_role().diff()["inline_policies"]["live"]
    assert sorted(live) == ["extra", "read"]


def test_attached_policy_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    aws.attach_role_policy(RoleName="app", PolicyArn=S3_FULL)
    assert _compare_role().diff() == {
        "attached_policy_arns": {"state": [LOGS], "live": sorted([S3_FULL, LOGS])}
    }


def test_detached_policy_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    aws.detach_role_policy(RoleName="app", PolicyArn=LOGS)
    assert _compare_role().diff()["attached_policy_arns"]["live"] == []


def test_policy_formatting_differences_are_not_drift(aws) -> None:  # type: ignore[no-untyped-def]
    reordered = {
        "Statement": [
            {"Resource": ["arn:aws:s3:::b/*"], "Action": ["s3:GetObject"], "Effect": "Allow"}
        ],
        "Version": "2012-10-17",
    }
    result = _compare_role()
    assert not result.drifted
    state_text = json.dumps(reordered)
    assert normalize_policy(state_text) == normalize_policy(INLINE)


def test_deleted_role_no_longer_exists(aws) -> None:  # type: ignore[no-untyped-def]
    aws.detach_role_policy(RoleName="app", PolicyArn=LOGS)
    aws.delete_role_policy(RoleName="app", PolicyName="read")
    aws.delete_role(RoleName="app")
    assert _compare_role().exists is False


def test_managed_policy_document_change_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    arn = aws.create_policy(PolicyName="p", PolicyDocument=json.dumps(INLINE))["Policy"]["Arn"]
    index = index_of(resource("aws_iam_policy", "p", id=arn, arn=arn, policy=json.dumps(INLINE)))
    ref = ResourceRef(type=IAM_POLICY, id=arn)
    state = find_in_state(index, ref)
    assert state is not None
    assert not iam.compare_policy(ref, index, state).drifted
    wider = {**INLINE, "Statement": [{**INLINE["Statement"][0], "Action": "*"}]}
    aws.create_policy_version(PolicyArn=arn, PolicyDocument=json.dumps(wider), SetAsDefault=True)
    assert list(iam.compare_policy(ref, index, state).diff()) == ["policy_document"]


def test_normalize_policy_single_value_equals_one_item_list() -> None:
    a = {
        "Version": "2012-10-17",
        "Statement": {"Effect": "Allow", "Action": "s3:Get*", "Resource": "*", "Principal": "*"},
    }
    b = {
        "Statement": [
            {
                "Principal": {"AWS": ["*"]},
                "Resource": ["*"],
                "Action": ["s3:Get*"],
                "Effect": "Allow",
            }
        ],
        "Version": "2012-10-17",
    }
    assert normalize_policy(a) == normalize_policy(b)
    assert normalize_policy(None) is None
