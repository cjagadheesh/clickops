from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from clickops import status, store
from clickops.cli import app

REGION = "ap-south-1"
NOW = datetime.now(UTC)


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A healthy moto account: trail logging, four enabled rules, an empty queue, no alarms."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(
            Bucket="trail-logs", CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        trail = boto3.client("cloudtrail", region_name=REGION)
        trail.create_trail(Name="clickops-trail", S3BucketName="trail-logs")
        trail.start_logging(Name="clickops-trail")
        for region, rule in status.RULES:
            boto3.client("events", region_name=region).put_rule(
                Name=rule, EventPattern='{"source": ["aws.ec2"]}', State="ENABLED"
            )
        boto3.client("sqs", region_name=REGION).create_queue(QueueName="clickops-detector-dlq")
        boto3.client("dynamodb", region_name=REGION).create_table(**store.TABLE_DEFINITION)
        yield


def rows() -> dict[str, status.StatusRow]:
    return {r.name: r for r in status.collect(REGION, now=NOW)}


def put_event(when: datetime, event_id: str = "e1") -> None:
    table = boto3.resource("dynamodb", region_name=REGION).Table(store.TABLE_NAME)
    store.put_event(
        table,
        store.build_item(
            resource_key="sg#sg-1",
            event_id=event_id,
            when=when,
            fields={"event_name": "AuthorizeSecurityGroupIngress"},
        ),
    )


def test_a_healthy_account_passes_every_check(account) -> None:  # type: ignore[no-untyped-def]
    result = rows()
    assert len(result) == 8
    assert all(r.ok for r in result.values()), result
    assert result["CloudTrail logging"].detail == "clickops-trail is logging"
    assert result["Alarms"].detail == "none open"
    assert result["Dead-letter queue"].detail == "0 message(s) waiting"


def test_a_stopped_trail_is_a_problem(account) -> None:  # type: ignore[no-untyped-def]
    boto3.client("cloudtrail", region_name=REGION).stop_logging(Name="clickops-trail")
    row = rows()["CloudTrail logging"]
    assert not row.ok and "NOT logging" in row.detail


def test_a_missing_trail_is_a_problem(account) -> None:  # type: ignore[no-untyped-def]
    boto3.client("cloudtrail", region_name=REGION).delete_trail(Name="clickops-trail")
    assert not rows()["CloudTrail logging"].ok


def test_disabled_and_missing_rules_are_problems(account) -> None:  # type: ignore[no-untyped-def]
    boto3.client("events", region_name=REGION).disable_rule(Name="clickops-tamper")
    boto3.client("events", region_name="us-east-1").delete_rule(Name="clickops-forward-global")
    result = rows()
    assert result["Rule clickops-tamper (ap-south-1)"].detail == "disabled"
    assert not result["Rule clickops-tamper (ap-south-1)"].ok
    assert result["Rule clickops-forward-global (us-east-1)"].detail == "missing"
    assert result["Rule clickops-regional (ap-south-1)"].ok


def test_messages_in_the_dead_letter_queue_are_a_problem(account) -> None:  # type: ignore[no-untyped-def]
    sqs = boto3.client("sqs", region_name=REGION)
    url = sqs.get_queue_url(QueueName="clickops-detector-dlq")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="stuck")
    row = rows()["Dead-letter queue"]
    assert not row.ok and row.detail == "1 message(s) waiting"


def test_open_alarms_are_listed(account) -> None:  # type: ignore[no-untyped-def]
    cw = boto3.client("cloudwatch", region_name=REGION)
    cw.put_metric_alarm(
        AlarmName="clickops-detector-errors",
        MetricName="Errors",
        Namespace="AWS/Lambda",
        Statistic="Sum",
        Period=300,
        EvaluationPeriods=1,
        Threshold=0,
        ComparisonOperator="GreaterThanThreshold",
    )
    cw.set_alarm_state(AlarmName="clickops-detector-errors", StateValue="ALARM", StateReason="test")
    cw.put_metric_alarm(
        AlarmName="someone-elses",
        MetricName="Errors",
        Namespace="AWS/Lambda",
        Statistic="Sum",
        Period=300,
        EvaluationPeriods=1,
        Threshold=0,
        ComparisonOperator="GreaterThanThreshold",
    )
    cw.set_alarm_state(AlarmName="someone-elses", StateValue="ALARM", StateReason="test")
    row = rows()["Alarms"]
    assert not row.ok and row.detail == "open: clickops-detector-errors"


def test_last_event_time_and_age(account) -> None:  # type: ignore[no-untyped-def]
    assert "none in the last 7 days" in rows()["Last stored event"].detail
    put_event(NOW - timedelta(minutes=30), "old")
    put_event(NOW - timedelta(minutes=5), "newer")
    row = rows()["Last stored event"]
    assert row.ok and "5 min ago" in row.detail and "AuthorizeSecurityGroupIngress" in row.detail


def test_last_event_looks_back_across_days_and_ignores_alert_counters(account) -> None:  # type: ignore[no-untyped-def]
    table = boto3.resource("dynamodb", region_name=REGION).Table(store.TABLE_NAME)
    table.put_item(Item={"resource_key": "alert#x", "sk": "window", "window_start": 1})
    assert store.last_event(table, NOW) is None
    put_event(NOW - timedelta(days=3), "three-days-ago")
    item = store.last_event(table, NOW)
    assert item is not None and item["event_id"] == "three-days-ago"
    assert store.last_event(table, NOW + timedelta(days=30)) is None


def test_missing_event_table_is_reported(account) -> None:  # type: ignore[no-untyped-def]
    missing = boto3.resource("dynamodb", region_name=REGION).Table("nope")
    row = status.check_last_event(missing, NOW)
    assert not row.ok and "cannot read" in row.detail


def test_status_command_prints_a_table_and_exit_code(account) -> None:  # type: ignore[no-untyped-def]
    ok = CliRunner().invoke(app, ["status"], env={"COLUMNS": "200"})
    assert ok.exit_code == 0, ok.output
    assert "CloudTrail logging" in ok.output and "problem" not in ok.output
    boto3.client("cloudtrail", region_name=REGION).stop_logging(Name="clickops-trail")
    bad = CliRunner().invoke(app, ["status"], env={"COLUMNS": "200"})
    assert bad.exit_code == 1 and "NOT logging" in bad.output and "problem" in bad.output


def test_readme_lists_the_tamper_outcome_and_the_status_command() -> None:
    from pathlib import Path

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "| `tamper` |" in readme and "`StopLogging`" in readme
    assert "clickops status" in readme
    for outcome in ("managed-drift", "managed-delete", "shadow-create", "ignored"):
        assert f"`{outcome}`" in readme
