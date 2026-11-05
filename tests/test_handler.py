import json
import logging

import boto3
import pytest
from conftest import fixture_paths, load_fixture
from moto import mock_aws

from clickops import handler, store
from clickops.events import NormalizationError


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.delenv("CLICKOPS_SELF_ROLE_ARN", raising=False)
    monkeypatch.delenv("CLICKOPS_TRUSTED_ROLES", raising=False)
    handler._table = None
    with mock_aws():
        boto3.client("dynamodb").create_table(**store.TABLE_DEFINITION)
        yield boto3.resource("dynamodb").Table(store.TABLE_NAME)
    handler._table = None


def test_stores_event_as_unresolved(table) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("ec2", "AuthorizeSecurityGroupIngress")
    result = handler.handler(raw, None)
    assert result["stored"] is True
    items = table.scan()["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["outcome"] == "unresolved"
    assert item["severity"] == "none"
    assert item["event_name"] == "AuthorizeSecurityGroupIngress"
    assert item["actor_class"] == "cli-human"
    assert item["actor_name"] == "asha@example.com"
    assert item["day"] == "2026-10-26"
    assert item["sk"] == f"2026-10-26T10:15:30Z#{raw['detail']['eventID']}"
    assert int(item["expires_at"]) > 0


def test_console_actor_is_recorded(table) -> None:  # type: ignore[no-untyped-def]
    handler.handler(load_fixture("iam", "AttachRolePolicy.console"), None)
    assert table.scan()["Items"][0]["actor_class"] == "console-human"


def test_trusted_roles_come_from_environment(table, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "CLICKOPS_TRUSTED_ROLES",
        "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/"
        "AWSReservedSSO_AdminAccess_0123456789abcdef",
    )
    handler.handler(load_fixture("ec2", "StopInstances"), None)
    assert table.scan()["Items"][0]["actor_class"] == "ci"


def test_retry_does_not_duplicate(table) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("s3", "CreateBucket")
    assert handler.handler(raw, None)["stored"] is True
    assert handler.handler(raw, None)["stored"] is False
    assert table.scan()["Count"] == 1


def test_failed_call_is_not_stored(table) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("ec2", "StopInstances")
    raw["detail"]["errorCode"] = "Client.UnauthorizedOperation"
    assert handler.handler(raw, None) == {"stored": False, "reason": "failed-call"}
    assert table.scan()["Count"] == 0


def test_malformed_event_raises_for_retry_and_dlq(table) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NormalizationError):
        handler.handler({"detail": {"eventName": "X"}}, None)


def test_logs_one_structured_json_line(table, caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="clickops"):
        handler.handler(load_fixture("lambda", "UpdateFunctionConfiguration20150331v2"), None)
    lines = [r.getMessage() for r in caplog.records if r.name == "clickops"]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["event_name"] == "UpdateFunctionConfiguration"
    assert data["outcome"] == "unresolved"
    assert data["stored"] is True


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_fixture_is_stored(table, path) -> None:  # type: ignore[no-untyped-def]
    assert handler.handler(json.loads(path.read_text()), None)["stored"] is True
