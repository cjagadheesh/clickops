from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from clickops import store

EVENTS_TF = Path(__file__).resolve().parent.parent / "infra" / "detector" / "events_table.tf"
WHEN = datetime(2026, 10, 26, 10, 15, 30, tzinfo=UTC)


def test_key_builders() -> None:
    assert store.sort_key(WHEN, "e1") == "2026-10-26T10:15:30Z#e1"
    assert store.day_of(WHEN) == "2026-10-26"
    assert store.expires_at(WHEN) == int(WHEN.timestamp()) + 90 * 86400


def test_keys_use_utc_whatever_the_input_zone() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 10, 26, 3, 0, 0, tzinfo=ist)  # 2026-10-25 21:30 UTC
    assert store.day_of(local) == "2026-10-25"
    assert store.utc_iso(local) == "2026-10-25T21:30:00Z"


def test_sort_keys_order_by_time() -> None:
    later = WHEN + timedelta(seconds=1)
    assert store.sort_key(WHEN, "z") < store.sort_key(later, "a")


def test_terraform_table_matches_python_schema() -> None:
    tf = EVENTS_TF.read_text()
    assert f'name         = "{store.TABLE_NAME}"' in tf
    assert 'billing_mode = "PAY_PER_REQUEST"' in tf
    for attr in (store.HASH_KEY, store.RANGE_KEY, store.DAY_ATTR, store.TS_ATTR):
        assert f'name = "{attr}"' in tf
    assert f'hash_key     = "{store.HASH_KEY}"' in tf
    assert f'range_key    = "{store.RANGE_KEY}"' in tf
    assert f'name            = "{store.DAY_INDEX}"' in tf
    assert f'attribute_name = "{store.TTL_ATTR}"' in tf


@mock_aws
def test_table_definition_supports_event_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    ddb = boto3.client("dynamodb", region_name="ap-south-1")
    ddb.create_table(**store.TABLE_DEFINITION)
    for i, ev in enumerate(("e1", "e2")):
        when = WHEN + timedelta(minutes=i)
        ddb.put_item(
            TableName=store.TABLE_NAME,
            Item={
                store.HASH_KEY: {"S": "sg#sg-0abc"},
                store.RANGE_KEY: {"S": store.sort_key(when, ev)},
                store.DAY_ATTR: {"S": store.day_of(when)},
                store.TS_ATTR: {"S": store.utc_iso(when)},
                store.TTL_ATTR: {"N": str(store.expires_at(when))},
            },
        )
    by_resource = ddb.query(
        TableName=store.TABLE_NAME,
        KeyConditionExpression="resource_key = :r",
        ExpressionAttributeValues={":r": {"S": "sg#sg-0abc"}},
    )
    assert [i[store.RANGE_KEY]["S"][-2:] for i in by_resource["Items"]] == ["e1", "e2"]
    by_day = ddb.query(
        TableName=store.TABLE_NAME,
        IndexName=store.DAY_INDEX,
        KeyConditionExpression="#d = :d AND ts >= :t",
        ExpressionAttributeNames={"#d": "day"},
        ExpressionAttributeValues={":d": {"S": "2026-10-26"}, ":t": {"S": "2026-10-26T10:16:00Z"}},
    )
    assert by_day["Count"] == 1
