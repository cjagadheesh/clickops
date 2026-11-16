"""Shadow-resource discovery: live resources of the six types that no Terraform state knows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops import store
from clickops.resolvers.base import (
    EC2_INSTANCE,
    IAM_POLICY,
    IAM_ROLE,
    LAMBDA_FUNCTION,
    ROUTE53_RECORD,
    ROUTE53_ZONE,
    S3_BUCKET,
    SG,
    STATE_TYPES,
)
from clickops.resolvers.route53 import record_id
from clickops.state import StateIndex

SSO_ROLE_PREFIX = "AWSReservedSSO_"
SERVICE_ROLE_PATH = "/aws-service-role/"
SKIPPED_RECORD_TYPES = {"NS", "SOA"}
_TERMINATED = {"terminated", "shutting-down"}


@dataclass(frozen=True)
class ShadowResource:
    type: str
    id: str
    name: str = ""
    created: datetime | None = None
    creator: str | None = None

    @property
    def key(self) -> str:
        return f"{self.type}#{self.id}"

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["created"] = self.created.isoformat() if self.created else None
        return data


def _managed(index: StateIndex, ref_type: str, resource_id: str) -> bool:
    return index.get(STATE_TYPES[ref_type], resource_id) is not None


def _name_tag(tags: Any) -> str:
    return next((t["Value"] for t in tags or [] if t["Key"] == "Name"), "")


def scan_security_groups(index: StateIndex, region: str) -> list[ShadowResource]:
    ec2 = boto3.client("ec2", region_name=region)
    found = []
    for page in ec2.get_paginator("describe_security_groups").paginate():
        for group in page["SecurityGroups"]:
            if group["GroupName"] == "default":  # every VPC has one; it is never created by hand
                continue
            if not _managed(index, SG, group["GroupId"]):
                found.append(ShadowResource(SG, group["GroupId"], group["GroupName"]))
    return found


def scan_instances(index: StateIndex, region: str) -> list[ShadowResource]:
    ec2 = boto3.client("ec2", region_name=region)
    found = []
    for page in ec2.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] in _TERMINATED:
                    continue
                if not _managed(index, EC2_INSTANCE, instance["InstanceId"]):
                    found.append(
                        ShadowResource(
                            EC2_INSTANCE,
                            instance["InstanceId"],
                            _name_tag(instance.get("Tags")),
                            instance.get("LaunchTime"),
                        )
                    )
    return found


def scan_roles(index: StateIndex) -> list[ShadowResource]:
    iam = boto3.client("iam", region_name="us-east-1")
    found = []
    for page in iam.get_paginator("list_roles").paginate():
        for role in page["Roles"]:
            name, path = role["RoleName"], role.get("Path", "/")
            if path.startswith(SERVICE_ROLE_PATH) or name.startswith(SSO_ROLE_PREFIX):
                continue
            if not _managed(index, IAM_ROLE, name):
                found.append(ShadowResource(IAM_ROLE, name, name, role.get("CreateDate")))
    return found


def scan_policies(index: StateIndex) -> list[ShadowResource]:
    iam = boto3.client("iam", region_name="us-east-1")
    found = []
    # Scope "Local" lists customer-managed policies only, which leaves out AWS-managed ones.
    for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
        for policy in page["Policies"]:
            if not _managed(index, IAM_POLICY, policy["Arn"]):
                found.append(
                    ShadowResource(
                        IAM_POLICY, policy["Arn"], policy["PolicyName"], policy.get("CreateDate")
                    )
                )
    return found


def scan_buckets(index: StateIndex, region: str) -> list[ShadowResource]:
    s3 = boto3.client("s3", region_name=region)
    found = []
    for bucket in s3.list_buckets()["Buckets"]:
        name = bucket["Name"]
        location = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        if location != region:
            continue
        if not _managed(index, S3_BUCKET, name):
            found.append(ShadowResource(S3_BUCKET, name, name, bucket.get("CreationDate")))
    return found


def scan_functions(index: StateIndex, region: str) -> list[ShadowResource]:
    lam = boto3.client("lambda", region_name=region)
    found = []
    for page in lam.get_paginator("list_functions").paginate():
        for function in page["Functions"]:
            name = function["FunctionName"]
            if not _managed(index, LAMBDA_FUNCTION, name):
                found.append(ShadowResource(LAMBDA_FUNCTION, name, name))
    return found


def scan_route53(index: StateIndex) -> list[ShadowResource]:
    r53 = boto3.client("route53", region_name="us-east-1")
    found = []
    for zone_page in r53.get_paginator("list_hosted_zones").paginate():
        for zone in zone_page["HostedZones"]:
            zone_id = zone["Id"].rsplit("/", 1)[-1]
            if not _managed(index, ROUTE53_ZONE, zone_id):
                # Records of an unmanaged zone come with the zone, so they are not listed too.
                found.append(ShadowResource(ROUTE53_ZONE, zone_id, zone["Name"].rstrip(".")))
                continue
            for page in r53.get_paginator("list_resource_record_sets").paginate(
                HostedZoneId=zone_id
            ):
                for record in page["ResourceRecordSets"]:
                    if record["Type"] in SKIPPED_RECORD_TYPES:
                        continue
                    ident = record_id(zone_id, record["Name"], record["Type"])
                    if not _managed(index, ROUTE53_RECORD, ident):
                        found.append(
                            ShadowResource(ROUTE53_RECORD, ident, record["Name"].rstrip("."))
                        )
    return found


def find_creator(table: Any, resource: ShadowResource) -> str | None:
    """Who created the resource, from the event store (the first stored event for it)."""
    try:
        items = table.query(
            KeyConditionExpression="resource_key = :k",
            ExpressionAttributeValues={":k": resource.key},
        )["Items"]
    except ClientError:
        return None
    creations = [i for i in items if i.get("outcome") == "shadow-create"] or items
    return str(creations[0]["actor_name"]) if creations and creations[0].get("actor_name") else None


def scan(index: StateIndex, region: str = "ap-south-1", table: Any = None) -> list[ShadowResource]:
    """Every live resource of the six types that is in no state file, sorted by type and ID."""
    found = [
        *scan_security_groups(index, region),
        *scan_roles(index),
        *scan_policies(index),
        *scan_buckets(index, region),
        *scan_instances(index, region),
        *scan_functions(index, region),
        *scan_route53(index),
    ]
    if table is not None:
        found = [
            ShadowResource(r.type, r.id, r.name, r.created, find_creator(table, r)) for r in found
        ]
    return sorted(found, key=lambda r: (r.type, r.id))


def open_table(region: str) -> Any:
    return boto3.resource("dynamodb", region_name=region).Table(store.TABLE_NAME)
