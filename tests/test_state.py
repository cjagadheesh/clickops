import json
import logging
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from clickops.config import StateLocation
from clickops.state import StateError, StateReader, build_index, parse_state

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "state" / "sandbox-state.json"
SG = "sg-0a1b2c3d4e5f60718"
ADMIN_SG = "sg-0b2c3d4e5f6071829"
BUCKET = "clickops-sandbox-111122223333"
ROLE = "clickops-sandbox-app"


def _state() -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())
    assert isinstance(data, dict)
    return data


def test_every_managed_resource_is_found_by_id_and_by_arn() -> None:
    state = _state()
    index = build_index([state])
    managed = [r for r in state["resources"] if r["mode"] == "managed"]
    assert len(index) == len(managed) == 22
    for resource in managed:
        attrs = resource["instances"][0]["attributes"]
        found = index.get(resource["type"], attrs["id"])
        assert found is not None, resource["name"]
        assert found.address == f"{resource['type']}.{resource['name']}"
        if attrs.get("arn"):
            assert index.get_by_arn(attrs["arn"]) == found


def test_data_sources_are_not_indexed() -> None:
    index = build_index([_state()])
    assert index.get("aws_caller_identity", "111122223333") is None
    assert index.get("aws_ami", "ami-0abc1234") is None


def test_missing_resources_are_not_found() -> None:
    index = build_index([_state()])
    assert index.get("aws_security_group", "sg-doesnotexist") is None
    assert index.get_by_arn("arn:aws:iam::111122223333:role/nope") is None


def test_security_group_rules_map_to_their_group() -> None:
    index = build_index([_state()])
    rules = index.children("aws_security_group", SG)
    assert [r.type for r in rules] == ["aws_vpc_security_group_ingress_rule"]
    assert index.owner("aws_vpc_security_group_ingress_rule", "sgr-0123456789abcdef0") == index.get(
        "aws_security_group", SG
    )
    assert [r.id for r in index.children("aws_security_group", ADMIN_SG)] == [
        "sgr-0fedcba9876543210"
    ]


def test_s3_config_resources_map_to_their_bucket() -> None:
    index = build_index([_state()])
    children = {r.type for r in index.children("aws_s3_bucket", BUCKET)}
    assert children == {
        "aws_s3_bucket_versioning",
        "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_public_access_block",
    }
    owner = index.owner("aws_s3_bucket_public_access_block", BUCKET)
    assert owner is not None and owner.type == "aws_s3_bucket"


def test_role_policies_and_attachments_map_to_their_role() -> None:
    index = build_index([_state()])
    assert {r.type for r in index.children("aws_iam_role", ROLE)} == {
        "aws_iam_role_policy",
        "aws_iam_role_policy_attachment",
    }


def test_other_children_map_to_parents() -> None:
    index = build_index([_state()])
    zone = "Z0123456789ABCDEFGHIJ"
    assert len(index.children("aws_route53_zone", zone)) == 2
    assert len(index.children("aws_instance", "i-0123456789abcdef0")) == 1


def test_a_resource_without_a_parent_owns_itself() -> None:
    index = build_index([_state()])
    group = index.get("aws_security_group", SG)
    assert index.owner("aws_security_group", SG) == group


def test_unsupported_version_is_rejected() -> None:
    with pytest.raises(StateError, match="version"):
        parse_state({"version": 3, "resources": []})


def test_attribute_values_never_appear_in_repr() -> None:
    index = build_index([_state()])
    function = index.get("aws_lambda_function", "clickops-sandbox-hello")
    assert function is not None
    assert "hunter2" not in repr(function)
    assert "hunter2" in json.dumps(function.attributes)  # still available to comparators


def test_multiple_state_files_merge() -> None:
    other = {
        "version": 4,
        "resources": [
            {
                "mode": "managed",
                "type": "aws_sns_topic",
                "name": "critical",
                "instances": [{"attributes": {"id": "arn:t", "arn": "arn:t"}}],
            }
        ],
    }
    index = build_index([_state(), other])
    assert index.get("aws_sns_topic", "arn:t") is not None
    assert index.get("aws_security_group", SG) is not None


def test_module_and_indexed_addresses() -> None:
    state = {
        "version": 4,
        "resources": [
            {
                "module": "module.net",
                "mode": "managed",
                "type": "aws_security_group",
                "name": "x",
                "instances": [{"index_key": 1, "attributes": {"id": "sg-1"}}],
            }
        ],
    }
    assert parse_state(state)[0].address == "module.net.aws_security_group.x[1]"


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        client.create_bucket(
            Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        client.put_object(
            Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=FIXTURE.read_bytes()
        )
        yield client


def test_reader_loads_index_from_s3_and_caches_by_etag(s3) -> None:  # type: ignore[no-untyped-def]
    reader = StateReader([StateLocation(bucket="tfstate", key="sandbox/terraform.tfstate")], s3)
    assert reader.load().get("aws_security_group", SG) is not None
    assert reader.downloads == 1
    reader.load()
    reader.load()
    assert reader.downloads == 1  # unchanged ETag: only HeadObject calls


def test_reader_refreshes_when_the_object_changes(s3) -> None:  # type: ignore[no-untyped-def]
    reader = StateReader([StateLocation(bucket="tfstate", key="sandbox/terraform.tfstate")], s3)
    reader.load()
    state = _state()
    state["resources"] = [r for r in state["resources"] if r["type"] != "aws_instance"]
    s3.put_object(Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=json.dumps(state))
    index = reader.load()
    assert reader.downloads == 2
    assert index.get("aws_instance", "i-0123456789abcdef0") is None
    assert index.get("aws_security_group", SG) is not None


def test_reader_rejects_bad_state_with_location_in_error(s3) -> None:  # type: ignore[no-untyped-def]
    s3.put_object(Bucket="tfstate", Key="bad.tfstate", Body=b'{"version": 3}')
    reader = StateReader([StateLocation(bucket="tfstate", key="bad.tfstate")], s3)
    with pytest.raises(StateError, match="s3://tfstate/bad.tfstate"):
        reader.load()


def test_reader_logs_addresses_but_no_attribute_values(s3, caplog) -> None:  # type: ignore[no-untyped-def]
    reader = StateReader([StateLocation(bucket="tfstate", key="sandbox/terraform.tfstate")], s3)
    with caplog.at_level(logging.INFO, logger="clickops"):
        reader.load()
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "aws_lambda_function.hello" in text
    assert "hunter2" not in text
    assert "10.20.1.10" not in text
