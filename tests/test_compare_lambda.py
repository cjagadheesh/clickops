import base64
import hashlib
import io
import zipfile
from typing import Any

import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import lambda_fn
from clickops.models import ResourceRef
from clickops.resolvers.base import LAMBDA_FUNCTION, find_in_state

ROLE = "arn:aws:iam::123456789012:role/app"
OTHER_ROLE = "arn:aws:iam::123456789012:role/other"


def _zip(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.py", body)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


CODE = _zip("def handler(event, context):\n    return 1\n")


@pytest.fixture
def lam(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        iam = boto3.client("iam", region_name="us-east-1")
        for name in ("app", "other"):
            iam.create_role(RoleName=name, AssumeRolePolicyDocument="{}")
        client = boto3.client("lambda", region_name="ap-south-1")
        client.create_function(
            FunctionName="hello",
            Runtime="python3.12",
            Role=ROLE,
            Handler="hello.handler",
            Code={"ZipFile": CODE},
            MemorySize=128,
            Timeout=10,
            Environment={"Variables": {"GREETING": "secret-value-1"}},
        )
        yield client


def _compare():  # type: ignore[no-untyped-def]
    attrs: dict[str, Any] = {
        "id": "hello",
        "function_name": "hello",
        "runtime": "python3.12",
        "role": ROLE,
        "handler": "hello.handler",
        "memory_size": 128,
        "timeout": 10,
        "source_code_hash": _sha(CODE),
        "environment": [{"variables": {"GREETING": "secret-value-1"}}],
    }
    index = index_of(resource("aws_lambda_function", "hello", **attrs))
    ref = ResourceRef(type=LAMBDA_FUNCTION, id="hello", region="ap-south-1")
    state = find_in_state(index, ref)
    assert state is not None
    return lambda_fn.compare(ref, index, state)


def test_matching_function_has_no_diff(lam) -> None:  # type: ignore[no-untyped-def]
    result = _compare()
    assert result.exists and not result.drifted


@pytest.mark.parametrize(
    ("update", "field", "state", "live"),
    [
        ({"Runtime": "python3.11"}, "runtime", "python3.12", "python3.11"),
        ({"Handler": "other.handler"}, "handler", "hello.handler", "other.handler"),
        ({"MemorySize": 512}, "memory_size", 128, 512),
        ({"Timeout": 60}, "timeout", 10, 60),
        ({"Role": OTHER_ROLE}, "role", ROLE, OTHER_ROLE),
    ],
)
def test_each_configuration_attribute_is_compared(lam, update, field, state, live) -> None:  # type: ignore[no-untyped-def]
    lam.update_function_configuration(FunctionName="hello", **update)
    assert _compare().diff() == {field: {"state": state, "live": live}}


def test_changed_code_is_reported_by_hash(lam) -> None:  # type: ignore[no-untyped-def]
    new = _zip("def handler(event, context):\n    return 2\n")
    lam.update_function_code(FunctionName="hello", ZipFile=new)
    assert _compare().diff() == {"code_sha256": {"state": _sha(CODE), "live": _sha(new)}}


def test_environment_changes_report_names_only(lam) -> None:  # type: ignore[no-untyped-def]
    lam.update_function_configuration(
        FunctionName="hello",
        Environment={"Variables": {"GREETING": "changed-value", "EXTRA": "super-secret"}},
    )
    result = _compare()
    assert result.diff() == {
        "environment_variable_names": {"state": ["GREETING"], "live": ["EXTRA", "GREETING"]}
    }
    assert "super-secret" not in repr(result)
    assert "changed-value" not in repr(result)


def test_changed_value_of_an_existing_variable_is_not_reported(lam) -> None:  # type: ignore[no-untyped-def]
    lam.update_function_configuration(
        FunctionName="hello", Environment={"Variables": {"GREETING": "different"}}
    )
    assert not _compare().drifted


def test_deleted_function_no_longer_exists(lam) -> None:  # type: ignore[no-untyped-def]
    lam.delete_function(FunctionName="hello")
    assert _compare().exists is False
