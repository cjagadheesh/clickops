"""CloudTrail and EventBridge events on clickops' own trail and rules."""

from __future__ import annotations

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import EVENT_RULE, TRAIL, param

TRAIL_EVENTS = {"StopLogging", "DeleteTrail", "UpdateTrail", "PutEventSelectors"}
RULE_EVENTS = {"DisableRule", "DeleteRule", "RemoveTargets"}


def trail_name(raw: str) -> str:
    """A trail name from a name or a trail ARN."""
    return raw.rsplit("trail/", 1)[-1]


def resolve_trail(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name not in TRAIL_EVENTS:
        return []
    raw = param(event, "name") or param(event, "trailName")  # PutEventSelectors says trailName
    if not raw:
        return []
    name = trail_name(raw)
    arn = f"arn:aws:cloudtrail:{event.region}:{event.account}:trail/{name}"
    return [ResourceRef(type=TRAIL, id=name, arn=arn, region=event.region)]


def resolve_rule(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name not in RULE_EVENTS:
        return []
    name = param(event, "name") or param(event, "rule")  # RemoveTargets names it "rule"
    if not name:
        return []
    arn = f"arn:aws:events:{event.region}:{event.account}:rule/{name}"
    return [ResourceRef(type=EVENT_RULE, id=name, arn=arn, region=event.region)]
