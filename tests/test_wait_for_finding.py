import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import boto3
import pytest
from moto import mock_aws

from clickops import store

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wait_for_finding.py"
SINCE = datetime.now(UTC) - timedelta(minutes=2)


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wait_for_finding", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        boto3.client("dynamodb").create_table(**store.TABLE_DEFINITION)
        yield boto3.resource("dynamodb").Table(store.TABLE_NAME)


def put(table, when: datetime, **fields) -> None:  # type: ignore[no-untyped-def]
    base = {
        "event_name": "AuthorizeSecurityGroupIngress",
        "outcome": "managed-drift",
        "severity": "critical",
        "actor_name": "asha",
        "actor_class": "cli-human",
    }
    store.put_event(
        table,
        store.build_item(
            resource_key="sg#sg-1", event_id="e1", when=when, fields={**base, **fields}
        ),
    )


def test_finds_the_matching_item(table) -> None:  # type: ignore[no-untyped-def]
    module = load()
    put(table, datetime.now(UTC) - timedelta(minutes=1))
    item = module.find_item(table, SINCE, "sg#sg-1", "AuthorizeSecurityGroupIngress")
    assert item is not None and item["severity"] == "critical"
    assert module.find_item(table, SINCE, "sg#sg-2", "AuthorizeSecurityGroupIngress") is None
    assert module.find_item(table, SINCE, "sg#sg-1", "DeleteSecurityGroup") is None


def test_wait_polls_until_the_item_appears(table) -> None:  # type: ignore[no-untyped-def]
    module = load()
    now = {"t": 0.0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["t"] += seconds
        if len(sleeps) == 2:
            put(table, datetime.now(UTC) - timedelta(seconds=30))

    item, waited = module.wait(
        table,
        since=SINCE,
        resource="sg#sg-1",
        event="AuthorizeSecurityGroupIngress",
        interval=15,
        sleep=sleep,
        clock=lambda: now["t"],
    )
    assert item is not None and waited == 30 and sleeps == [15, 15]


def test_wait_times_out(table) -> None:  # type: ignore[no-untyped-def]
    module = load()
    now = {"t": 0.0}

    def sleep(seconds: float) -> None:
        now["t"] += seconds

    item, waited = module.wait(
        table,
        since=SINCE,
        resource="sg#sg-1",
        event="X",
        timeout=45,
        interval=15,
        sleep=sleep,
        clock=lambda: now["t"],
    )
    assert item is None and waited >= 45


def test_check_reports_unexpected_outcome_and_severity() -> None:
    module = load()
    item = {"outcome": "managed-drift", "severity": "warning"}
    assert module.check(item, "managed-drift", "warning") == []
    assert module.check(item, None, None) == []
    assert len(module.check(item, "managed-delete", "critical")) == 2


def test_main_prints_the_delay_and_exit_codes(table, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    module = load()
    put(table, datetime.now(UTC) - timedelta(seconds=20))
    argv = [
        "--resource",
        "sg#sg-1",
        "--event",
        "AuthorizeSecurityGroupIngress",
        "--since",
        SINCE.isoformat(),
        "--expect-outcome",
        "managed-drift",
        "--expect-severity",
        "critical",
    ]
    assert module.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["found"] and result["problems"] == [] and result["delay_seconds"] >= 120
    assert result["actor"] == "asha (cli-human)"
    assert module.main([*argv[:-1], "warning"]) == 1
    missing = [
        "--resource",
        "sg#nope",
        "--event",
        "X",
        "--since",
        SINCE.isoformat(),
        "--timeout",
        "0",
    ]
    assert module.main(missing) == 1


def test_label_and_append_write_a_result_line(table, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    module = load()
    put(table, datetime.now(UTC) - timedelta(seconds=10))
    results = tmp_path / "results.jsonl"
    argv = [
        "--resource",
        "sg#sg-1",
        "--event",
        "AuthorizeSecurityGroupIngress",
        "--since",
        SINCE.isoformat(),
        "--label",
        "SSH from the world",
        "--expect-severity",
        "critical",
        "--append",
        str(results),
    ]
    assert module.main(argv) == 0
    capsys.readouterr()
    line = json.loads(results.read_text())
    assert line["label"] == "SSH from the world" and line["found"] is True
    assert line["expect_severity"] == "critical" and line["problems"] == []


def test_a_timeout_is_recorded_as_a_failure(table, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    module = load()
    results = tmp_path / "results.jsonl"
    argv = [
        "--resource",
        "sg#nope",
        "--event",
        "X",
        "--since",
        SINCE.isoformat(),
        "--timeout",
        "0",
        "--label",
        "never",
        "--append",
        str(results),
        "--expect-severity",
        "critical",
    ]
    assert module.main(argv) == 1
    capsys.readouterr()
    line = json.loads(results.read_text())
    assert line["found"] is False and line["label"] == "never"
