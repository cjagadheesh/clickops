"""Shared pieces for resolvers: resource type names and the link to Terraform state types."""

from __future__ import annotations

from collections.abc import Callable

from clickops.models import NormalizedEvent, ResourceRef
from clickops.state import StateIndex, StateResource

Resolver = Callable[[NormalizedEvent], list[ResourceRef]]

# ResourceRef.type values (they prefix the event store key, e.g. sg#sg-0abc).
SG = "sg"
IAM_ROLE = "iam-role"
IAM_POLICY = "iam-policy"
S3_BUCKET = "s3"
EC2_INSTANCE = "ec2"
LAMBDA_FUNCTION = "lambda"
ROUTE53_ZONE = "route53-zone"
ROUTE53_RECORD = "route53-record"

# The Terraform resource type that owns each kind of resource in state.
STATE_TYPES: dict[str, str] = {
    SG: "aws_security_group",
    IAM_ROLE: "aws_iam_role",
    IAM_POLICY: "aws_iam_policy",
    S3_BUCKET: "aws_s3_bucket",
    EC2_INSTANCE: "aws_instance",
    LAMBDA_FUNCTION: "aws_lambda_function",
    ROUTE53_ZONE: "aws_route53_zone",
    ROUTE53_RECORD: "aws_route53_record",
}


def find_in_state(index: StateIndex, ref: ResourceRef) -> StateResource | None:
    """The Terraform-managed resource for this ref, or None when state does not know it."""
    state_type = STATE_TYPES.get(ref.type)
    return index.get(state_type, ref.id) if state_type else None


def param(event: NormalizedEvent, *path: str) -> str | None:
    """A string from the request parameters, following a path of keys."""
    value: object = event.request_parameters
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, str) and value else None


def response(event: NormalizedEvent, *path: str) -> str | None:
    """A string from the response elements, following a path of keys."""
    value: object = event.response_elements
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, str) and value else None
