"""Outcome and severity: spec tables, critical overrides, opt-outs and config overrides."""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from clickops.compare.base import Comparison
from clickops.config import Config
from clickops.models import Actor, ActorClass, NormalizedEvent, Outcome, ResourceRef, Severity
from clickops.resolvers.base import STATE_TYPES
from clickops.state import StateResource

IGNORE_TAG = "clickops:ignore"
SAFE_WORLD_PORTS = {80, 443}
WORLD_CIDRS = {"0.0.0.0/0", "::/0"}

DEFAULT_SEVERITY = {
    Outcome.MANAGED_DRIFT: Severity.WARNING,
    Outcome.MANAGED_DELETE: Severity.CRITICAL,
    Outcome.SHADOW_CREATE: Severity.INFO,
    Outcome.IGNORED: Severity.NONE,
}

CREATE_EVENTS = {
    "CreateSecurityGroup",
    "CreateRole",
    "CreatePolicy",
    "CreateBucket",
    "RunInstances",
    "CreateFunction",
    "CreateHostedZone",
}
_SKIPPED_ACTORS = {ActorClass.CLICKOPS_SELF, ActorClass.CI, ActorClass.AWS_SERVICE}
_WRITE_VERBS = (
    "put",
    "create",
    "delete",
    "update",
    "attach",
    "detach",
    "modify",
    "set",
    "add",
    "remove",
    "run",
    "start",
    "stop",
    "terminate",
    "tag",
    "untag",
    "write",
    "invoke",
    "pass",
    "change",
    "authorize",
    "revoke",
    "associate",
    "disassociate",
    "enable",
    "disable",
    "reboot",
)


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    severity: Severity
    reason: str


# --- tags -------------------------------------------------------------------------------------


