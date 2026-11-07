"""Layout of the DynamoDB event log ``clickops-events`` and its key builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

TABLE_NAME = "clickops-events"
TTL_DAYS = 90
DAY_INDEX = "day-ts"

# Attribute names, shared with infra/detector/events_table.tf.
HASH_KEY = "resource_key"
RANGE_KEY = "sk"
DAY_ATTR = "day"
TS_ATTR = "ts"
TTL_ATTR = "expires_at"

TABLE_DEFINITION: dict[str, Any] = {
    "TableName": TABLE_NAME,
    "BillingMode": "PAY_PER_REQUEST",
    "KeySchema": [
        {"AttributeName": HASH_KEY, "KeyType": "HASH"},
        {"AttributeName": RANGE_KEY, "KeyType": "RANGE"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": HASH_KEY, "AttributeType": "S"},
        {"AttributeName": RANGE_KEY, "AttributeType": "S"},
        {"AttributeName": DAY_ATTR, "AttributeType": "S"},
        {"AttributeName": TS_ATTR, "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": DAY_INDEX,
            "KeySchema": [
                {"AttributeName": DAY_ATTR, "KeyType": "HASH"},
                {"AttributeName": TS_ATTR, "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
}


def utc_iso(when: datetime) -> str:
    """Timestamp in a sortable, fixed-width UTC form: 2026-10-26T10:15:30Z."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sort_key(when: datetime, event_id: str) -> str:
    return f"{utc_iso(when)}#{event_id}"


def day_of(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%d")


def expires_at(when: datetime, days: int = TTL_DAYS) -> int:
    """Epoch seconds after which DynamoDB may delete the item."""
    return int((when.astimezone(UTC) + timedelta(days=days)).timestamp())


def build_item(
    *,
    resource_key: str,
    event_id: str,
    when: datetime,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """A DynamoDB item with the key, day, timestamp and TTL attributes filled in."""
    return {
        HASH_KEY: resource_key,
        RANGE_KEY: sort_key(when, event_id),
        DAY_ATTR: day_of(when),
        TS_ATTR: utc_iso(when),
        TTL_ATTR: expires_at(when),
        "event_id": event_id,
        **{k: v for k, v in fields.items() if v is not None},
    }


def put_event(table: Any, item: dict[str, Any]) -> bool:
    """Write an item once. Returns False when this event was already stored (a Lambda retry)."""
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#sk)",
            ExpressionAttributeNames={"#sk": RANGE_KEY},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def query_since(table: Any, since: datetime, until: datetime | None = None) -> list[dict[str, Any]]:
    """Events from ``since`` up to ``until``, oldest first, read through the day index."""
    end = until or datetime.now(UTC)
    start_ts = utc_iso(since)
    end_ts = utc_iso(end)
    items: list[dict[str, Any]] = []
    day = since.astimezone(UTC).date()
    last_day = end.astimezone(UTC).date()
    while day <= last_day:
        kwargs: dict[str, Any] = {
            "IndexName": DAY_INDEX,
            "KeyConditionExpression": "#d = :d AND #t BETWEEN :from AND :to",
            "ExpressionAttributeNames": {"#d": DAY_ATTR, "#t": TS_ATTR},
            "ExpressionAttributeValues": {
                ":d": day.isoformat(),
                ":from": start_ts,
                ":to": end_ts,
            },
        }
        while True:
            page = table.query(**kwargs)
            items.extend(page["Items"])
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        day += timedelta(days=1)
    return sorted(items, key=lambda i: (i[TS_ATTR], i[RANGE_KEY]))
