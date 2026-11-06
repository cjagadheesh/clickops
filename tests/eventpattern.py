"""A small EventBridge event-pattern matcher (exact values and prefix) for offline tests."""

from __future__ import annotations

from typing import Any


def _value_matches(rule: Any, value: Any) -> bool:
    if isinstance(rule, dict):
        if "prefix" in rule:
            return isinstance(value, str) and value.startswith(rule["prefix"])
        raise NotImplementedError(f"unsupported operator: {rule}")
    return bool(rule == value)


def matches(pattern: dict[str, Any], event: dict[str, Any]) -> bool:
    """True when every field in the pattern is satisfied by the event."""
    for key, rule in pattern.items():
        if key not in event:
            return False
        value = event[key]
        if isinstance(rule, dict):
            if not isinstance(value, dict) or not matches(rule, value):
                return False
        else:
            candidates = value if isinstance(value, list) else [value]
            if not any(_value_matches(r, c) for r in rule for c in candidates):
                return False
    return True
