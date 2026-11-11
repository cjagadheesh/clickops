"""Route 53 events to the zone or records they change."""

from __future__ import annotations

from typing import Any

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import ROUTE53_RECORD, ROUTE53_ZONE, param, response


def _zone_id(raw: str) -> str:
    return raw.rsplit("/", 1)[-1]


def record_id(zone_id: str, name: str, record_type: str) -> str:
    """Terraform's import ID for a record: ZONEID_name_TYPE, name without the trailing dot."""
    return f"{zone_id}_{name.rstrip('.').lower()}_{record_type.upper()}"


def _zone_ref(event: NormalizedEvent, zone_id: str) -> ResourceRef:
    arn = f"arn:aws:route53:::hostedzone/{zone_id}"
    return ResourceRef(type=ROUTE53_ZONE, id=zone_id, arn=arn, region=event.region)


def _records(event: NormalizedEvent, zone_id: str) -> list[ResourceRef]:
    batch: Any = event.request_parameters.get("changeBatch")
    changes = batch.get("changes", []) if isinstance(batch, dict) else []
    refs: dict[str, ResourceRef] = {}
    for change in changes:
        record_set = change.get("resourceRecordSet") if isinstance(change, dict) else None
        if not isinstance(record_set, dict):
            continue
        name, record_type = record_set.get("name"), record_set.get("type")
        if not name or not record_type:
            continue
        ident = record_id(zone_id, name, record_type)
        refs[ident] = ResourceRef(type=ROUTE53_RECORD, id=ident, region=event.region)
    return list(refs.values())


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name == "ChangeResourceRecordSets":
        zone = param(event, "hostedZoneId")
        return _records(event, _zone_id(zone)) if zone else []
    if event.name == "CreateHostedZone":
        zone = response(event, "hostedZone", "id")
    elif event.name == "DeleteHostedZone":
        zone = param(event, "id")
    else:
        return []
    return [_zone_ref(event, _zone_id(zone))] if zone else []
