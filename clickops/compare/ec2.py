"""EC2 instance type, security groups, instance profile and run state: live versus state."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, changed, children_of
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource

_RUNNING = {"pending", "running"}
_STOPPED = {"stopping", "stopped"}
_GONE = {"shutting-down", "terminated"}


def run_state(name: str) -> str:
    """Collapse EC2 lifecycle states into running or stopped."""
    return "running" if name in _RUNNING else "stopped"


def _wanted_state(index: StateIndex, state: StateResource) -> str:
    managed = children_of(index, state, "aws_ec2_instance_state")
    if managed:
        return run_state(str(managed[0].attributes.get("state", "running")))
    return run_state(str(state.attributes.get("instance_state") or "running"))


def _state_groups(state: StateResource) -> list[str]:
    groups = state.attributes.get("vpc_security_group_ids") or state.attributes.get(
        "security_groups"
    )
    return sorted(groups or [])


def compare(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    ec2 = boto3.client("ec2", region_name=ref.region)
    try:
        reservations = ec2.describe_instances(InstanceIds=[ref.id])["Reservations"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {
            "InvalidInstanceID.NotFound",
            "InvalidInstanceID.Malformed",
        }:
            return Comparison(exists=False)
        raise
    instance: Any = reservations[0]["Instances"][0]
    if instance["State"]["Name"] in _GONE:
        return Comparison(exists=False)
    profile_arn = (instance.get("IamInstanceProfile") or {}).get("Arn", "")
    live_profile = profile_arn.rsplit("/", 1)[-1]
    changes = changed(
        "instance_type", state.attributes.get("instance_type"), instance["InstanceType"]
    )
    changes += changed(
        "security_group_ids",
        _state_groups(state),
        sorted(g["GroupId"] for g in instance.get("SecurityGroups", [])),
    )
    changes += changed(
        "instance_profile", state.attributes.get("iam_instance_profile") or "", live_profile
    )
    changes += changed(
        "run_state", _wanted_state(index, state), run_state(instance["State"]["Name"])
    )
    return Comparison(changes=changes)
