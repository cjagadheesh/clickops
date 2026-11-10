"""Security group events to the group they change."""

from __future__ import annotations

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import SG, param, response

# Rule-level calls and ModifySecurityGroupRules carry the parent group's ID, so they resolve to it.
GROUP_EVENTS = {
    "DeleteSecurityGroup",
    "AuthorizeSecurityGroupIngress",
    "AuthorizeSecurityGroupEgress",
    "RevokeSecurityGroupIngress",
    "RevokeSecurityGroupEgress",
    "ModifySecurityGroupRules",
}


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name == "CreateSecurityGroup":
        group_id = response(event, "groupId")
    elif event.name in GROUP_EVENTS:
        group_id = param(event, "groupId")
    else:
        return []
    if not group_id:
        return []
    arn = f"arn:aws:ec2:{event.region}:{event.account}:security-group/{group_id}"
    return [ResourceRef(type=SG, id=group_id, arn=arn, region=event.region)]
