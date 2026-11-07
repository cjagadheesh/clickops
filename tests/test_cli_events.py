import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from clickops import store
from clickops.cli import app, parse_duration


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-south-1").create_table(**store.TABLE_DEFINITION)
        yield boto3.resource("dynamodb", region_name="ap-south-1").Table(store.TABLE_NAME)


def _put(table, when: datetime, event_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
    item = store.build_item(
        resource_key=fields.pop("resource_key", "sg#sg-0abc"),
        event_id=event_id,
        when=when,
        fields={
            "event_name": "AuthorizeSecurityGroupIngress",
            "actor_name": "asha",
            "actor_class": "cli-human",
            "outcome": "managed-drift",
            "severity": "warning",
            **fields,
        },
    )
    store.put_event(table, item)


@pytest.mark.parametrize(
    ("text", "delta"),
    [("30m", timedelta(minutes=30)), ("1h", timedelta(hours=1)), ("2D", timedelta(days=2))],
)
def test_parse_duration(text: str, delta: timedelta) -> None:
    assert parse_duration(text) == delta


@pytest.mark.parametrize("text", ["", "h", "1", "1w", "-1h", "0h", "1.5h"])
def test_parse_duration_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


def test_query_since_spans_days_and_orders_oldest_first(table) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 10, 27, 0, 30, tzinfo=UTC)
    _put(table, datetime(2026, 10, 26, 23, 50, tzinfo=UTC), "a")
    _put(table, datetime(2026, 10, 27, 0, 10, tzinfo=UTC), "b")
    _put(table, datetime(2026, 10, 26, 20, 0, tzinfo=UTC), "too-old")
    items = store.query_since(table, now - timedelta(hours=1), now)
    assert [i["event_id"] for i in items] == ["a", "b"]


def test_query_since_excludes_future_events(table) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 10, 27, 0, 30, tzinfo=UTC)
    _put(table, now + timedelta(minutes=5), "future")
    assert store.query_since(table, now - timedelta(hours=1), now) == []


def test_events_command_prints_table(table) -> None:  # type: ignore[no-untyped-def]
    _put(table, datetime.now(UTC) - timedelta(minutes=5), "e1", severity="critical")
    result = CliRunner().invoke(app, ["events", "--since", "1h"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "AuthorizeSecurityGroupIngress" in result.output
    assert "asha" in result.output
    assert "critical" in result.output
    assert "sg#sg-0abc" in result.output


def test_events_command_json_and_empty(table) -> None:  # type: ignore[no-untyped-def]
    empty = CliRunner().invoke(app, ["events", "--since", "30m"])
    assert "No events in the last 30m" in empty.output
    _put(table, datetime.now(UTC) - timedelta(minutes=1), "e2")
    out = CliRunner().invoke(app, ["events", "--since", "1h", "--json"])
    assert json.loads(out.output)[0]["event_id"] == "e2"


def test_events_command_rejects_bad_since(table) -> None:  # type: ignore[no-untyped-def]
    result = CliRunner().invoke(app, ["events", "--since", "soon"])
    assert result.exit_code != 0
