"""Security group rules: live versus Terraform state."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, Gone, changed
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource

NOT_FOUND = {"InvalidGroup.NotFound", "InvalidGroupId.Malformed"}


def rule_text(protocol: Any, from_port: Any, to_port: Any, target: str) -> str:
    """One rule as ``tcp 22-22 0.0.0.0/0`` (``all`` for every protocol and port)."""
    proto = "all" if str(protocol) == "-1" else str(protocol)
    if proto == "all":
        return f"all {target}"
    return f"{proto} {from_port}-{to_port} {target}"


def _expand(attrs: dict[str, Any]) -> list[str]:
    """Rules from an inline ingress/egress block or a rule resource."""
    proto = attrs.get("ip_protocol", attrs.get("protocol", attrs.get("from_protocol")))
    low, high = attrs.get("from_port"), attrs.get("to_port")
    targets: list[str] = []
    for key in (
        "cidr_ipv4",
        "cidr_ipv6",
        "referenced_security_group_id",
        "prefix_list_id",
        "source_security_group_id",
        "cidr_blocks",
        "ipv6_cidr_blocks",
        "security_groups",
        "prefix_list_ids",
    ):
        value = attrs.get(key)
        if isinstance(value, str) and value:
            targets.append(value)
        elif isinstance(value, list):
            targets.extend(str(v) for v in value if v)
    if attrs.get("self"):
        targets.append("self")
    return [rule_text(proto, low, high, t) for t in targets]


def state_rules(index: StateIndex, state: StateResource) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {"ingress": [], "egress": []}
    for direction in rules:
        for block in state.attributes.get(direction) or []:
            rules[direction].extend(_expand(block))
    for child in index.children(state.type, state.id):
        if child.type == "aws_vpc_security_group_ingress_rule":
            rules["ingress"].extend(_expand(child.attributes))
        elif child.type == "aws_vpc_security_group_egress_rule":
            rules["egress"].extend(_expand(child.attributes))
        elif child.type == "aws_security_group_rule":
            direction = "egress" if child.attributes.get("type") == "egress" else "ingress"
            rules[direction].extend(_expand(child.attributes))
    return {k: sorted(set(v)) for k, v in rules.items()}


def _live_permissions(perms: Any, group_id: str) -> list[str]:
    out: list[str] = []
    for perm in perms:
        proto, low, high = perm.get("IpProtocol"), perm.get("FromPort"), perm.get("ToPort")
        targets = [r["CidrIp"] for r in perm.get("IpRanges", [])]
        targets += [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])]
        for pair in perm.get("UserIdGroupPairs", []):
            targets.append("self" if pair["GroupId"] == group_id else pair["GroupId"])
        targets += [p["PrefixListId"] for p in perm.get("PrefixListIds", [])]
        out.extend(rule_text(proto, low, high, t) for t in targets)
    return sorted(set(out))


def live_rules(ref: ResourceRef) -> dict[str, list[str]]:
    ec2 = boto3.client("ec2", region_name=ref.region)
    try:
        groups = ec2.describe_security_groups(GroupIds=[ref.id])["SecurityGroups"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] in NOT_FOUND:
            raise Gone from exc
        raise
    group = groups[0]
    return {
        "ingress": _live_permissions(group.get("IpPermissions", []), ref.id),
        "egress": _live_permissions(group.get("IpPermissionsEgress", []), ref.id),
    }


def _self_to_group(rules: dict[str, list[str]], group_id: str) -> dict[str, list[str]]:
    return {k: sorted(r.replace(group_id, "self") for r in v) for k, v in rules.items()}


def compare(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    want = _self_to_group(state_rules(index, state), ref.id)
    try:
        have = live_rules(ref)
    except Gone:
        return Comparison(exists=False)
    changes = changed("ingress", want["ingress"], have["ingress"])
    changes += changed("egress", want["egress"], have["egress"])
    return Comparison(changes=changes)


__all__ = ["compare", "live_rules", "state_rules"]
