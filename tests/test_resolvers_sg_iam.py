import json
from pathlib import Path

import pytest
from conftest import fixture_paths, load_fixture

from clickops import resolvers
from clickops.events import normalize
from clickops.models import NormalizedEvent
from clickops.resolvers.base import find_in_state
from clickops.state import build_index

STATE = Path(__file__).resolve().parent / "fixtures" / "state" / "sandbox-state.json"
ACCOUNT = "111122223333"
WEB_SG = "sg-0a1b2c3d4e5f60718"
NEW_SG = "sg-0c3d4e5f607182930"
ROLE = "clickops-sandbox-app"
POLICY = f"arn:aws:iam::{ACCOUNT}:policy/clickops-sandbox-extra"

# fixture stem (service/EventName[.variant]) -> (ref type, ref id, managed in state?)
EXPECTED = {
    "ec2/CreateSecurityGroup": ("sg", NEW_SG, False),
    "ec2/DeleteSecurityGroup": ("sg", WEB_SG, True),
    "ec2/AuthorizeSecurityGroupIngress": ("sg", WEB_SG, True),
    "ec2/AuthorizeSecurityGroupIngress.console": ("sg", WEB_SG, True),
    "ec2/AuthorizeSecurityGroupIngress.ci": ("sg", WEB_SG, True),
    "ec2/AuthorizeSecurityGroupIngress.cloudformation": ("sg", WEB_SG, True),
    "ec2/AuthorizeSecurityGroupEgress": ("sg", WEB_SG, True),
    "ec2/RevokeSecurityGroupIngress": ("sg", WEB_SG, True),
    "ec2/RevokeSecurityGroupEgress": ("sg", WEB_SG, True),
    "ec2/ModifySecurityGroupRules": ("sg", WEB_SG, True),
    "iam/CreateRole": ("iam-role", "clickops-scratch-role", False),
    "iam/DeleteRole": ("iam-role", ROLE, True),
    "iam/UpdateAssumeRolePolicy": ("iam-role", ROLE, True),
    "iam/PutRolePolicy": ("iam-role", ROLE, True),
    "iam/PutRolePolicy.self": ("iam-role", ROLE, True),
    "iam/DeleteRolePolicy": ("iam-role", ROLE, True),
    "iam/AttachRolePolicy": ("iam-role", ROLE, True),
    "iam/AttachRolePolicy.console": ("iam-role", ROLE, True),
    "iam/DetachRolePolicy": ("iam-role", ROLE, True),
    "iam/CreatePolicy": ("iam-policy", POLICY, False),
    "iam/CreatePolicyVersion": ("iam-policy", POLICY, False),
}
# Instance events share ec2.amazonaws.com; they resolve on a later day.
NOT_YET = {
    "RunInstances",
    "TerminateInstances",
    "ModifyInstanceAttribute",
    "StartInstances",
    "StopInstances",
}


def _event(path: Path) -> NormalizedEvent:
    event = normalize(json.loads(path.read_text()))
    assert event is not None
    return event


def _stem(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


SG_IAM_PATHS = [
    p
    for p in fixture_paths()
    if p.parent.name in ("ec2", "iam") and p.stem.split(".")[0] not in NOT_YET
]
INDEX = build_index([json.loads(STATE.read_text())])


def test_expected_table_covers_every_sg_and_iam_fixture() -> None:
    assert {_stem(p) for p in SG_IAM_PATHS} == set(EXPECTED)


@pytest.mark.parametrize("path", SG_IAM_PATHS, ids=_stem)
def test_fixture_resolves_to_the_expected_ref(path: Path) -> None:
    ref_type, ref_id, managed = EXPECTED[_stem(path)]
    refs = resolvers.resolve(_event(path))
    assert len(refs) == 1
    assert (refs[0].type, refs[0].id) == (ref_type, ref_id)
    found = find_in_state(INDEX, refs[0])
    assert (found is not None) is managed


def test_refs_carry_arn_and_region() -> None:
    sg = resolvers.resolve(_event(SG_IAM_PATHS[0].parent / "AuthorizeSecurityGroupIngress.json"))[0]
    assert sg.arn == f"arn:aws:ec2:ap-south-1:{ACCOUNT}:security-group/{WEB_SG}"
    assert sg.region == "ap-south-1"
    assert sg.key == f"sg#{WEB_SG}"
    role = resolvers.resolve(_event(SG_IAM_PATHS[0].parents[1] / "iam" / "DeleteRole.json"))[0]
    assert role.arn == f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    created = resolvers.resolve(_event(SG_IAM_PATHS[0].parents[1] / "iam" / "CreateRole.json"))[0]
    assert created.arn == f"arn:aws:iam::{ACCOUNT}:role/clickops-scratch-role"


def test_rule_level_state_resources_belong_to_the_resolved_group() -> None:
    ref = resolvers.resolve(load_event("ec2", "ModifySecurityGroupRules"))[0]
    group = find_in_state(INDEX, ref)
    assert group is not None
    assert [r.id for r in INDEX.children(group.type, group.id)] == ["sgr-0123456789abcdef0"]


def load_event(service: str, name: str) -> NormalizedEvent:
    event = normalize(load_fixture(service, name))
    assert event is not None
    return event


def test_unknown_sources_and_names_give_no_refs() -> None:
    event = load_event("ec2", "AuthorizeSecurityGroupIngress")
    assert resolvers.resolve(event.model_copy(update={"source": "sqs.amazonaws.com"})) == []
    assert resolvers.resolve(event.model_copy(update={"name": "DescribeInstances"})) == []


def test_missing_ids_give_no_refs() -> None:
    event = load_event("ec2", "AuthorizeSecurityGroupIngress")
    assert resolvers.resolve(event.model_copy(update={"request_parameters": {}})) == []
    created = load_event("ec2", "CreateSecurityGroup")
    assert resolvers.resolve(created.model_copy(update={"response_elements": {}})) == []
    role = load_event("iam", "DeleteRole")
    assert resolvers.resolve(role.model_copy(update={"request_parameters": {}})) == []
