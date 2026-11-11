"""EC2 instance events to the instances they change (one ref per instance)."""

from __future__ import annotations

from typing import Any

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import EC2_INSTANCE, param

# Request carries the IDs for these; RunInstances only reveals them in the response.
REQUEST_EVENTS = {"TerminateInstances", "StartInstances", "StopInstances"}


def _instance_ids(container: Any) -> list[str]:
    items = (
        container.get("instancesSet", {}).get("items", []) if isinstance(container, dict) else []
    )
    return [i["instanceId"] for i in items if isinstance(i, dict) and i.get("instanceId")]


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name == "RunInstances":
        ids = _instance_ids(event.response_elements)
    elif event.name in REQUEST_EVENTS:
        ids = _instance_ids(event.request_parameters) or _instance_ids(event.response_elements)
    elif event.name == "ModifyInstanceAttribute":
        single = param(event, "instanceId")
        ids = [single] if single else []
    else:
        return []
    return [
        ResourceRef(
            type=EC2_INSTANCE,
            id=instance_id,
            arn=f"arn:aws:ec2:{event.region}:{event.account}:instance/{instance_id}",
            region=event.region,
        )
        for instance_id in dict.fromkeys(ids)
    ]
