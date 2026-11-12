"""S3 bucket policy, public access block, versioning and encryption: live versus state."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, FieldChange, changed, children_of, normalize_policy
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource

BPA_FLAGS = (
    "block_public_acls",
    "block_public_policy",
    "ignore_public_acls",
    "restrict_public_buckets",
)
_BPA_API = {
    "block_public_acls": "BlockPublicAcls",
    "block_public_policy": "BlockPublicPolicy",
    "ignore_public_acls": "IgnorePublicAcls",
    "restrict_public_buckets": "RestrictPublicBuckets",
}


def _first(value: Any) -> dict[str, Any]:
    return value[0] if isinstance(value, list) and value else {}


def _error_code(exc: ClientError) -> str:
    return str(exc.response["Error"]["Code"])


def _live_policy(s3: Any, bucket: str) -> Any:
    try:
        return normalize_policy(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    except ClientError as exc:
        if _error_code(exc) == "NoSuchBucketPolicy":
            return None
        raise


def _live_bpa(s3: Any, bucket: str) -> dict[str, bool]:
    try:
        config = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    except ClientError as exc:
        if _error_code(exc) == "NoSuchPublicAccessBlockConfiguration":
            return dict.fromkeys(BPA_FLAGS, False)
        raise
    return {flag: bool(config.get(api, False)) for flag, api in _BPA_API.items()}


def _live_versioning(s3: Any, bucket: str) -> str:
    return str(s3.get_bucket_versioning(Bucket=bucket).get("Status") or "Disabled")


def _live_encryption(s3: Any, bucket: str) -> str | None:
    try:
        config = s3.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]
    except ClientError as exc:
        if _error_code(exc) == "ServerSideEncryptionConfigurationNotFoundError":
            return None
        raise
    default = config["Rules"][0]["ApplyServerSideEncryptionByDefault"]
    return str(default["SSEAlgorithm"])


def compare(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    """Compare only what Terraform manages: a setting without a state resource is skipped."""
    bucket = ref.id
    s3 = boto3.client("s3", region_name=ref.region)
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if _error_code(exc) in {"404", "NoSuchBucket", "NotFound"}:
            return Comparison(exists=False)
        raise

    changes: list[FieldChange] = []
    policies = children_of(index, state, "aws_s3_bucket_policy")
    if policies:
        changes += changed(
            "bucket_policy",
            normalize_policy(policies[0].attributes.get("policy")),
            _live_policy(s3, bucket),
        )
    blocks = children_of(index, state, "aws_s3_bucket_public_access_block")
    if blocks:
        want = {flag: bool(blocks[0].attributes.get(flag, False)) for flag in BPA_FLAGS}
        live = _live_bpa(s3, bucket)
        changes += [
            FieldChange(f"public_access_block.{flag}", want[flag], live[flag])
            for flag in BPA_FLAGS
            if want[flag] != live[flag]
        ]
    versioning = children_of(index, state, "aws_s3_bucket_versioning")
    if versioning:
        status = _first(versioning[0].attributes.get("versioning_configuration")).get("status")
        changes += changed("versioning", status or "Disabled", _live_versioning(s3, bucket))
    encryption = children_of(index, state, "aws_s3_bucket_server_side_encryption_configuration")
    if encryption:
        rule = _first(encryption[0].attributes.get("rule"))
        default = _first(rule.get("apply_server_side_encryption_by_default"))
        changes += changed(
            "encryption_algorithm", default.get("sse_algorithm"), _live_encryption(s3, bucket)
        )
    return Comparison(changes=changes)
