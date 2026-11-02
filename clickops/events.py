"""Turn an EventBridge "AWS API Call via CloudTrail" event into a NormalizedEvent."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from clickops.models import NormalizedEvent

# Lambda event names carry an API version, e.g. UpdateFunctionConfiguration20150331v2.
_VERSION_SUFFIX = re.compile(r"\d{8}(?:v\d+)?$")


class NormalizationError(ValueError):
    """The event is not a usable CloudTrail API call event."""


def base_event_name(name: str) -> str:
    """Strip a Lambda API-version suffix from an event name."""
    return _VERSION_SUFFIX.sub("", name)


def _required(detail: dict[str, Any], key: str) -> Any:
    value = detail.get(key)
    if value in (None, ""):
        raise NormalizationError(f"CloudTrail detail is missing {key}")
    return value


def normalize(raw: dict[str, Any]) -> NormalizedEvent | None:
    """Return the normalized event, or None for a call that failed.

    A call with an ``errorCode`` changed nothing, so it is dropped. Anything that is not a
    CloudTrail event, or lacks a required field, raises ``NormalizationError``.
    """
    detail = raw.get("detail")
    if not isinstance(detail, dict):
        raise NormalizationError("event has no CloudTrail detail")
    if detail.get("errorCode"):
        return None

    try:
        return NormalizedEvent(
            event_id=_required(detail, "eventID"),
            time=_required(detail, "eventTime"),
            source=_required(detail, "eventSource"),
            name=base_event_name(_required(detail, "eventName")),
            region=_required(detail, "awsRegion"),
            account=raw.get("account") or _required(detail, "recipientAccountId"),
            user_identity=detail.get("userIdentity") or {},
            request_parameters=detail.get("requestParameters") or {},
            response_elements=detail.get("responseElements") or {},
            error_code=None,
            source_ip=detail.get("sourceIPAddress"),
            user_agent=detail.get("userAgent"),
        )
    except ValidationError as exc:
        raise NormalizationError(f"invalid CloudTrail detail: {exc.error_count()} errors") from exc
