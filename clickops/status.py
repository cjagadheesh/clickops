"""``clickops status``: is the detector's own plumbing healthy?"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops import store

TRAIL = "clickops-trail"
DLQ = "clickops-detector-dlq"
ALARM_PREFIX = "clickops-"
HOME_REGION = "ap-south-1"
# (region, rule name): the three rules in the home region and the forwarder in us-east-1.
RULES = [
    (HOME_REGION, "clickops-regional"),
    (HOME_REGION, "clickops-global"),
    (HOME_REGION, "clickops-tamper"),
    ("us-east-1", "clickops-forward-global"),
]


@dataclass(frozen=True)
class StatusRow:
    name: str
    ok: bool
    detail: str


def _code(exc: ClientError) -> str:
    return str(exc.response["Error"]["Code"])


def check_trail(region: str) -> StatusRow:
    name = "CloudTrail logging"
    try:
        status = boto3.client("cloudtrail", region_name=region).get_trail_status(Name=TRAIL)
    except ClientError as exc:
        return StatusRow(name, False, f"{TRAIL}: {_code(exc)}")
    logging_on = bool(status.get("IsLogging"))
    return StatusRow(name, logging_on, f"{TRAIL} is {'logging' if logging_on else 'NOT logging'}")


def check_rule(region: str, rule: str) -> StatusRow:
    name = f"Rule {rule} ({region})"
    try:
        state = boto3.client("events", region_name=region).describe_rule(Name=rule)["State"]
    except ClientError as exc:
        return StatusRow(
            name, False, "missing" if _code(exc) == "ResourceNotFoundException" else _code(exc)
        )
    return StatusRow(name, state == "ENABLED", state.lower())


def check_last_event(table: Any, now: datetime) -> StatusRow:
    name = "Last stored event"
    try:
        item = store.last_event(table, now)
    except ClientError as exc:
        return StatusRow(name, False, f"cannot read {store.TABLE_NAME}: {_code(exc)}")
    if item is None:
        return StatusRow(name, True, "none in the last 7 days (a quiet account is fine)")
    when = datetime.strptime(str(item["ts"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    minutes = int((now - when).total_seconds() // 60)
    return StatusRow(name, True, f"{item['ts']} ({minutes} min ago): {item.get('event_name', '?')}")


def check_dlq(region: str) -> StatusRow:
    name = "Dead-letter queue"
    sqs = boto3.client("sqs", region_name=region)
    try:
        url = sqs.get_queue_url(QueueName=DLQ)["QueueUrl"]
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
    except ClientError as exc:
        return StatusRow(name, False, f"{DLQ}: {_code(exc)}")
    depth = int(attrs.get("ApproximateNumberOfMessages", 0)) + int(
        attrs.get("ApproximateNumberOfMessagesNotVisible", 0)
    )
    return StatusRow(name, depth == 0, f"{depth} message(s) waiting")


def check_alarms(region: str) -> StatusRow:
    name = "Alarms"
    try:
        alarms = boto3.client("cloudwatch", region_name=region).describe_alarms(
            AlarmNamePrefix=ALARM_PREFIX, StateValue="ALARM"
        )["MetricAlarms"]
    except ClientError as exc:
        return StatusRow(name, False, _code(exc))
    if not alarms:
        return StatusRow(name, True, "none open")
    return StatusRow(name, False, "open: " + ", ".join(sorted(a["AlarmName"] for a in alarms)))


def collect(
    region: str = HOME_REGION, table: Any = None, now: datetime | None = None
) -> list[StatusRow]:
    now = now or datetime.now(UTC)
    table = table or boto3.resource("dynamodb", region_name=region).Table(store.TABLE_NAME)
    return [
        check_trail(region),
        *(check_rule(rule_region, rule) for rule_region, rule in RULES),
        check_last_event(table, now),
        check_dlq(region),
        check_alarms(region),
    ]
