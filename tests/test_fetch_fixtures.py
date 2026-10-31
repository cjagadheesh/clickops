import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_fixtures.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scrub_replaces_account_and_access_keys() -> None:
    mod = _load()
    text = "arn:aws:iam::999988887777:role/x key AKIAABCDEFGHIJKLMNOP"
    out = mod.scrub(text, "999988887777")
    assert "999988887777" not in out
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "111122223333" in out


def test_envelope_wraps_record_as_eventbridge_event() -> None:
    mod = _load()
    record = {
        "eventID": "e1",
        "recipientAccountId": "1",
        "eventTime": "2026-10-26T10:00:00Z",
        "awsRegion": "ap-south-1",
        "eventName": "StopInstances",
    }
    env = mod.envelope(record, "ec2")
    assert env["_source"] == "real"
    assert env["source"] == "aws.ec2"
    assert env["detail-type"] == "AWS API Call via CloudTrail"
    assert json.dumps(env["detail"]) == json.dumps(record)
