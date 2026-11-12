"""Shared pieces for comparators: the result type and policy normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from clickops.models import NormalizedEvent, ResourceRef
from clickops.state import StateIndex, StateResource


@dataclass(frozen=True)
class FieldChange:
    field: str
    state: Any
    live: Any


@dataclass
class Comparison:
    """Outcome of comparing live configuration with Terraform state for one resource."""

    exists: bool = True
    changes: list[FieldChange] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return bool(self.changes)

    def diff(self) -> dict[str, dict[str, Any]]:
        """Field-level diff in the shape stored on a Finding."""
        return {c.field: {"state": c.state, "live": c.live} for c in self.changes}


class Gone(Exception):
    """The resource no longer exists in AWS."""


def changed(name: str, state: Any, live: Any) -> list[FieldChange]:
    return [] if state == live else [FieldChange(name, state, live)]


_LIST_KEYS = {"Action", "NotAction", "Resource", "NotResource"}
_PRINCIPAL_KEYS = {"Principal", "NotPrincipal"}


def _as_list(value: Any) -> list[Any]:
    items = value if isinstance(value, list) else [value]
    return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))


def _norm(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        out = {k: _norm(v, k) for k, v in value.items()}
        return out
    if key in _LIST_KEYS and not isinstance(value, dict):
        return _as_list(value)
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def normalize_policy(document: Any) -> Any:
    """A canonical form of an IAM or bucket policy for comparison.

    Parses JSON text, treats a single string and a one-item list as equal for actions, resources
    and principals, and orders statements and list values, so key and statement order don't matter.
    """
    if document in (None, ""):
        return None
    if isinstance(document, str):
        document = json.loads(document)
    doc = _norm(document)
    statements = doc.get("Statement") if isinstance(doc, dict) else None
    if statements is not None:
        statements = statements if isinstance(statements, list) else [statements]
        statements = [_norm_statement(s) for s in statements]
        doc["Statement"] = sorted(statements, key=lambda s: json.dumps(s, sort_keys=True))
    return doc


def _norm_statement(statement: dict[str, Any]) -> dict[str, Any]:
    out = dict(statement)
    for key in _PRINCIPAL_KEYS & out.keys():
        principal = out[key]
        if isinstance(principal, dict):
            out[key] = {k: _as_list(v) for k, v in principal.items()}
        elif principal == "*":
            out[key] = {"AWS": ["*"]}
    return out


def children_of(index: StateIndex, state: StateResource, child_type: str) -> list[StateResource]:
    return [c for c in index.children(state.type, state.id) if c.type == child_type]


__all__ = [
    "Comparison",
    "FieldChange",
    "Gone",
    "NormalizedEvent",
    "ResourceRef",
    "changed",
    "children_of",
    "normalize_policy",
]
