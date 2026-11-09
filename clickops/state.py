"""Terraform state reader: S3 state files to an index by type and ID and by ARN.

State files can hold secrets. Nothing here logs or prints attribute values, only addresses and
IDs, and ``StateResource.attributes`` is left out of ``repr``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import boto3

from clickops.config import StateLocation

logger = logging.getLogger("clickops")

SUPPORTED_VERSION = 4

# Child resource type -> (attribute holding the parent's ID, parent resource type).
PARENT_LINKS: dict[str, tuple[str, str]] = {
    "aws_vpc_security_group_ingress_rule": ("security_group_id", "aws_security_group"),
    "aws_vpc_security_group_egress_rule": ("security_group_id", "aws_security_group"),
    "aws_security_group_rule": ("security_group_id", "aws_security_group"),
    "aws_iam_role_policy": ("role", "aws_iam_role"),
    "aws_iam_role_policy_attachment": ("role", "aws_iam_role"),
    "aws_lambda_permission": ("function_name", "aws_lambda_function"),
    "aws_ec2_instance_state": ("instance_id", "aws_instance"),
    "aws_route53_record": ("zone_id", "aws_route53_zone"),
}
_S3_CONFIG_PREFIX = "aws_s3_bucket_"


class StateError(Exception):
    """A state file is unreadable or not in a supported format."""


@dataclass(frozen=True)
class StateResource:
    type: str
    address: str
    id: str
    arn: str | None = None
    parent: tuple[str, str] | None = None  # (type, id) of the owning resource
    attributes: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.type, self.id


def _parent_link(resource_type: str) -> tuple[str, str] | None:
    if resource_type in PARENT_LINKS:
        return PARENT_LINKS[resource_type]
    if resource_type.startswith(_S3_CONFIG_PREFIX):
        return "bucket", "aws_s3_bucket"
    return None


def _address(resource: dict[str, Any], index_key: Any) -> str:
    base = f"{resource['type']}.{resource['name']}"
    if resource.get("module"):
        base = f"{resource['module']}.{base}"
    return f"{base}[{index_key!r}]" if index_key is not None else base


def parse_state(state: dict[str, Any]) -> list[StateResource]:
    """Managed resources from one decoded state file."""
    if state.get("version") != SUPPORTED_VERSION:
        raise StateError(
            f"unsupported state format version {state.get('version')!r}; expected "
            f"{SUPPORTED_VERSION}"
        )
    found: list[StateResource] = []
    for resource in state.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        for instance in resource.get("instances", []):
            attrs = instance.get("attributes") or {}
            resource_id = attrs.get("id")
            if not resource_id:
                continue
            parent = None
            link = _parent_link(resource["type"])
            if link and attrs.get(link[0]):
                parent = (link[1], str(attrs[link[0]]))
            found.append(
                StateResource(
                    type=resource["type"],
                    address=_address(resource, instance.get("index_key")),
                    id=str(resource_id),
                    arn=attrs.get("arn") or None,
                    parent=parent,
                    attributes=attrs,
                )
            )
    return found


class StateIndex:
    """Lookup of Terraform-managed resources by (type, id) and by ARN."""

    def __init__(self, resources: Iterable[StateResource] = ()) -> None:
        self._by_key: dict[tuple[str, str], StateResource] = {}
        self._by_arn: dict[str, StateResource] = {}
        self._children: dict[tuple[str, str], list[StateResource]] = {}
        for resource in resources:
            self.add(resource)

    def add(self, resource: StateResource) -> None:
        self._by_key[resource.key] = resource
        if resource.arn:
            self._by_arn[resource.arn] = resource
        if resource.parent:
            self._children.setdefault(resource.parent, []).append(resource)

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self) -> Any:
        return iter(self._by_key.values())

    def get(self, resource_type: str, resource_id: str) -> StateResource | None:
        return self._by_key.get((resource_type, resource_id))

    def get_by_arn(self, arn: str) -> StateResource | None:
        return self._by_arn.get(arn)

    def children(self, resource_type: str, resource_id: str) -> list[StateResource]:
        """Resources owned by this one: rules of a security group, config of a bucket, ..."""
        return list(self._children.get((resource_type, resource_id), []))

    def owner(self, resource_type: str, resource_id: str) -> StateResource | None:
        """The resource that owns this one, or the resource itself when it has no parent."""
        found = self.get(resource_type, resource_id)
        if found and found.parent:
            return self.get(*found.parent)
        return found


def build_index(states: Iterable[dict[str, Any]]) -> StateIndex:
    index = StateIndex()
    for state in states:
        for resource in parse_state(state):
            index.add(resource)
    return index


class StateReader:
    """Reads the configured state files from S3 and caches the index between invocations.

    Each ``load`` makes one HeadObject call per state file and downloads a file only when its ETag
    changed. Keep one reader in the Lambda's global scope.
    """

    def __init__(self, locations: Iterable[StateLocation], client: Any = None) -> None:
        self._locations = list(locations)
        self._client = client
        self._etags: dict[tuple[str, str], str] = {}
        self._parsed: dict[tuple[str, str], list[StateResource]] = {}
        self._index = StateIndex()
        self.downloads = 0

    def _s3(self, region: str) -> Any:
        return self._client or boto3.client("s3", region_name=region)

    def load(self) -> StateIndex:
        changed = False
        for loc in self._locations:
            ident = (loc.bucket, loc.key)
            s3 = self._s3(loc.region)
            etag = s3.head_object(Bucket=loc.bucket, Key=loc.key)["ETag"]
            if self._etags.get(ident) == etag:
                continue
            body = s3.get_object(Bucket=loc.bucket, Key=loc.key)["Body"].read()
            self.downloads += 1
            try:
                resources = parse_state(json.loads(body))
            except (ValueError, StateError) as exc:
                raise StateError(f"s3://{loc.bucket}/{loc.key}: {exc}") from exc
            self._parsed[ident] = resources
            self._etags[ident] = etag
            changed = True
            logger.info(
                json.dumps(
                    {
                        "msg": "state loaded",
                        "key": loc.key,
                        "resources": [r.address for r in resources],
                    }
                )
            )
        if changed:
            self._index = StateIndex(r for res in self._parsed.values() for r in res)
        return self._index
