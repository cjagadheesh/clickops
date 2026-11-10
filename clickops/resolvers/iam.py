"""IAM events to the role or policy they change."""

from __future__ import annotations

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import IAM_POLICY, IAM_ROLE, param, response

ROLE_EVENTS = {
    "CreateRole",
    "DeleteRole",
    "UpdateAssumeRolePolicy",
    "PutRolePolicy",
    "DeleteRolePolicy",
    "AttachRolePolicy",
    "DetachRolePolicy",
}


def _role(event: NormalizedEvent) -> list[ResourceRef]:
    name = param(event, "roleName")
    if not name:
        return []
    # Role ARNs include a path, which only CreateRole's response reveals.
    arn = response(event, "role", "arn") or f"arn:aws:iam::{event.account}:role/{name}"
    return [ResourceRef(type=IAM_ROLE, id=name, arn=arn, region=event.region)]


def _policy(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name == "CreatePolicy":
        arn = response(event, "policy", "arn")
    else:
        arn = param(event, "policyArn")
    if not arn:
        return []
    return [ResourceRef(type=IAM_POLICY, id=arn, arn=arn, region=event.region)]


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    """Role calls resolve to the role (attach and detach change the role, not the policy)."""
    if event.name in ROLE_EVENTS:
        return _role(event)
    if event.name in {"CreatePolicy", "CreatePolicyVersion"}:
        return _policy(event)
    return []
