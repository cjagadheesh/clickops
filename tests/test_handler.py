import json
import logging
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from conftest import load_fixture
from moto import mock_aws

from clickops import handler, store
from clickops.compare.base import Comparison, FieldChange
from clickops.events import NormalizationError
from clickops.state import StateError

STATE = Path(__file__).resolve().parent / "fixtures" / "state" / "sandbox-state.json"


def reset_globals() -> None:
    handler._table = None
    handler._config = None
    handler._reader = None


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    for var in ("CLICKOPS_SELF_ROLE_ARN", "CLICKOPS_TRUSTED_ROLES", "CLICKOPS_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLICKOPS_STATE_LOCATIONS", "tfstate/sandbox/terraform.tfstate")
    reset_globals()
    with mock_aws():
        boto3.client("dynamodb").create_table(**store.TABLE_DEFINITION)
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        s3.put_object(Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=STATE.read_bytes())
        yield boto3.resource("dynamodb").Table(store.TABLE_NAME)
    reset_globals()


def drift(*args: Any, **kwargs: Any) -> Comparison:
    return Comparison(
        changes=[FieldChange("ingress", ["tcp 443-443 0.0.0.0/0"], ["tcp 22-22 10.0.0.0/8"])]
    )


@pytest.fixture
def canned_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handler, "compare", lambda event, ref, index: drift())


def items(table: Any) -> list[dict[str, Any]]:
    return sorted(table.scan()["Items"], key=lambda i: i["resource_key"])


def test_managed_drift_is_stored_with_diff_and_address(aws, canned_drift) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("ec2", "RevokeSecurityGroupIngress")
    result = handler.handler(raw, None)
    assert result["stored"] is True
    [item] = items(aws)
    assert item["resource_key"] == "sg#sg-0a1b2c3d4e5f60718"
    assert (item["outcome"], item["severity"]) == ("managed-drift", "warning")
    assert item["terraform_address"] == "aws_security_group.web"
    assert json.loads(item["diff"])["ingress"]["live"] == ["tcp 22-22 10.0.0.0/8"]
    assert item["actor_class"] == "cli-human" and item["actor_name"] == "asha@example.com"
    assert item["day"] == "2026-10-26"
    assert item["sk"] == f"2026-10-26T10:15:30Z#{raw['detail']['eventID']}"
    assert int(item["expires_at"]) > 0


def test_world_ssh_from_the_cli_is_critical(aws, canned_drift) -> None:  # type: ignore[no-untyped-def]
    handler.handler(load_fixture("ec2", "AuthorizeSecurityGroupIngress"), None)
    [item] = items(aws)
    assert (item["outcome"], item["severity"]) == ("managed-drift", "critical")
    assert "world" in item["reason"]


def test_deleting_a_managed_resource_is_critical_without_describe_calls(aws) -> None:  # type: ignore[no-untyped-def]
    handler.handler(load_fixture("ec2", "DeleteSecurityGroup"), None)
    [item] = items(aws)
    assert (item["outcome"], item["severity"]) == ("managed-delete", "critical")


def test_creating_an_unmanaged_resource_is_a_shadow_create(aws) -> None:  # type: ignore[no-untyped-def]
    handler.handler(load_fixture("s3", "CreateBucket"), None)
    [item] = items(aws)
    assert (item["outcome"], item["severity"]) == ("shadow-create", "info")
    assert "terraform_address" not in item


def test_ci_events_are_stored_as_ignored_without_reading_state(monkeypatch, aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name="ap-south-1").delete_object(
        Bucket="tfstate", Key="sandbox/terraform.tfstate"
    )  # reading state would now fail
    handler.handler(load_fixture("ec2", "AuthorizeSecurityGroupIngress.ci"), None)
    [item] = items(aws)
    assert (item["outcome"], item["severity"], item["actor_class"]) == ("ignored", "none", "ci")


def test_event_with_several_resources_stores_one_item_each(aws, canned_drift) -> None:  # type: ignore[no-untyped-def]
    handler.handler(load_fixture("ec2", "RunInstances"), None)
    stored = items(aws)
    assert [i["resource_key"] for i in stored] == [
        "ec2#i-0123456789abcdef0",
        "ec2#i-0fedcba9876543210",
    ]
    assert [i["outcome"] for i in stored] == ["managed-drift", "shadow-create"]


