"""S3 events to the bucket they change."""

from __future__ import annotations

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers.base import S3_BUCKET, param

BUCKET_EVENTS = {
    "CreateBucket",
    "DeleteBucket",
    "PutBucketPolicy",
    "DeleteBucketPolicy",
    "PutBucketPublicAccessBlock",
    "DeleteBucketPublicAccessBlock",
    "PutBucketVersioning",
    "PutBucketEncryption",
}


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    if event.name not in BUCKET_EVENTS:
        return []
    bucket = param(event, "bucketName")
    if not bucket:
        return []
    return [
        ResourceRef(type=S3_BUCKET, id=bucket, arn=f"arn:aws:s3:::{bucket}", region=event.region)
    ]
