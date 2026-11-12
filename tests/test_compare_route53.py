import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import route53
from clickops.models import ResourceRef
from clickops.resolvers.base import ROUTE53_RECORD, find_in_state


@pytest.fixture
def zone(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("route53", region_name="us-east-1")
        zone_id = client.create_hosted_zone(Name="clickops.internal", CallerReference="x")[
            "HostedZone"
        ]["Id"].rsplit("/", 1)[-1]
        _upsert(client, zone_id, "app.clickops.internal", "A", 300, ["10.20.1.10"])
        _upsert(client, zone_id, "db.clickops.internal", "A", 300, ["10.20.1.20"])
        yield client, zone_id


def _upsert(client, zone_id, name, rtype, ttl, values, action="UPSERT"):  # type: ignore[no-untyped-def]
    client.change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": action,
                    "ResourceRecordSet": {
                        "Name": name,
                        "Type": rtype,
                        "TTL": ttl,
                        "ResourceRecords": [{"Value": v} for v in values],
                    },
                }
            ]
        },
    )


def _compare(zone_id: str, name: str = "app.clickops.internal", record_type: str = "A"):  # type: ignore[no-untyped-def]
    record_id = f"{zone_id}_{name}_{record_type}"
    index = index_of(
        resource("aws_route53_zone", "private", id=zone_id, zone_id=zone_id),
        resource(
            "aws_route53_record",
            "app",
            id=record_id,
            zone_id=zone_id,
            name="app.clickops.internal",
            type="A",
            ttl=300,
            records=["10.20.1.10"],
        ),
    )
    ref = ResourceRef(type=ROUTE53_RECORD, id=record_id)
    state = find_in_state(index, ref)
    assert state is not None
    return route53.compare(ref, index, state)


def test_split_record_id() -> None:
    assert route53.split_record_id("Z123_app.clickops.internal_A") == (
        "Z123",
        "app.clickops.internal",
        "A",
    )
    assert route53.split_record_id("Z123_my_host.example.com_TXT") == (
        "Z123",
        "my_host.example.com",
        "TXT",
    )


def test_matching_record_has_no_diff(zone) -> None:  # type: ignore[no-untyped-def]
    _, zone_id = zone
    result = _compare(zone_id)
    assert result.exists and not result.drifted


def test_changed_value_is_reported(zone) -> None:  # type: ignore[no-untyped-def]
    client, zone_id = zone
    _upsert(client, zone_id, "app.clickops.internal", "A", 300, ["10.20.1.99"])
    assert _compare(zone_id).diff() == {"values": {"state": ["10.20.1.10"], "live": ["10.20.1.99"]}}


def test_changed_ttl_is_reported(zone) -> None:  # type: ignore[no-untyped-def]
    client, zone_id = zone
    _upsert(client, zone_id, "app.clickops.internal", "A", 60, ["10.20.1.10"])
    assert _compare(zone_id).diff() == {"ttl": {"state": 300, "live": 60}}


def test_added_value_is_reported(zone) -> None:  # type: ignore[no-untyped-def]
    client, zone_id = zone
    _upsert(client, zone_id, "app.clickops.internal", "A", 300, ["10.20.1.10", "10.20.1.11"])
    assert _compare(zone_id).diff()["values"]["live"] == ["10.20.1.10", "10.20.1.11"]


def test_deleted_record_no_longer_exists(zone) -> None:  # type: ignore[no-untyped-def]
    client, zone_id = zone
    _upsert(client, zone_id, "app.clickops.internal", "A", 300, ["10.20.1.10"], action="DELETE")
    assert _compare(zone_id).exists is False


def test_missing_zone_means_the_record_no_longer_exists(zone) -> None:  # type: ignore[no-untyped-def]
    assert _compare("ZDOESNOTEXIST").exists is False


def test_record_type_is_matched(zone) -> None:  # type: ignore[no-untyped-def]
    client, zone_id = zone
    _upsert(client, zone_id, "app.clickops.internal", "TXT", 300, ['"hello"'])
    assert not _compare(zone_id).drifted  # the A record is still compared, not the TXT record
