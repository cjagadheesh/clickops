import json
import logging
from pathlib import Path

import pytest
from conftest import fixture_paths, load_fixture

from clickops import resolvers
from clickops.events import normalize
from clickops.models import NormalizedEvent
from clickops.resolvers.base import STATE_TYPES, find_in_state
from clickops.resolvers.lambda_fn import function_name
from clickops.resolvers.route53 import record_id
from clickops.state import build_index

STATE = Path(__file__).resolve().parent / "fixtures" / "state" / "sandbox-state.json"
INDEX = build_index([json.loads(STATE.read_text())])
ZONE = "Z0123456789ABCDEFGHIJ"
INSTANCE = "i-0123456789abcdef0"

# fixture stem -> [(ref type, ref id, managed in state?)]
EXPECTED = {
    "ec2/RunInstances": [("ec2", INSTANCE, True), ("ec2", "i-0fedcba9876543210", False)],
    "ec2/TerminateInstances": [("ec2", INSTANCE, True)],
    "ec2/ModifyInstanceAttribute": [("ec2", INSTANCE, True)],
    "ec2/StartInstances": [("ec2", INSTANCE, True)],
    "ec2/StopInstances": [("ec2", INSTANCE, True)],
    "ec2/StopInstances.service-linked": [("ec2", INSTANCE, True)],
    "s3/CreateBucket": [("s3", "clickops-scratch-111122223333", False)],
    "s3/DeleteBucket": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/PutBucketPolicy": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/DeleteBucketPolicy": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/PutBucketPublicAccessBlock": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/PutBucketPublicAccessBlock.console": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/DeleteBucketPublicAccessBlock": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/PutBucketVersioning": [("s3", "clickops-sandbox-111122223333", True)],
    "s3/PutBucketEncryption": [("s3", "clickops-sandbox-111122223333", True)],
    "lambda/CreateFunction20150331": [("lambda", "clickops-scratch-fn", False)],
    "lambda/DeleteFunction20150331": [("lambda", "clickops-sandbox-hello", True)],
    "lambda/UpdateFunctionConfiguration20150331v2": [("lambda", "clickops-sandbox-hello", True)],
    "lambda/UpdateFunctionCode20150331v2": [("lambda", "clickops-sandbox-hello", True)],
    "lambda/AddPermission20150331v2": [("lambda", "clickops-sandbox-hello", True)],
    "route53/ChangeResourceRecordSets": [
        ("route53-record", f"{ZONE}_app.clickops.internal_A", True),
        ("route53-record", f"{ZONE}_db.clickops.internal_A", True),
    ],
    "route53/CreateHostedZone": [("route53-zone", "Z0987654321ZYXWVUTSRQ", False)],
    "route53/DeleteHostedZone": [("route53-zone", ZONE, True)],
}


