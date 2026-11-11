"""Lambda events to the function they change."""

from __future__ import annotations

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import LAMBDA_FUNCTION, param, response

# Version suffixes (20150331, v2) are already stripped from the event name.
FUNCTION_EVENTS = {
    "CreateFunction",
    "DeleteFunction",
    "UpdateFunctionConfiguration",
    "UpdateFunctionCode",
    "AddPermission",
}


def function_name(raw: str) -> str:
    """Bare function name from a name, a partial ARN, a full ARN or a name:qualifier."""
    name = raw.split(":function:", 1)[1] if ":function:" in raw else raw
    return name.split(":", 1)[0]


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name not in FUNCTION_EVENTS:
        return []
    raw = response(event, "functionName") if event.name == "CreateFunction" else None
    raw = raw or param(event, "functionName")
    if not raw:
        return []
    name = function_name(raw)
    arn = f"arn:aws:lambda:{event.region}:{event.account}:function:{name}"
    return [ResourceRef(type=LAMBDA_FUNCTION, id=name, arn=arn, region=event.region)]
