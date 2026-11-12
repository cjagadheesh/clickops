import json
from pathlib import Path

import boto3
import pytest
from conftest import fixture_paths
from moto import mock_aws

from clickops import compare as compare_pkg
from clickops import resolvers
from clickops.compare import DELETE_EVENTS, Comparison, compare
from clickops.events import normalize
from clickops.models import NormalizedEvent
from clickops.state import build_index

STATE = Path(__file__).resolve().parent / "fixtures" / "state" / "sandbox-state.json"
INDEX = build_index([json.loads(STATE.read_text())])


def _event(path: Path) -> NormalizedEvent:
    event = normalize(json.loads(path.read_text()))
    assert event is not None
    return event


def test_delete_events_cover_whole_resource_removal() -> None:
    assert {
        "DeleteSecurityGroup",
        "DeleteRole",
        "DeleteBucket",
        "TerminateInstances",
        "DeleteFunction",
        "DeleteHostedZone",
    } == DELETE_EVENTS


def test_delete_events_report_gone_without_calling_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("AWS was called")

    monkeypatch.setattr(boto3, "client", boom)
    names = {
        "DeleteSecurityGroup",
        "DeleteRole",
        "DeleteBucket",
        "TerminateInstances",
        "DeleteFunction20150331",
        "DeleteHostedZone",
    }
    seen = set()
    for path in fixture_paths():
        if path.stem.split(".")[0] not in names:
            continue
        event = _event(path)
        for ref in resolvers.resolve(event):
            result = compare(event, ref, INDEX)
            if result is not None:  # the ref is managed
                assert result.exists is False and not result.drifted
                seen.add(event.name)
    assert seen == DELETE_EVENTS


def test_unmanaged_resources_have_no_comparison() -> None:
    path = next(p for p in fixture_paths() if p.stem == "CreateSecurityGroup")
    event = _event(path)
    ref = resolvers.resolve(event)[0]
    assert compare(event, ref, INDEX) is None


def test_hosted_zone_refs_compare_as_unchanged() -> None:
    path = next(p for p in fixture_paths() if p.stem == "DeleteHostedZone")
    event = _event(path).model_copy(update={"name": "ChangeResourceRecordSets"})
    ref = resolvers.resolve(_event(path))[0]
    assert compare(event, ref, INDEX) == Comparison()


def test_each_resource_type_has_a_comparator() -> None:
    assert set(compare_pkg.COMPARATORS) == {
        "sg",
        "iam-role",
        "iam-policy",
        "s3",
        "ec2",
        "lambda",
        "route53-record",
    }


@mock_aws
def test_dispatches_to_the_resource_comparator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    path = next(p for p in fixture_paths() if p.stem == "PutBucketVersioning")
    event = _event(path)
    ref = resolvers.resolve(event)[0]
    # No bucket exists in moto, so the S3 comparator reports it gone.
    result = compare(event, ref, INDEX)
    assert result is not None and result.exists is False
