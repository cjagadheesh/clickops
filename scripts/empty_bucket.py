#!/usr/bin/env python3
"""Delete every object, version and delete marker in a clickops S3 bucket.

Terraform cannot destroy a bucket that still holds objects (none of the clickops buckets set
``force_destroy``), so ``scripts/destroy.sh`` empties each one first. Only buckets named
``clickops-*`` are accepted.

    scripts/empty_bucket.py clickops-trail-123456789012
"""

from __future__ import annotations

import sys

import boto3
from botocore.exceptions import ClientError

PREFIX = "clickops-"


def empty_bucket(name: str, region: str = "ap-south-1") -> int:
    """Remove all versions and delete markers; return how many were deleted."""
    if not name.startswith(PREFIX):
        raise ValueError(f"refusing to empty {name!r}: only {PREFIX}* buckets are accepted")
    bucket = boto3.resource("s3", region_name=region).Bucket(name)
    deleted = 0
    try:
        for version in bucket.object_versions.all():
            version.delete()
            deleted += 1
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchBucket":
            return 0
        raise
    return deleted


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: empty_bucket.py BUCKET", file=sys.stderr)
        return 2
    try:
        count = empty_bucket(argv[1])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{argv[1]}: deleted {count} object version(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
