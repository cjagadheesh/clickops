import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import sg
from clickops.compare.base import FieldChange
from clickops.models import ResourceRef
from clickops.resolvers.base import SG, find_in_state


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def group(env):  # type: ignore[no-untyped-def]
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="ap-south-1")
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        group_id = ec2.create_security_group(GroupName="web", Description="web", VpcId=vpc)[
            "GroupId"
        ]
        ec2.revoke_security_group_egress(
            GroupId=group_id,
            IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        )
        ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                }
            ],
        )
        yield ec2, group_id


def _compare(group_id: str, *extra):  # type: ignore[no-untyped-def]
    index = index_of(
        resource("aws_security_group", "web", id=group_id, ingress=[], egress=[]),
        resource(
            "aws_vpc_security_group_ingress_rule",
            "https",
            id="sgr-1",
            security_group_id=group_id,
            cidr_ipv4="0.0.0.0/0",
            ip_protocol="tcp",
            from_port=443,
            to_port=443,
        ),
        *extra,
    )
    ref = ResourceRef(type=SG, id=group_id, region="ap-south-1")
    state = find_in_state(index, ref)
    assert state is not None
    return sg.compare(ref, index, state)


def test_matching_group_has_no_diff(group) -> None:  # type: ignore[no-untyped-def]
    _, group_id = group
    result = _compare(group_id)
    assert result.exists and not result.drifted


def test_added_ingress_rule_is_reported(group) -> None:  # type: ignore[no-untyped-def]
    ec2, group_id = group
    ec2.authorize_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )
    result = _compare(group_id)
    assert result.changes == [
        FieldChange(
            "ingress", ["tcp 443-443 0.0.0.0/0"], ["tcp 22-22 0.0.0.0/0", "tcp 443-443 0.0.0.0/0"]
        )
    ]


def test_removed_ingress_rule_is_reported(group) -> None:  # type: ignore[no-untyped-def]
    ec2, group_id = group
    ec2.revoke_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )
    result = _compare(group_id)
    assert result.diff() == {"ingress": {"state": ["tcp 443-443 0.0.0.0/0"], "live": []}}


def test_changed_cidr_is_reported(group) -> None:  # type: ignore[no-untyped-def]
    ec2, group_id = group
    ec2.revoke_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )
    ec2.authorize_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 443,
                "ToPort": 443,
                "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
            }
        ],
    )
    assert _compare(group_id).diff()["ingress"]["live"] == ["tcp 443-443 10.0.0.0/8"]


def test_added_egress_rule_is_reported(group) -> None:  # type: ignore[no-untyped-def]
    ec2, group_id = group
    ec2.authorize_security_group_egress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 8443,
                "ToPort": 8443,
                "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
            }
        ],
    )
    result = _compare(group_id)
    assert list(result.diff()) == ["egress"]
    assert result.diff()["egress"]["live"] == ["tcp 8443-8443 10.0.0.0/8"]


def test_referenced_group_and_all_protocol_rules(group) -> None:  # type: ignore[no-untyped-def]
    ec2, group_id = group
    ec2.authorize_security_group_egress(
        GroupId=group_id,
        IpPermissions=[{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": group_id}]}],
    )
    extra = resource(
        "aws_vpc_security_group_egress_rule",
        "self_all",
        id="sgr-2",
        security_group_id=group_id,
        referenced_security_group_id=group_id,
        ip_protocol="-1",
    )
    result = _compare(group_id, extra)
    assert not result.drifted


def test_deleted_group_means_it_no_longer_exists(env) -> None:  # type: ignore[no-untyped-def]
    with mock_aws():
        index = index_of(resource("aws_security_group", "web", id="sg-0123456789abcdef0"))
        ref = ResourceRef(type=SG, id="sg-0123456789abcdef0", region="ap-south-1")
        state = find_in_state(index, ref)
        assert state is not None
        assert sg.compare(ref, index, state).exists is False


def test_inline_rules_in_the_group_resource_are_expanded(group) -> None:  # type: ignore[no-untyped-def]
    _, group_id = group
    index = index_of(
        resource(
            "aws_security_group",
            "web",
            id=group_id,
            egress=[],
            ingress=[
                {
                    "protocol": "tcp",
                    "from_port": 443,
                    "to_port": 443,
                    "cidr_blocks": ["0.0.0.0/0"],
                    "ipv6_cidr_blocks": [],
                    "security_groups": [],
                    "prefix_list_ids": [],
                    "self": False,
                }
            ],
        )
    )
    state = index.get("aws_security_group", group_id)
    assert state is not None
    ref = ResourceRef(type=SG, id=group_id, region="ap-south-1")
    assert not sg.compare(ref, index, state).drifted