def test_unresolvable_events_are_stored_as_unresolved(aws) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("ec2", "StopInstances")
    raw["detail"]["eventName"] = "SomethingNew"
    handler.handler(raw, None)
    [item] = items(aws)
    assert item["resource_key"] == "unresolved#SomethingNew"
    assert (item["outcome"], item["severity"]) == ("unresolved", "none")


def test_retry_does_not_duplicate(aws) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("s3", "CreateBucket")
    assert handler.handler(raw, None)["stored"] is True
    assert handler.handler(raw, None)["stored"] is False
    assert len(items(aws)) == 1


def test_failed_call_is_not_stored(aws) -> None:  # type: ignore[no-untyped-def]
    raw = load_fixture("ec2", "StopInstances")
    raw["detail"]["errorCode"] = "Client.UnauthorizedOperation"
    assert handler.handler(raw, None) == {"stored": False, "reason": "failed-call"}
    assert items(aws) == []


def test_trusted_roles_from_the_environment_are_ci(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "CLICKOPS_TRUSTED_ROLES",
        "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/"
        "AWSReservedSSO_AdminAccess_0123456789abcdef",
    )
    handler.handler(load_fixture("ec2", "StopInstances"), None)
    assert items(aws)[0]["actor_class"] == "ci"


def test_config_file_overrides_severity_and_ignores(
    aws, monkeypatch, tmp_path, canned_drift
) -> None:  # type: ignore[no-untyped-def]
    cfg = tmp_path / "clickops.yaml"
    cfg.write_text(
        "state_locations:\n  - bucket: tfstate\n    key: sandbox/terraform.tfstate\n"
        "severity_overrides:\n  - outcome: shadow-create\n    severity: warning\n"
        "ignore:\n  - resource_type: aws_security_group\n    id_pattern: 'sg-0a1b*'\n"
        "    reason: scratch\n"
    )
    monkeypatch.setenv("CLICKOPS_CONFIG", str(cfg))
    handler.handler(load_fixture("s3", "CreateBucket"), None)
    handler.handler(load_fixture("ec2", "RevokeSecurityGroupIngress"), None)
    by_key = {i["resource_key"]: i for i in items(aws)}
    assert by_key["s3#clickops-scratch-111122223333"]["severity"] == "warning"
    assert by_key["sg#sg-0a1b2c3d4e5f60718"]["outcome"] == "ignored"
    assert by_key["sg#sg-0a1b2c3d4e5f60718"]["reason"] == "scratch"


# --- failures must raise so Lambda retries and then dead-letters the event ---------------------


def test_malformed_event_raises(aws) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NormalizationError):
        handler.handler({"detail": {"eventName": "X"}}, None)
    assert items(aws) == []


def throttle(*args: Any, **kwargs: Any) -> Comparison:
    raise ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Describe"
    )


def test_aws_throttling_raises_and_stores_nothing(aws, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(handler, "compare", throttle)
    with pytest.raises(ClientError, match="ThrottlingException"):
        handler.handler(load_fixture("ec2", "RevokeSecurityGroupIngress"), None)
    assert items(aws) == []


def test_unreadable_state_raises(aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name="ap-south-1").put_object(
        Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=b'{"version": 3}'
    )
    with pytest.raises(StateError):
        handler.handler(load_fixture("ec2", "RevokeSecurityGroupIngress"), None)


def test_missing_state_object_raises(aws) -> None:  # type: ignore[no-untyped-def]
    boto3.client("s3", region_name="ap-south-1").delete_object(
        Bucket="tfstate", Key="sandbox/terraform.tfstate"
    )
    with pytest.raises(ClientError):
        handler.handler(load_fixture("ec2", "RevokeSecurityGroupIngress"), None)


def test_logs_one_structured_json_line(aws, canned_drift, caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.INFO, logger="clickops"):
        handler.handler(load_fixture("ec2", "RevokeSecurityGroupIngress"), None)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == "clickops" and r.levelno == 20 and r.getMessage().startswith("{")
    ]
    messages = [json.loads(line) for line in lines]
    processed = [m for m in messages if m.get("msg") == "event processed"]
    assert len(processed) == 1
    assert processed[0]["findings"][0]["outcome"] == "managed-drift"
    assert "10.0.0.0/8" not in "\n".join(lines)  # no diff or state values in logs
