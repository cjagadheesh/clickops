"""Compare live configuration with Terraform state, one comparator per resource type."""

from __future__ import annotations

from clickops.compare import ec2, iam, lambda_fn, route53, s3, sg
from clickops.compare.base import Comparison, FieldChange
from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import (
    EC2_INSTANCE,
    IAM_POLICY,
    IAM_ROLE,
    LAMBDA_FUNCTION,
    ROUTE53_RECORD,
    S3_BUCKET,
    SG,
    find_in_state,
)
from clickops.state import StateIndex

# Calls that remove the whole resource. The event proves it is gone, so no describe call is made.
DELETE_EVENTS = {
    "DeleteSecurityGroup",
    "DeleteRole",
    "DeleteBucket",
    "TerminateInstances",
    "DeleteFunction",
    "DeleteHostedZone",
}

COMPARATORS = {
    SG: sg.compare,
    IAM_ROLE: iam.compare_role,
    IAM_POLICY: iam.compare_policy,
    S3_BUCKET: s3.compare,
    EC2_INSTANCE: ec2.compare,
    LAMBDA_FUNCTION: lambda_fn.compare,
    ROUTE53_RECORD: route53.compare,
}


def compare(event: NormalizedEvent, ref: ResourceRef, index: StateIndex) -> Comparison | None:
    """Live-versus-state comparison for a resource, or None when state does not manage it.

    A resource-deleting event gives ``exists=False`` without calling AWS. Resource types with no
    comparator (hosted zones) compare as unchanged.
    """
    state = find_in_state(index, ref)
    if state is None:
        return None
    if event.name in DELETE_EVENTS:
        return Comparison(exists=False)
    comparator = COMPARATORS.get(ref.type)
    return comparator(ref, index, state) if comparator else Comparison()


__all__ = ["COMPARATORS", "DELETE_EVENTS", "Comparison", "FieldChange", "compare"]
