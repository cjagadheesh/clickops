import copy
import json
from pathlib import Path

import pytest
from conftest import fixture_paths, load_fixture

from clickops.events import NormalizationError, base_event_name, normalize


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_fixture_normalizes(path: Path) -> None:
    raw = json.loads(path.read_text())
    event = normalize(raw)
    assert event is not None
    assert event.event_id == raw["detail"]["eventID"]
    assert event.name == base_event_name(raw["detail"]["eventName"])
    assert not event.name[-1].isdigit()


@pytest.mark.parametrize(
    ("raw", "base"),
    [
        ("UpdateFunctionConfiguration20150331v2", "UpdateFunctionConfiguration"),
        ("CreateFunction20150331", "CreateFunction"),
        ("AddPermission20150331v2", "AddPermission"),
        ("RunInstances", "RunInstances"),
        ("CreateRole", "CreateRole"),
    ],
)
def test_base_event_name(raw: str, base: str) -> None:
    assert base_event_name(raw) == base


def test_ec2_fields() -> None:
    event = normalize(load_fixture("ec2", "AuthorizeSecurityGroupIngress"))
    assert event is not None
    assert event.source == "ec2.amazonaws.com"
    assert event.name == "AuthorizeSecurityGroupIngress"
    assert event.region == "ap-south-1"
    assert event.account == "111122223333"
    assert event.request_parameters["groupId"].startswith("sg-")
    assert event.user_identity["type"] == "AssumedRole"
    assert event.user_agent is not None and event.user_agent.startswith("aws-cli")
    assert event.source_ip == "203.0.113.25"


def test_iam_fields() -> None:
    event = normalize(load_fixture("iam", "AttachRolePolicy"))
    assert event is not None
    assert event.source == "iam.amazonaws.com"
    assert event.region == "us-east-1"
    assert event.request_parameters["roleName"] == "clickops-sandbox-app"


def test_s3_fields() -> None:
    event = normalize(load_fixture("s3", "PutBucketPublicAccessBlock"))
    assert event is not None
    assert event.source == "s3.amazonaws.com"
    assert event.request_parameters["bucketName"].startswith("clickops-sandbox-")
    assert event.response_elements == {}


def test_lambda_suffix_is_stripped() -> None:
    event = normalize(load_fixture("lambda", "UpdateFunctionConfiguration20150331v2"))
    assert event is not None
    assert event.name == "UpdateFunctionConfiguration"
    assert event.request_parameters["timeout"] == 60


def test_route53_fields() -> None:
    event = normalize(load_fixture("route53", "ChangeResourceRecordSets"))
    assert event is not None
    assert event.source == "route53.amazonaws.com"
    assert len(event.request_parameters["changeBatch"]["changes"]) == 2


def test_failed_call_is_dropped() -> None:
    raw = load_fixture("ec2", "AuthorizeSecurityGroupIngress")
    raw["detail"]["errorCode"] = "Client.UnauthorizedOperation"
    assert normalize(raw) is None


@pytest.mark.parametrize("missing", ["eventID", "eventName", "eventTime", "eventSource"])
def test_missing_required_field_raises(missing: str) -> None:
    raw = copy.deepcopy(load_fixture("ec2", "StopInstances"))
    del raw["detail"][missing]
    with pytest.raises(NormalizationError):
        normalize(raw)


def test_non_cloudtrail_event_raises() -> None:
    with pytest.raises(NormalizationError):
        normalize({"hello": "world"})


def test_bad_time_raises() -> None:
    raw = copy.deepcopy(load_fixture("ec2", "StopInstances"))
    raw["detail"]["eventTime"] = "not a time"
    with pytest.raises(NormalizationError):
        normalize(raw)


def test_top_level_console_flag_is_kept_in_identity() -> None:
    raw = copy.deepcopy(load_fixture("ec2", "StopInstances"))
    raw["detail"]["sessionCredentialFromConsole"] = "true"
    event = normalize(raw)
    assert event is not None
    assert event.user_identity["sessionCredentialFromConsole"] == "true"
