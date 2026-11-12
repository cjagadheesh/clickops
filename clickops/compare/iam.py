"""IAM roles and managed policies: live versus Terraform state."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, changed, children_of, normalize_policy
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource


def _state_inline(index: StateIndex, state: StateResource) -> dict[str, Any]:
    policies: dict[str, Any] = {}
    for child in children_of(index, state, "aws_iam_role_policy"):
        name = child.attributes.get("name") or child.id.split(":", 1)[-1]
        policies[name] = normalize_policy(child.attributes.get("policy"))
    for block in state.attributes.get("inline_policy") or []:
        if block.get("name"):
            policies[block["name"]] = normalize_policy(block.get("policy"))
    return policies


def _state_attached(index: StateIndex, state: StateResource) -> list[str]:
    arns = {
        c.attributes["policy_arn"]
        for c in children_of(index, state, "aws_iam_role_policy_attachment")
        if c.attributes.get("policy_arn")
    }
    arns.update(state.attributes.get("managed_policy_arns") or [])
    return sorted(arns)


def _missing(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "NoSuchEntity"


def compare_role(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    iam = boto3.client("iam", region_name="us-east-1")
    try:
        role = iam.get_role(RoleName=ref.id)["Role"]
        inline_names = iam.list_role_policies(RoleName=ref.id)["PolicyNames"]
        inline = {
            name: normalize_policy(
                iam.get_role_policy(RoleName=ref.id, PolicyName=name)["PolicyDocument"]
            )
            for name in inline_names
        }
        attached = iam.list_attached_role_policies(RoleName=ref.id)["AttachedPolicies"]
    except ClientError as exc:
        if _missing(exc):
            return Comparison(exists=False)
        raise
    changes = changed(
        "trust_policy",
        normalize_policy(state.attributes.get("assume_role_policy")),
        normalize_policy(role.get("AssumeRolePolicyDocument")),
    )
    changes += changed("inline_policies", _state_inline(index, state), inline)
    changes += changed(
        "attached_policy_arns",
        _state_attached(index, state),
        sorted(p["PolicyArn"] for p in attached),
    )
    return Comparison(changes=changes)


def compare_policy(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    iam = boto3.client("iam", region_name="us-east-1")
    try:
        version = iam.get_policy(PolicyArn=ref.id)["Policy"]["DefaultVersionId"]
        live = iam.get_policy_version(PolicyArn=ref.id, VersionId=version)["PolicyVersion"]
    except ClientError as exc:
        if _missing(exc):
            return Comparison(exists=False)
        raise
    return Comparison(
        changes=changed(
            "policy_document",
            normalize_policy(state.attributes.get("policy")),
            normalize_policy(live["Document"]),
        )
    )


__all__ = ["compare_policy", "compare_role"]