def _stem(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def _event(path: Path) -> NormalizedEvent:
    event = normalize(json.loads(path.read_text()))
    assert event is not None
    return event


def _load(service: str, name: str) -> NormalizedEvent:
    event = normalize(load_fixture(service, name))
    assert event is not None
    return event


REST_PATHS = [
    p
    for p in fixture_paths()
    if p.parent.name in ("s3", "lambda", "route53")
    or (
        p.parent.name == "ec2"
        and p.stem.split(".")[0]
        in {
            "RunInstances",
            "TerminateInstances",
            "ModifyInstanceAttribute",
            "StartInstances",
            "StopInstances",
        }
    )
]


def test_expected_table_covers_every_remaining_fixture() -> None:
    assert {_stem(p) for p in REST_PATHS} == set(EXPECTED)


@pytest.mark.parametrize("path", REST_PATHS, ids=_stem)
def test_fixture_resolves_to_expected_refs(path: Path) -> None:
    expected = EXPECTED[_stem(path)]
    refs = resolvers.resolve(_event(path))
    assert [(r.type, r.id) for r in refs] == [(t, i) for t, i, _ in expected]
    for ref, (_, _, managed) in zip(refs, expected, strict=True):
        assert (find_in_state(INDEX, ref) is not None) is managed


def test_every_fixture_in_the_library_resolves_to_at_least_one_ref() -> None:
    for path in fixture_paths():
        refs = resolvers.resolve(_event(path))
        assert refs, f"{_stem(path)} resolved to nothing"
        assert all(r.type in STATE_TYPES for r in refs)


def test_run_instances_gives_one_ref_per_instance() -> None:
    refs = resolvers.resolve(_load("ec2", "RunInstances"))
    assert [r.id for r in refs] == [INSTANCE, "i-0fedcba9876543210"]
    assert refs[0].arn == f"arn:aws:ec2:ap-south-1:111122223333:instance/{INSTANCE}"


def test_terminate_with_several_instances_and_duplicates() -> None:
    event = _load("ec2", "TerminateInstances")
    items = [{"instanceId": "i-1"}, {"instanceId": "i-2"}, {"instanceId": "i-1"}]
    event = event.model_copy(update={"request_parameters": {"instancesSet": {"items": items}}})
    assert [r.id for r in resolvers.resolve(event)] == ["i-1", "i-2"]


def test_record_ids_follow_terraform_import_format() -> None:
    assert record_id(ZONE, "App.Clickops.Internal.", "a") == f"{ZONE}_app.clickops.internal_A"


def test_change_batch_with_repeated_records_gives_one_ref_each() -> None:
    event = _load("route53", "ChangeResourceRecordSets")
    change = event.request_parameters["changeBatch"]["changes"][0]
    batch = {
        "changes": [
            change,
            change,
            {
                "action": "DELETE",
                "resourceRecordSet": {"name": "app.clickops.internal.", "type": "TXT"},
            },
        ]
    }
    event = event.model_copy(
        update={"request_parameters": {"hostedZoneId": ZONE, "changeBatch": batch}}
    )
    assert [r.id for r in resolvers.resolve(event)] == [
        f"{ZONE}_app.clickops.internal_A",
        f"{ZONE}_app.clickops.internal_TXT",
    ]


def test_hosted_zone_ids_with_prefix_are_cleaned() -> None:
    event = _load("route53", "ChangeResourceRecordSets")
    event = event.model_copy(
        update={
            "request_parameters": {
                **event.request_parameters,
                "hostedZoneId": f"/hostedzone/{ZONE}",
            }
        }
    )
    assert resolvers.resolve(event)[0].id.startswith(f"{ZONE}_")


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("my-fn", "my-fn"),
        ("my-fn:live", "my-fn"),
        ("arn:aws:lambda:ap-south-1:111122223333:function:my-fn", "my-fn"),
        ("arn:aws:lambda:ap-south-1:111122223333:function:my-fn:3", "my-fn"),
        ("111122223333:function:my-fn", "my-fn"),
    ],
)
def test_lambda_function_name_forms(raw: str, name: str) -> None:
    assert function_name(raw) == name


def test_lambda_event_with_arn_resolves_to_bare_name() -> None:
    event = _load("lambda", "UpdateFunctionConfiguration20150331v2")
    arn = "arn:aws:lambda:ap-south-1:111122223333:function:clickops-sandbox-hello:live"
    event = event.model_copy(update={"request_parameters": {"functionName": arn}})
    assert [r.id for r in resolvers.resolve(event)] == ["clickops-sandbox-hello"]


def test_unwatched_events_give_empty_lists_and_log_once_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    resolvers._logged_unknown.clear()
    event = _load("s3", "CreateBucket").model_copy(update={"name": "GetObject"})
    with caplog.at_level(logging.DEBUG, logger="clickops"):
        assert resolvers.resolve(event) == []
        assert resolvers.resolve(event) == []
        assert resolvers.resolve(event.model_copy(update={"source": "sqs.amazonaws.com"})) == []
    messages = [r for r in caplog.records if r.name == "clickops"]
    assert len(messages) == 2  # once per (source, name), nothing raised
    assert all(r.levelno == logging.DEBUG for r in messages)


def test_missing_ids_give_no_refs() -> None:
    for service, name in (
        ("s3", "DeleteBucket"),
        ("lambda", "DeleteFunction20150331"),
        ("route53", "DeleteHostedZone"),
        ("ec2", "ModifyInstanceAttribute"),
    ):
        event = _load(service, name).model_copy(update={"request_parameters": {}})
        assert resolvers.resolve(event) == [], name
