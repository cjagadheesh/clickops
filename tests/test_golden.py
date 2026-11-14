"""Replay every fixture through the full pipeline and compare the stored items with golden JSON.

Live comparisons are canned here (every managed, non-deleted resource has drifted) because the
comparators are tested against moto in test_compare_*.py; this checks the wiring and the rules.
Regenerate the expected files with ``UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py``.
"""

import json
import os
from pathlib import Path
from typing import Any

import boto3
import pytest
from conftest import fixture_paths
from moto import mock_aws

from clickops import compare as compare_pkg
from clickops import handler, store
from clickops.compare.base import Comparison, FieldChange

TESTS = Path(__file__).resolve().parent
STATE = TESTS / "fixtures" / "state" / "sandbox-state.json"
GOLDEN = TESTS / "golden"


def canned(*args: Any) -> Comparison:
    return Comparison(changes=[FieldChange("drift", "as coded", "changed by hand")])


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    for var in ("CLICKOPS_SELF_ROLE_ARN", "CLICKOPS_TRUSTED_ROLES", "CLICKOPS_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLICKOPS_SELF_ROLE_ARN", "arn:aws:iam::111122223333:role/clickops-detector")
    monkeypatch.setenv("CLICKOPS_STATE_LOCATIONS", "tfstate/sandbox/terraform.tfstate")
    for key in list(compare_pkg.COMPARATORS):
        monkeypatch.setitem(compare_pkg.COMPARATORS, key, canned)
    handler._table = handler._config = handler._reader = handler._notifier = None
    with mock_aws():
        boto3.client("dynamodb").create_table(**store.TABLE_DEFINITION)
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        s3.put_object(Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=STATE.read_bytes())
        yield boto3.resource("dynamodb").Table(store.TABLE_NAME)
    handler._table = handler._config = handler._reader = handler._notifier = None


def stored(table: Any) -> list[dict[str, Any]]:
    items = [
        json.loads(json.dumps(i, default=int))
        for i in table.scan()["Items"]
        if i["sk"] != "window"  # alert dedup rows share the table
    ]
    return sorted(items, key=lambda i: i["resource_key"])


def golden_path(fixture: Path) -> Path:
    return GOLDEN / fixture.parent.name / fixture.name


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_fixture_matches_golden(pipeline, path: Path) -> None:  # type: ignore[no-untyped-def]
    handler.handler(json.loads(path.read_text()), None)
    actual = stored(pipeline)
    expected_file = golden_path(path)
    if os.environ.get("UPDATE_GOLDEN"):
        expected_file.parent.mkdir(parents=True, exist_ok=True)
        expected_file.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
    assert expected_file.exists(), f"missing golden file {expected_file}"
    assert actual == json.loads(expected_file.read_text())


def test_no_stale_golden_files() -> None:
    fixtures = {golden_path(p) for p in fixture_paths()}
    assert set(GOLDEN.rglob("*.json")) == fixtures
