import json
from typing import Any

import boto3
import pytest
from helpers_state import index_of, resource
from moto import mock_aws

from clickops.compare import s3 as compare_s3
from clickops.models import ResourceRef
from clickops.resolvers.base import S3_BUCKET, find_in_state

BUCKET = "clickops-sandbox-test"
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": "*",
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }
    ],
}


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        client.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        client.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps(POLICY))
        client.put_public_access_block(
            Bucket=BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        client.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
        client.put_bucket_encryption(
            Bucket=BUCKET,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        yield client


def _compare(*, with_policy: bool = True, with_bpa: bool = True, **bpa: Any):  # type: ignore[no-untyped-def]
    flags = {
        "block_public_acls": True,
        "ignore_public_acls": True,
        "block_public_policy": True,
        "restrict_public_buckets": True,
        **bpa,
    }
    parts = [
        resource("aws_s3_bucket", "main", id=BUCKET, arn=f"arn:aws:s3:::{BUCKET}", bucket=BUCKET),
        resource(
            "aws_s3_bucket_versioning",
            "main",
            id=BUCKET,
            bucket=BUCKET,
            versioning_configuration=[{"status": "Enabled"}],
        ),
        resource(
            "aws_s3_bucket_server_side_encryption_configuration",
            "main",
            id=BUCKET,
            bucket=BUCKET,
            rule=[{"apply_server_side_encryption_by_default": [{"sse_algorithm": "AES256"}]}],
        ),
    ]
    if with_bpa:
        parts.append(
            resource("aws_s3_bucket_public_access_block", "main", id=BUCKET, bucket=BUCKET, **flags)
        )
    if with_policy:
        parts.append(
            resource(
                "aws_s3_bucket_policy", "main", id=BUCKET, bucket=BUCKET, policy=json.dumps(POLICY)
            )
        )
    index = index_of(*parts)
    ref = ResourceRef(type=S3_BUCKET, id=BUCKET, region="ap-south-1")
    state = find_in_state(index, ref)
    assert state is not None
    return compare_s3.compare(ref, index, state)


def test_matching_bucket_has_no_diff(s3) -> None:  # type: ignore[no-untyped-def]
    result = _compare()
    assert result.exists and not result.drifted


def test_changed_bucket_policy_is_reported(s3) -> None:  # type: ignore[no-untyped-def]
    open_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{BUCKET}/*",
            }
        ],
    }
    s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps(open_policy))
    assert list(_compare().diff()) == ["bucket_policy"]


def test_deleted_bucket_policy_is_reported(s3) -> None:  # type: ignore[no-untyped-def]
    s3.delete_bucket_policy(Bucket=BUCKET)
    diff = _compare().diff()
    assert diff["bucket_policy"]["live"] is None
    assert diff["bucket_policy"]["state"]["Statement"][0]["Effect"] == "Deny"


@pytest.mark.parametrize(
    ("flag", "api"),
    [
        ("block_public_acls", "BlockPublicAcls"),
        ("ignore_public_acls", "IgnorePublicAcls"),
        ("block_public_policy", "BlockPublicPolicy"),
        ("restrict_public_buckets", "RestrictPublicBuckets"),
    ],
)
def test_each_public_access_block_flag_is_compared(s3, flag: str, api: str) -> None:  # type: ignore[no-untyped-def]
    config = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
        api: False,
    }
    s3.put_public_access_block(Bucket=BUCKET, PublicAccessBlockConfiguration=config)
    assert _compare().diff() == {f"public_access_block.{flag}": {"state": True, "live": False}}


def test_deleted_public_access_block_reports_all_four_flags(s3) -> None:  # type: ignore[no-untyped-def]
    s3.delete_public_access_block(Bucket=BUCKET)
    assert len(_compare().changes) == 4


def test_suspended_versioning_is_reported(s3) -> None:  # type: ignore[no-untyped-def]
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Suspended"})
    assert _compare().diff() == {"versioning": {"state": "Enabled", "live": "Suspended"}}


def test_changed_encryption_algorithm_is_reported(s3) -> None:  # type: ignore[no-untyped-def]
    s3.put_bucket_encryption(
        Bucket=BUCKET,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]
        },
    )
    assert _compare().diff() == {"encryption_algorithm": {"state": "AES256", "live": "aws:kms"}}


def test_settings_terraform_does_not_manage_are_skipped(s3) -> None:  # type: ignore[no-untyped-def]
    s3.delete_bucket_policy(Bucket=BUCKET)
    s3.delete_public_access_block(Bucket=BUCKET)
    assert not _compare(with_policy=False, with_bpa=False).drifted


def test_deleted_bucket_no_longer_exists(s3) -> None:  # type: ignore[no-untyped-def]
    s3.delete_bucket_policy(Bucket=BUCKET)
    s3.delete_bucket(Bucket=BUCKET)
    assert _compare().exists is False
