"""Lambda entry point: normalize, classify, resolve, compare, decide and store."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import boto3

from clickops import resolvers, store
from clickops.actors import classify
from clickops.compare import compare
from clickops.config import Config, StateLocation, load_config
from clickops.events import normalize
from clickops.models import Actor, Finding, NormalizedEvent, Outcome, Severity
from clickops.resolvers.base import find_in_state
from clickops.rules import SKIPPED_ACTORS, decide
from clickops.state import StateReader

logger = logging.getLogger("clickops")
logger.setLevel(logging.INFO)

TABLE_ENV = "CLICKOPS_TABLE"
TRUSTED_ROLES_ENV = "CLICKOPS_TRUSTED_ROLES"
STATE_LOCATIONS_ENV = "CLICKOPS_STATE_LOCATIONS"
CONFIG_ENV = "CLICKOPS_CONFIG"
DEFAULT_CONFIG_PATH = "/var/task/clickops.yaml"

# Kept in the Lambda's global scope between invocations.
_table: Any = None
_config: Config | None = None
_reader: StateReader | None = None


def _get_table() -> Any:
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ.get(TABLE_ENV, store.TABLE_NAME))
    return _table


def _env_locations() -> list[StateLocation]:
    """State files from ``bucket/key,bucket/key`` in the environment."""
    locations = []
    for entry in os.environ.get(STATE_LOCATIONS_ENV, "").split(","):
        bucket, _, key = entry.strip().partition("/")
        if bucket and key:
            locations.append(StateLocation(bucket=bucket, key=key))
    return locations


def _get_config() -> Config:
    """``clickops.yaml`` when one is bundled, otherwise settings from the environment."""
    global _config
    if _config is None:
        path = Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH))
        _config = load_config(path) if path.is_file() else Config(state_locations=_env_locations())
    return _config


def _get_reader() -> StateReader:
    global _reader
    if _reader is None:
        _reader = StateReader(_get_config().state_locations)
    return _reader


def _trusted_roles() -> list[str]:
    env = [r.strip() for r in os.environ.get(TRUSTED_ROLES_ENV, "").split(",") if r.strip()]
    return [*_get_config().trusted_roles, *env]


def _log(**fields: Any) -> None:
    logger.info(json.dumps(fields, sort_keys=True, default=str))


def _findings(event: NormalizedEvent, actor: Actor) -> list[tuple[Finding, str, str | None]]:
    """One (finding, reason, state address) per changed resource."""
    refs = resolvers.resolve(event)
    if not refs:
        finding = Finding(
            event=event, actor=actor, outcome=Outcome.UNRESOLVED, severity=Severity.NONE
        )
        return [(finding, "no resource could be resolved from the event", None)]

    config = _get_config()
    # Machine actors are ignored whatever they changed, so state is not read for them.
    index = None if actor.actor_class in SKIPPED_ACTORS else _get_reader().load()
    results = []
    for ref in refs:
        state = find_in_state(index, ref) if index is not None else None
        comparison = compare(event, ref, index) if index is not None else None
        decision = decide(event, actor, ref, state, comparison, config)
        diff = comparison.diff() if comparison and decision.outcome is Outcome.MANAGED_DRIFT else {}
        finding = Finding(
            event=event,
            actor=actor,
            resource=ref,
            outcome=decision.outcome,
            severity=decision.severity,
            diff=diff,
        )
        results.append((finding, decision.reason, state.address if state else None))
    return results


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Process one CloudTrail event and store a finding for each resource it changed.

    A malformed event, a bad state file or an AWS error (throttling, access denied) raises, so
    Lambda retries the invocation and then sends it to the dead-letter queue.
    """
    normalized = normalize(event)
    if normalized is None:
        _log(msg="dropped failed call", event_id=(event.get("detail") or {}).get("eventID"))
        return {"stored": False, "reason": "failed-call"}

    actor = classify(normalized, _trusted_roles())
    results = _findings(normalized, actor)
    table = _get_table()
    summary = []
    for finding, reason, address in results:
        stored = store.put_event(table, store.finding_item(finding, reason, address))
        summary.append(
            {
                "resource": finding.resource.key if finding.resource else None,
                "outcome": finding.outcome.value,
                "severity": finding.severity.value,
                "stored": stored,
            }
        )
    _log(
        msg="event processed",
        event_id=normalized.event_id,
        event_name=normalized.name,
        actor_class=actor.actor_class.value,
        actor=actor.display_name,
        findings=summary,
    )
    return {
        "stored": any(s["stored"] for s in summary),
        "event_id": normalized.event_id,
        "findings": summary,
    }
