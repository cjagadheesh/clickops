"""Classify who made a call, in the fixed order from the spec."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from clickops.models import Actor, ActorClass, NormalizedEvent

SELF_ROLE_ENV = "CLICKOPS_SELF_ROLE_ARN"
CI_ROLE_NAME = "clickops-ci"
SSO_PREFIX = "AWSReservedSSO_"


def _role_key(arn: str) -> tuple[str, str] | None:
    """(account, role name) for an IAM role ARN or an STS assumed-role ARN, ignoring the path."""
    parts = arn.split(":", 5)
    if len(parts) != 6 or parts[2] not in {"iam", "sts"}:
        return None
    resource = parts[5]
    if resource.startswith("assumed-role/"):
        segments = resource.split("/")
        return (parts[4], segments[1]) if len(segments) >= 3 else None
    if resource.startswith("role/"):
        return parts[4], resource.rsplit("/", 1)[-1]
    return None


def _session_issuer_arn(identity: dict[str, Any]) -> str | None:
    issuer = (identity.get("sessionContext") or {}).get("sessionIssuer") or {}
    arn = issuer.get("arn")
    return arn if isinstance(arn, str) else None


def _role_keys(identity: dict[str, Any]) -> set[tuple[str, str]]:
    keys = set()
    for arn in (_session_issuer_arn(identity), identity.get("arn")):
        if isinstance(arn, str) and (key := _role_key(arn)):
            keys.add(key)
    return keys


def _matches_role(identity: dict[str, Any], role_arn: str) -> bool:
    wanted = _role_key(role_arn)
    return wanted is not None and wanted in _role_keys(identity)


def _is_ci(identity: dict[str, Any], trusted_roles: Iterable[str]) -> bool:
    if any(name == CI_ROLE_NAME for _, name in _role_keys(identity)):
        return True
    return any(_matches_role(identity, arn) for arn in trusted_roles)


def _is_aws_service(identity: dict[str, Any]) -> bool:
    if identity.get("type") == "AWSService" or identity.get("invokedBy"):
        return True
    issuer = _session_issuer_arn(identity) or ""
    return ":role/aws-service-role/" in issuer


def _from_console(identity: dict[str, Any]) -> bool:
    attributes = (identity.get("sessionContext") or {}).get("attributes") or {}
    flag = identity.get(
        "sessionCredentialFromConsole", attributes.get("sessionCredentialFromConsole")
    )
    return str(flag).lower() == "true"


def _display_name(identity: dict[str, Any], event: NormalizedEvent) -> str:
    kind = identity.get("type")
    if kind == "Root":
        return "root"
    if kind == "IAMUser" and identity.get("userName"):
        return str(identity["userName"])
    if kind == "AWSService":
        return str(identity.get("invokedBy") or event.source)
    if identity.get("invokedBy"):
        return str(identity["invokedBy"])
    arn = identity.get("arn")
    if isinstance(arn, str) and ":assumed-role/" in arn:
        # For Identity Center roles (AWSReservedSSO_*) the session name is the person's login.
        return arn.rsplit("/", 1)[-1]
    if isinstance(arn, str) and arn:
        return arn.rsplit("/", 1)[-1]
    return str(identity.get("principalId") or "unknown")


def classify(
    event: NormalizedEvent,
    trusted_roles: Iterable[str] = (),
    self_role_arn: str | None = None,
) -> Actor:
    """Return the actor class and a display name for the event's caller.

    Order: clickops-self, ci, aws-service, console-human, cli-human. The detector's own role comes
    from ``self_role_arn`` or the ``CLICKOPS_SELF_ROLE_ARN`` environment variable.
    """
    identity = event.user_identity
    own_role = self_role_arn if self_role_arn is not None else os.environ.get(SELF_ROLE_ENV)

    if own_role and _matches_role(identity, own_role):
        actor_class = ActorClass.CLICKOPS_SELF
    elif _is_ci(identity, trusted_roles):
        actor_class = ActorClass.CI
    elif _is_aws_service(identity):
        actor_class = ActorClass.AWS_SERVICE
    elif _from_console(identity):
        actor_class = ActorClass.CONSOLE_HUMAN
    else:
        actor_class = ActorClass.CLI_HUMAN

    arn = identity.get("arn")
    return Actor(
        actor_class=actor_class,
        display_name=_display_name(identity, event),
        arn=arn if isinstance(arn, str) else None,
    )
