"""End to end with moto-backed comparators: live AWS state is changed, then the event replayed."""

import json
from typing import Any

import boto3
import pytest
from conftest import load_fixture
from moto import mock_aws

from clickops import handler, store


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A moto account matching a small Terraform state: one security group and one role."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    for var in ("CLICKOPS_SELF_ROLE_ARN", "CLICKOPS_TRUSTED_ROLES", "CLICKOPS_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLICKOPS_STATE_LOCATIONS", "tfstate/sandbox/terraform.tfstate")
    handler._table = handler._config = handler._reader = handler._notifier = None
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="ap-south-1")
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        group = ec2.create_security_group(GroupName="admin", Description="admin", VpcId=vpc)[
            "GroupId"
        ]
        ec2.revoke_security_group_egress(
            GroupId=group,
            IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        )
        ec2.authorize_security_group_ingress(
            GroupId=group,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "203.0.113.10/32"}],
                }
            ],
        )
        iam = boto3.client("iam", region_name="us-east-1")
        trust = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        )
        iam.create_role(RoleName="clickops-sandbox-app", AssumeRolePolicyDocument=trust)
        policy_arn = iam.create_policy(
            PolicyName="s3-full",
            PolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}],
                }
            ),
        )["Policy"]["Arn"]
        state = {
            "version": 4,
            "resources": [
                {
                    "mode": "managed",
                    "type": "aws_security_group",
                    "name": "admin",
                    "instances": [{"attributes": {"id": group, "ingress": [], "egress": []}}],
                },
                {
                    "mode": "managed",
                    "type": "aws_vpc_security_group_ingress_rule",
                    "name": "ssh",
                    "instances": [
                        {
                            "attributes": {
                                "id": "sgr-1",
                                "security_group_id": group,
                                "cidr_ipv4": "203.0.113.10/32",
                                "ip_protocol": "tcp",
                                "from_port": 22,
                                "to_port": 22,
                            }
                        }
                    ],
                },
                {
                    "mode": "managed",
                    "type": "aws_iam_role",
                    "name": "app",
                    "instances": [
                        {
                            "attributes": {
                                "id": "clickops-sandbox-app",
                                "name": "clickops-sandbox-app",
                                "assume_role_policy": trust,
                            }
                        }
                    ],
                },
            ],
        }
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        s3.put_object(Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=json.dumps(state))
        yield ec2, iam, group, policy_arn
    handler._table = handler._config = handler._reader = handler._notifier = None


def _replay(group: str, fixture: tuple[str, str], **detail: Any) -> dict[str, Any]:
    ddb = boto3.client("dynamodb", region_name="ap-south-1")
    if not ddb.list_tables()["TableNames"]:
        ddb.create_table(**store.TABLE_DEFINITION)
    raw = load_fixture(*fixture)
    params = raw["detail"]["requestParameters"]
    params.update({k: v for k, v in detail.items()})
    if "groupId" in params:
        params["groupId"] = group
    handler.handler(raw, None)
    scanned = boto3.resource("dynamodb", region_name="ap-south-1").Table(store.TABLE_NAME).scan()
    [item] = [i for i in scanned["Items"] if i["sk"] != "window"]
    return item


def test_opening_ssh_to_the_world_is_critical_with_the_diff(sandbox) -> None:  # type: ignore[no-untyped-def]
    ec2, _, group, _ = sandbox
    ec2.authorize_security_group_ingress(
        GroupId=group,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )
    item = _replay(group, ("ec2", "AuthorizeSecurityGroupIngress"))
    assert (item["outcome"], item["severity"]) == ("managed-drift", "critical")
    diff = json.loads(item["diff"])
    assert diff["ingress"]["live"] == ["tcp 22-22 0.0.0.0/0", "tcp 22-22 203.0.113.10/32"]
    assert diff["ingress"]["state"] == ["tcp 22-22 203.0.113.10/32"]


def test_opening_ssh_to_one_office_is_only_a_warning(sandbox) -> None:  # type: ignore[no-untyped-def]
    ec2, _, group, _ = sandbox
    ec2.authorize_security_group_ingress(
        GroupId=group,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "198.51.100.0/24"}],
            }
        ],
    )
    item = _replay(
        group,
        ("ec2", "AuthorizeSecurityGroupIngress"),
        ipPermissions={
            "items": [
                {
                    "ipProtocol": "tcp",
                    "fromPort": 22,
                    "toPort": 22,
                    "ipRanges": {"items": [{"cidrIp": "198.51.100.0/24"}]},
                }
            ]
        },
    )
    assert (item["outcome"], item["severity"]) == ("managed-drift", "warning")


def test_attaching_a_managed_policy_is_a_warning_with_the_diff(sandbox) -> None:  # type: ignore[no-untyped-def]
    _, iam, group, arn = sandbox
    iam.attach_role_policy(RoleName="clickops-sandbox-app", PolicyArn=arn)
    item = _replay(group, ("iam", "AttachRolePolicy"), policyArn=arn)
    assert (item["outcome"], item["severity"]) == ("managed-drift", "warning")
    assert json.loads(item["diff"])["attached_policy_arns"]["live"] == [arn]


def test_a_change_that_matches_state_is_ignored(sandbox) -> None:  # type: ignore[no-untyped-def]
    _, _, group, _ = sandbox
    item = _replay(group, ("ec2", "RevokeSecurityGroupIngress"))
    assert (item["outcome"], item["severity"]) == ("ignored", "none")
    assert item["reason"] == "live configuration matches state"


def test_deleting_the_group_is_a_managed_delete(sandbox) -> None:  # type: ignore[no-untyped-def]
    ec2, _, group, _ = sandbox
    ec2.revoke_security_group_ingress(
        GroupId=group,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "203.0.113.10/32"}],
            }
        ],
    )
    ec2.delete_security_group(GroupId=group)
    item = _replay(group, ("ec2", "DeleteSecurityGroup"))
    assert (item["outcome"], item["severity"]) == ("managed-delete", "critical")


def test_group_removed_before_a_later_event_is_seen_still_reports_a_delete(sandbox) -> None:  # type: ignore[no-untyped-def]
    ec2, _, group, _ = sandbox
    ec2.revoke_security_group_ingress(
        GroupId=group,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "203.0.113.10/32"}],
            }
        ],
    )
    ec2.delete_security_group(GroupId=group)
    item = _replay(group, ("ec2", "RevokeSecurityGroupIngress"))
    assert item["outcome"] == "managed-delete"