def _collect_tags(node: Any, found: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in {"tags", "tagset"}:
                _read_tag_container(value, found)
            _collect_tags(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_tags(item, found)


def _read_tag_container(value: Any, found: dict[str, str]) -> None:
    if isinstance(value, dict):
        if "items" in value:
            _read_tag_container(value["items"], found)
        elif {"key", "value"} <= {k.lower() for k in value}:
            lowered = {k.lower(): v for k, v in value.items()}
            found[str(lowered["key"])] = str(lowered["value"])
        else:
            found.update({str(k): str(v) for k, v in value.items() if isinstance(v, str)})
    elif isinstance(value, list):
        for item in value:
            _read_tag_container(item, found)


def request_tags(event: NormalizedEvent) -> dict[str, str]:
    """Tags set by the request itself (create calls)."""
    found: dict[str, str] = {}
    _collect_tags(event.request_parameters, found)
    return found


def _state_tags(state: StateResource | None) -> dict[str, str]:
    if state is None:
        return {}
    tags: dict[str, str] = {}
    for key in ("tags", "tags_all"):
        value = state.attributes.get(key)
        if isinstance(value, dict):
            tags.update({str(k): str(v) for k, v in value.items()})
    return tags


def opted_out(event: NormalizedEvent, state: StateResource | None) -> bool:
    tags = {**request_tags(event), **_state_tags(state)}
    return tags.get(IGNORE_TAG, "").lower() == "true"


def _config_ignored(ref: ResourceRef, config: Config | None) -> str | None:
    if config is None:
        return None
    state_type = STATE_TYPES.get(ref.type)
    for rule in config.ignore:
        if rule.resource_type is None and rule.id_pattern is None:
            continue
        if rule.resource_type and rule.resource_type not in {ref.type, state_type}:
            continue
        if rule.id_pattern and not fnmatch.fnmatch(ref.id, rule.id_pattern):
            continue
        return rule.reason or "ignored by clickops.yaml"
    return None


# --- creation ---------------------------------------------------------------------------------


def _record_created(event: NormalizedEvent, ref: ResourceRef) -> bool:
    batch = event.request_parameters.get("changeBatch")
    changes = batch.get("changes", []) if isinstance(batch, dict) else []
    for change in changes:
        record = change.get("resourceRecordSet", {}) if isinstance(change, dict) else {}
        name, rtype = str(record.get("name", "")).rstrip(".").lower(), record.get("type", "")
        if ref.id.endswith(f"_{name}_{str(rtype).upper()}") and change.get("action") in {
            "CREATE",
            "UPSERT",
        }:
            return True
    return False


def is_creation(event: NormalizedEvent, ref: ResourceRef) -> bool:
    if event.name == "ChangeResourceRecordSets":
        return _record_created(event, ref)
    return event.name in CREATE_EVENTS


# --- critical overrides -----------------------------------------------------------------------


def _port_exposed(protocol: Any, low: Any, high: Any) -> bool:
    if str(protocol) in {"-1", "all"} or low in (None, -1) or high in (None, -1):
        return True
    return not (low == high and low in SAFE_WORLD_PORTS)


def exposes_world(rules: Iterable[tuple[Any, Any, Any, str]]) -> bool:
    """True if any (protocol, from port, to port, cidr) opens a port other than 80 or 443."""
    return any(cidr in WORLD_CIDRS and _port_exposed(p, lo, hi) for p, lo, hi, cidr in rules)


_RULE_TEXT = re.compile(r"^(?P<proto>\S+)(?: (?P<low>-?\d+)-(?P<high>-?\d+))? (?P<cidr>\S+)$")


def _parse_rule_text(text: str) -> tuple[Any, Any, Any, str] | None:
    match = _RULE_TEXT.match(text)
    if not match:
        return None
    low = int(match["low"]) if match["low"] is not None else None
    high = int(match["high"]) if match["high"] is not None else None
    return match["proto"], low, high, match["cidr"]


def _added_ingress(comparison: Comparison | None) -> list[tuple[Any, Any, Any, str]]:
    rules = []
    for change in comparison.changes if comparison else []:
        if change.field == "ingress":
            for text in set(change.live or []) - set(change.state or []):
                parsed = _parse_rule_text(text)
                if parsed:
                    rules.append(parsed)
    return rules


def _requested_ingress(event: NormalizedEvent) -> list[tuple[Any, Any, Any, str]]:
    if event.name != "AuthorizeSecurityGroupIngress":
        return []
    perms = event.request_parameters.get("ipPermissions", {})
    rules = []
    for perm in perms.get("items", []) if isinstance(perms, dict) else []:
        for rng in (perm.get("ipRanges") or {}).get("items", []):
            rules.append(
                (
                    perm.get("ipProtocol"),
                    perm.get("fromPort"),
                    perm.get("toPort"),
                    rng.get("cidrIp", ""),
                )
            )
        for rng in (perm.get("ipv6Ranges") or {}).get("items", []):
            rules.append(
                (
                    perm.get("ipProtocol"),
                    perm.get("fromPort"),
                    perm.get("toPort"),
                    rng.get("cidrIpv6", ""),
                )
            )
    return rules


def _is_write_action(action: str) -> bool:
    if action == "*":
        return True
    name = action.split(":", 1)[-1]
    return name == "*" or name.lower().startswith(_WRITE_VERBS)


def policy_is_dangerous(document: Any) -> bool:
    """An Allow with Action or Resource ``*`` together with a write action."""
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except ValueError:
            return False
    statements = document.get("Statement", []) if isinstance(document, dict) else []
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
            continue
        actions = _as_list(statement.get("Action"))
        resources = _as_list(statement.get("Resource"))
        wildcard = "*" in actions or "*" in resources
        if wildcard and any(_is_write_action(a) for a in actions):
            return True
    return False


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def _policy_documents(event: NormalizedEvent, comparison: Comparison | None) -> list[Any]:
    docs: list[Any] = []
    if event.name in {"PutRolePolicy", "CreatePolicy", "CreatePolicyVersion"}:
        docs.append(event.request_parameters.get("policyDocument"))
    for change in comparison.changes if comparison else []:
        if change.field == "policy_document":
            docs.append(change.live)
        elif change.field == "inline_policies" and isinstance(change.live, dict):
            state = change.state if isinstance(change.state, dict) else {}
            docs.extend(doc for name, doc in change.live.items() if doc != state.get(name))
    return [d for d in docs if d]


def _public_access_blocked_off(event: NormalizedEvent, comparison: Comparison | None) -> bool:
    if event.name == "DeleteBucketPublicAccessBlock":
        return True
    if event.name == "PutBucketPublicAccessBlock":
        config = event.request_parameters.get("PublicAccessBlockConfiguration") or {}
        flags = (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
        if any(config.get(flag) is not True for flag in flags):
            return True
    return any(
        c.field.startswith("public_access_block.") and c.live is False
        for c in (comparison.changes if comparison else [])
    )


def critical_reason(event: NormalizedEvent, comparison: Comparison | None) -> str | None:
    if exposes_world(_requested_ingress(event)) or exposes_world(_added_ingress(comparison)):
        return "ingress from the world on a port other than 80 or 443"
    if any(policy_is_dangerous(d) for d in _policy_documents(event, comparison)):
        return "IAM policy with a wildcard and a write action"
    if _public_access_blocked_off(event, comparison):
        return "S3 Block Public Access disabled"
    return None


# --- decision ---------------------------------------------------------------------------------


def _override(outcome: Outcome, ref: ResourceRef, config: Config | None) -> Severity | None:
    if config is None:
        return None
    state_type = STATE_TYPES.get(ref.type)
    matches = [o for o in config.severity_overrides if o.outcome is outcome]
    specific = [o for o in matches if o.resource_type in {ref.type, state_type}]
    chosen = specific or [o for o in matches if o.resource_type is None]
    return chosen[0].severity if chosen else None


def decide(
    event: NormalizedEvent,
    actor: Actor,
    ref: ResourceRef,
    state: StateResource | None,
    comparison: Comparison | None,
    config: Config | None = None,
) -> Decision:
    """Outcome and severity for one changed resource."""
    if actor.actor_class in _SKIPPED_ACTORS:
        return Decision(Outcome.IGNORED, Severity.NONE, f"actor is {actor.actor_class.value}")
    if opted_out(event, state):
        return Decision(Outcome.IGNORED, Severity.NONE, f"tagged {IGNORE_TAG}=true")
    if (reason := _config_ignored(ref, config)) is not None:
        return Decision(Outcome.IGNORED, Severity.NONE, reason)

    if state is None:
        if not is_creation(event, ref):
            return Decision(Outcome.IGNORED, Severity.NONE, "resource is not managed by Terraform")
        outcome, why = Outcome.SHADOW_CREATE, "created outside Terraform"
    elif comparison is None or not comparison.exists:
        outcome, why = Outcome.MANAGED_DELETE, "Terraform-managed resource was deleted"
    elif comparison.drifted:
        outcome, why = Outcome.MANAGED_DRIFT, "live configuration differs from Terraform state"
    else:
        return Decision(Outcome.IGNORED, Severity.NONE, "live configuration matches state")

    severity = DEFAULT_SEVERITY[outcome]
    if (critical := critical_reason(event, comparison)) is not None:
        severity, why = Severity.CRITICAL, f"{why}; {critical}"
    elif (override := _override(outcome, ref, config)) is not None:
        severity = override
    return Decision(outcome, severity, why)
