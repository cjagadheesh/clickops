import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "empty_bucket", ROOT / "scripts" / "empty_bucket.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_bucket(name: str, versioned: bool) -> object:
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
    if versioned:
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    return s3


@mock_aws
def test_removes_all_versions_and_delete_markers() -> None:
    s3 = make_bucket("clickops-tfstate-1", versioned=True)
    for body in (b"1", b"2"):
        s3.put_object(Bucket="clickops-tfstate-1", Key="sandbox/terraform.tfstate", Body=body)
    s3.put_object(Bucket="clickops-tfstate-1", Key="other", Body=b"x")
    s3.delete_object(Bucket="clickops-tfstate-1", Key="other")  # leaves a delete marker

    assert load().empty_bucket("clickops-tfstate-1") == 4
    listing = s3.list_object_versions(Bucket="clickops-tfstate-1")
    assert "Versions" not in listing and "DeleteMarkers" not in listing
    s3.delete_bucket(Bucket="clickops-tfstate-1")


@mock_aws
def test_unversioned_and_empty_buckets() -> None:
    s3 = make_bucket("clickops-trail-1", versioned=False)
    s3.put_object(Bucket="clickops-trail-1", Key="a", Body=b"x")
    module = load()
    assert module.empty_bucket("clickops-trail-1") == 1
    assert module.empty_bucket("clickops-trail-1") == 0


@mock_aws
def test_missing_bucket_is_not_an_error() -> None:
    assert load().empty_bucket("clickops-gone") == 0


@mock_aws
def test_refuses_buckets_that_are_not_clickops() -> None:
    s3 = make_bucket("someone-elses", versioned=False)
    s3.put_object(Bucket="someone-elses", Key="a", Body=b"x")
    module = load()
    with pytest.raises(ValueError, match="only clickops-"):
        module.empty_bucket("someone-elses")
    assert module.main(["empty_bucket.py", "someone-elses"]) == 2
    assert s3.list_objects_v2(Bucket="someone-elses")["KeyCount"] == 1


def test_usage_error() -> None:
    assert load().main(["empty_bucket.py"]) == 2
