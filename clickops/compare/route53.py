"""Route 53 record name, type, TTL and values: live versus Terraform state."""

from __future__ import annotations

from typing import Any, cast

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, changed
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource


def split_record_id(record_id: str) -> tuple[str, str, str]:
    """(zone ID, name, type) from Terraform's ``ZONEID_name_TYPE``."""
    zone, rest = record_id.split("_", 1)
    name, record_type = rest.rsplit("_", 1)
    return zone, name, record_type


def _clean(name: str) -> str:
    return name.rstrip(".").lower().replace("\\052", "*")


def compare(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    zone, name, record_type = split_record_id(ref.id)
    client = boto3.client("route53", region_name="us-east-1")
    try:
        page = client.list_resource_record_sets(
            HostedZoneId=zone,
            StartRecordName=name,
            StartRecordType=cast(Any, record_type),
            MaxItems="5",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchHostedZone":
            return Comparison(exists=False)
        raise
    live = next(
        (
            r
            for r in page["ResourceRecordSets"]
            if _clean(r["Name"]) == name.lower() and r["Type"] == record_type
        ),
        None,
    )
    if live is None:
        return Comparison(exists=False)
    attrs = state.attributes
    changes = changed("name", _clean(str(attrs.get("name", name))), _clean(live["Name"]))
    changes += changed("type", attrs.get("type", record_type), live["Type"])
    changes += changed("ttl", attrs.get("ttl"), live.get("TTL"))
    changes += changed(
        "values",
        sorted(attrs.get("records") or []),
        sorted(r["Value"] for r in live.get("ResourceRecords", [])),
    )
    return Comparison(changes=changes)
