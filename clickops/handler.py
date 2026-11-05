"""Lambda entry point: normalize, classify and store one CloudTrail event."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from clickops import store
from clickops.actors import classify
from clickops.events import normalize
from clickops.models import Outcome, Severity

logger = logging.getLogger("clickops")
logger.setLevel(logging.INFO)

TABLE_ENV = "CLICKOPS_TABLE"
TRUSTED_ROLES_ENV = "CLICKOPS_TRUSTED_ROLES"

_table: Any = None


def _get_table() -> Any:
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ.get(TABLE_ENV, store.TABLE_NAME))
    return _table


def _trusted_roles() -> list[str]:
    return [r.strip() for r in os.environ.get(TRUSTED_ROLES_ENV, "").split(",") if r.strip()]


def _log(**fields: Any) -> None:
    logger.info(json.dumps(fields, sort_keys=True, default=str))


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Store the event with outcome ``unresolved`` (resource matching arrives later).

    A malformed event raises, so Lambda retries it and then sends it to the DLQ.
    """
    normalized = normalize(event)
    if normalized is None:
        _log(msg="dropped failed call", event_id=(event.get("detail") or {}).get("eventID"))
        return {"stored": False, "reason": "failed-call"}

    actor = classify(normalized, _trusted_roles())
    item = store.build_item(
        resource_key=f"unresolved#{normalized.name}",
        event_id=normalized.event_id,
        when=normalized.time,
        fields={
            "event_name": normalized.name,
            "event_source": normalized.source,
            "region": normalized.region,
            "account": normalized.account,
            "actor_class": actor.actor_class.value,
            "actor_name": actor.display_name,
            "actor_arn": actor.arn,
            "source_ip": normalized.source_ip,
            "user_agent": normalized.user_agent,
            "outcome": Outcome.UNRESOLVED.value,
            "severity": Severity.NONE.value,
        },
    )
    stored = store.put_event(_get_table(), item)
    _log(
        msg="event processed",
        event_id=normalized.event_id,
        event_name=normalized.name,
        actor_class=actor.actor_class.value,
        actor=actor.display_name,
        outcome=Outcome.UNRESOLVED.value,
        stored=stored,
    )
    return {"stored": stored, "event_id": normalized.event_id}
