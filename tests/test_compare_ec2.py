from typing import Any

import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import ec2 as compare_ec2
from clickops.models import ResourceRef
from clickops.resolvers.base import EC2_INSTANCE, find_in_state


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="ap-south-1")
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
        groups = {
            name: ec2.create_security_group(GroupName=name, Description=name, VpcId=vpc)["GroupId"]
            for name in ("web", "admin", "extra")
        }
        instance = ec2.run_instances(
            ImageId="ami-12c6146b",
            MinCount=1,
            MaxCount=1,
            InstanceType="t4g.nano",
            SubnetId=subnet,
            SecurityGroupIds=[groups["web"], groups["admin"]],
        )["Instances"][0]["InstanceId"]
        ec2.stop_instances(InstanceIds=[instance])
        yield ec2, instance, groups


def _compare(instance: str, groups: dict[str, str], **overrides: Any):  # type: ignore[no-untyped-def]
    attrs = {
        "id": instance,
        "instance_type": "t4g.nano",
        "vpc_security_group_ids": [groups["web"], groups["admin"]],
        "iam_instance_profile": "",
    }
    attrs.update(overrides)
    index = index_of(
        resource("aws_instance", "main", **attrs),
        resource(
            "aws_ec2_instance_state", "main", id=instance, instance_id=instance, state="stopped"
        ),
    )
    ref = ResourceRef(type=EC2_INSTANCE, id=instance, region="ap-south-1")
    state = find_in_state(index, ref)
    assert state is not None
    return compare_ec2.compare(ref, index, state)


def test_matching_stopped_instance_has_no_diff(aws) -> None:  # type: ignore[no-untyped-def]
    _, instance, groups = aws
    result = _compare(instance, groups)
    assert result.exists and not result.drifted


def test_changed_instance_type_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    ec2, instance, groups = aws
    ec2.modify_instance_attribute(InstanceId=instance, InstanceType={"Value": "t4g.small"})
    assert _compare(instance, groups).diff() == {
        "instance_type": {"state": "t4g.nano", "live": "t4g.small"}
    }


def test_changed_security_groups_are_reported(aws) -> None:  # type: ignore[no-untyped-def]
    ec2, instance, groups = aws
    ec2.modify_instance_attribute(InstanceId=instance, Groups=[groups["web"], groups["extra"]])
    diff = _compare(instance, groups).diff()
    assert diff["security_group_ids"]["live"] == sorted([groups["web"], groups["extra"]])


def test_attached_instance_profile_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    ec2, instance, groups = aws
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_instance_profile(InstanceProfileName="ops")
    ec2.associate_iam_instance_profile(IamInstanceProfile={"Name": "ops"}, InstanceId=instance)
    assert _compare(instance, groups).diff() == {"instance_profile": {"state": "", "live": "ops"}}


def test_started_instance_is_reported(aws) -> None:  # type: ignore[no-untyped-def]
    ec2, instance, groups = aws
    ec2.start_instances(InstanceIds=[instance])
    assert _compare(instance, groups).diff() == {
        "run_state": {"state": "stopped", "live": "running"}
    }


def test_state_without_instance_state_resource_uses_the_instance_attribute(aws) -> None:  # type: ignore[no-untyped-def]
    _, instance, groups = aws
    index = index_of(
        resource(
            "aws_instance",
            "main",
            id=instance,
            instance_type="t4g.nano",
            vpc_security_group_ids=[groups["web"], groups["admin"]],
            instance_state="stopped",
        )
    )
    ref = ResourceRef(type=EC2_INSTANCE, id=instance, region="ap-south-1")
    state = find_in_state(index, ref)
    assert state is not None
    assert not compare_ec2.compare(ref, index, state).drifted


def test_terminated_instance_no_longer_exists(aws) -> None:  # type: ignore[no-untyped-def]
    ec2, instance, groups = aws
    ec2.terminate_instances(InstanceIds=[instance])
    assert _compare(instance, groups).exists is False


def test_run_state_collapses_lifecycle_states() -> None:
    assert compare_ec2.run_state("pending") == "running"
    assert compare_ec2.run_state("stopping") == "stopped"
