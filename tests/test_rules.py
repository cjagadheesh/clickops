import json
from typing import Any

import pytest
from conftest import load_fixture
from helpers_state import index_of, resource

from clickops.compare.base import Comparison, FieldChange
from clickops.config import Config, IgnoreRule, SeverityOverride, StateLocation
from clickops.events import normalize
from clickops.models import Actor, ActorClass, NormalizedEvent, Outcome, ResourceRef, Severity
from clickops.rules import (
    decide,
    exposes_world,
    is_creation,
    policy_is_dangerous,
    request_tags,
)
from clickops.state import StateResource

HUMAN = Actor(actor_class=ActorClass.CLI_HUMAN, display_name="asha")
SG_REF = ResourceRef(type="sg", id="sg-0a1b2c3d4e5f60718")
DRIFT = Comparison(
    changes=[FieldChange("ingress", ["tcp 443-443 0.0.0.0/0"], ["tcp 22-22 10.0.0.0/8"])]
)


def event(service: str, name: str, **request: Any) -> NormalizedEvent:
    base = normalize(load_fixture(service, name))
    assert base is not None
    if request:
        return base.model_copy(update={"request_parameters": request})
    return base


def state_of(
    type_: str = "aws_security_group", id_: str = "sg-0a1b2c3d4e5f60718", **attrs: Any
) -> StateResource:
    found = index_of(resource(type_, "x", id=id_, **attrs)).get(type_, id_)
    assert found is not None
    return found


def config(**kwargs: Any) -> Config:
    return Config(state_locations=[StateLocation(bucket="b", key="k")], **kwargs)


# --- the spec's outcome and severity table -----------------------------------------------------


def test_managed_drift_is_a_warning() -> None:
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state_of(), DRIFT)
    assert (result.outcome, result.severity) == (Outcome.MANAGED_DRIFT, Severity.WARNING)


def test_managed_delete_is_critical() -> None:
    gone = Comparison(exists=False)
    result = decide(event("ec2", "DeleteSecurityGroup"), HUMAN, SG_REF, state_of(), gone)
    assert (result.outcome, result.severity) == (Outcome.MANAGED_DELETE, Severity.CRITICAL)


def test_shadow_create_is_info() -> None:
    result = decide(event("ec2", "CreateSecurityGroup"), HUMAN, SG_REF, None, None)
    assert (result.outcome, result.severity) == (Outcome.SHADOW_CREATE, Severity.INFO)


@pytest.mark.parametrize(
    "actor_class", [ActorClass.CI, ActorClass.CLICKOPS_SELF, ActorClass.AWS_SERVICE]
)
def test_machine_actors_are_ignored(actor_class: ActorClass) -> None:
    actor = Actor(actor_class=actor_class, display_name="x")
    result = decide(
        event("ec2", "DeleteSecurityGroup"), actor, SG_REF, state_of(), Comparison(exists=False)
    )
    assert (result.outcome, result.severity) == (Outcome.IGNORED, Severity.NONE)


def test_console_humans_are_alerted_like_cli_humans() -> None:
    actor = Actor(actor_class=ActorClass.CONSOLE_HUMAN, display_name="asha")
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), actor, SG_REF, state_of(), DRIFT)
    assert result.outcome is Outcome.MANAGED_DRIFT


def test_change_to_an_unmanaged_resource_is_ignored() -> None:
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, None, None)
    assert result.outcome is Outcome.IGNORED


def test_change_that_matches_state_is_ignored() -> None:
    result = decide(
        event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state_of(), Comparison()
    )
    assert (result.outcome, result.severity) == (Outcome.IGNORED, Severity.NONE)


def test_missing_comparison_for_a_managed_resource_counts_as_deleted() -> None:
    result = decide(event("ec2", "DeleteSecurityGroup"), HUMAN, SG_REF, state_of(), None)
    assert result.outcome is Outcome.MANAGED_DELETE


# --- Route 53 records --------------------------------------------------------------------------


def test_route53_upsert_of_an_unmanaged_record_is_a_shadow_create() -> None:
    ev = event("route53", "ChangeResourceRecordSets")
    new = ResourceRef(type="route53-record", id="Z0123456789ABCDEFGHIJ_app.clickops.internal_A")
    assert is_creation(ev, new)
    assert decide(ev, HUMAN, new, None, None).outcome is Outcome.SHADOW_CREATE


def test_route53_delete_of_an_unmanaged_record_is_not_a_creation() -> None:
    ev = event("route53", "ChangeResourceRecordSets")
    other = ResourceRef(type="route53-record", id="Z0123456789ABCDEFGHIJ_db.clickops.internal_A")
    assert not is_creation(ev, other)
    assert decide(ev, HUMAN, other, None, None).outcome is Outcome.IGNORED


# --- critical overrides ------------------------------------------------------------------------


def ingress(
    cidr: str, proto: str = "tcp", low: int = 22, high: int = 22, v6: bool = False
) -> NormalizedEvent:
    key = "ipv6Ranges" if v6 else "ipRanges"
    cidr_key = "cidrIpv6" if v6 else "cidrIp"
    perm = {
        "ipProtocol": proto,
        "fromPort": low,
        "toPort": high,
        key: {"items": [{cidr_key: cidr}]},
    }
    return event(
        "ec2", "AuthorizeSecurityGroupIngress", groupId=SG_REF.id, ipPermissions={"items": [perm]}
    )


@pytest.mark.parametrize(
    ("cidr", "proto", "low", "high", "v6", "critical"),
    [
        ("0.0.0.0/0", "tcp", 22, 22, False, True),
        ("0.0.0.0/0", "tcp", 80, 80, False, False),
        ("0.0.0.0/0", "tcp", 443, 443, False, False),
        ("0.0.0.0/0", "tcp", 80, 443, False, True),
        ("0.0.0.0/0", "-1", -1, -1, False, True),
        ("::/0", "tcp", 22, 22, True, True),
        ("::/0", "tcp", 443, 443, True, False),
        ("10.0.0.0/8", "tcp", 22, 22, False, False),
        ("0.0.0.0/0", "tcp", 0, 65535, False, True),
    ],
)
def test_world_ingress_override(
    cidr: str, proto: str, low: int, high: int, v6: bool, critical: bool
) -> None:
    result = decide(ingress(cidr, proto, low, high, v6), HUMAN, SG_REF, state_of(), DRIFT)
    assert result.outcome is Outcome.MANAGED_DRIFT
    assert (result.severity is Severity.CRITICAL) is critical


def test_world_ingress_found_by_comparison_makes_drift_critical() -> None:
    added = Comparison(
        changes=[
            FieldChange(
                "ingress",
                ["tcp 443-443 0.0.0.0/0"],
                ["tcp 22-22 0.0.0.0/0", "tcp 443-443 0.0.0.0/0"],
            )
        ]
    )
    ev = event("ec2", "ModifySecurityGroupRules")
    assert decide(ev, HUMAN, SG_REF, state_of(), added).severity is Severity.CRITICAL


def test_existing_coded_world_rule_does_not_make_every_change_critical() -> None:
    coded = Comparison(
        changes=[
            FieldChange("egress", [], ["tcp 8443-8443 10.0.0.0/8"]),
            FieldChange("ingress", ["tcp 22-22 0.0.0.0/0"], ["tcp 22-22 0.0.0.0/0"]),
        ]
    )
    ev = event("ec2", "AuthorizeSecurityGroupEgress")
    assert decide(ev, HUMAN, SG_REF, state_of(), coded).severity is Severity.WARNING


def test_world_ingress_on_a_new_group_is_critical_shadow_create() -> None:
    ev = ingress("0.0.0.0/0").model_copy(update={"name": "AuthorizeSecurityGroupIngress"})
    result = decide(ev, HUMAN, SG_REF, None, None)
    assert result.outcome is Outcome.IGNORED  # not a creation; the group itself is not managed
    created = event("ec2", "CreateSecurityGroup")
    assert decide(created, HUMAN, SG_REF, None, None).severity is Severity.INFO


def doc(*statements: dict[str, Any]) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


ROLE_REF = ResourceRef(type="iam-role", id="clickops-sandbox-app")


@pytest.mark.parametrize(
    ("statement", "dangerous"),
    [
        ({"Effect": "Allow", "Action": "*", "Resource": "*"}, True),
        ({"Effect": "Allow", "Action": "s3:PutObject", "Resource": "*"}, True),
        ({"Effect": "Allow", "Action": ["s3:GetObject", "s3:DeleteObject"], "Resource": "*"}, True),
        ({"Effect": "Allow", "Action": "s3:*", "Resource": "arn:aws:s3:::b/*"}, False),
        ({"Effect": "Allow", "Action": "*", "Resource": "arn:aws:s3:::b/*"}, True),
        ({"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}, False),
        ({"Effect": "Allow", "Action": ["s3:GetObject", "ec2:Describe*"], "Resource": "*"}, False),
        ({"Effect": "Allow", "Action": "iam:PassRole", "Resource": "arn:aws:iam::1:role/x"}, False),
        ({"Effect": "Deny", "Action": "*", "Resource": "*"}, False),
    ],
)
def test_policy_is_dangerous(statement: dict[str, Any], dangerous: bool) -> None:
    assert policy_is_dangerous(doc(statement)) is dangerous


def test_policy_is_dangerous_accepts_documents_and_single_statements() -> None:
    assert policy_is_dangerous({"Statement": {"Effect": "Allow", "Action": "*", "Resource": "*"}})
    assert not policy_is_dangerous("not json")


def test_iam_wildcard_write_policy_makes_the_drift_critical() -> None:
    bad = event(
        "iam",
        "PutRolePolicy",
        roleName=ROLE_REF.id,
        policyName="x",
        policyDocument=doc({"Effect": "Allow", "Action": "*", "Resource": "*"}),
    )
    ok = event(
        "iam",
        "PutRolePolicy",
        roleName=ROLE_REF.id,
        policyName="x",
        policyDocument=doc({"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}),
    )
    state = state_of("aws_iam_role", ROLE_REF.id)
    change = Comparison(changes=[FieldChange("inline_policies", {}, {"x": None})])
    assert decide(bad, HUMAN, ROLE_REF, state, change).severity is Severity.CRITICAL
    assert decide(ok, HUMAN, ROLE_REF, state, change).severity is Severity.WARNING


def test_wildcard_policy_found_by_comparison_makes_the_drift_critical() -> None:
    wide = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }
    change = Comparison(changes=[FieldChange("inline_policies", {}, {"admin": wide})])
    ev = event("iam", "PutRolePolicy", roleName=ROLE_REF.id, policyName="admin")
    state = state_of("aws_iam_role", ROLE_REF.id)
    assert decide(ev, HUMAN, ROLE_REF, state, change).severity is Severity.CRITICAL


def test_attaching_a_managed_policy_is_only_a_warning() -> None:
    ev = event("iam", "AttachRolePolicy")
    change = Comparison(
        changes=[
            FieldChange("attached_policy_arns", [], ["arn:aws:iam::aws:policy/AmazonS3FullAccess"])
        ]
    )
    result = decide(ev, HUMAN, ROLE_REF, state_of("aws_iam_role", ROLE_REF.id), change)
    assert result.severity is Severity.WARNING


BUCKET_REF = ResourceRef(type="s3", id="clickops-sandbox-111122223333")


def test_block_public_access_override() -> None:
    state = state_of("aws_s3_bucket", BUCKET_REF.id)
    change = Comparison(changes=[FieldChange("versioning", "Enabled", "Suspended")])
    off = event("s3", "PutBucketPublicAccessBlock")
    assert decide(off, HUMAN, BUCKET_REF, state, change).severity is Severity.CRITICAL
    on_all = event(
        "s3",
        "PutBucketPublicAccessBlock",
        bucketName=BUCKET_REF.id,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    assert decide(on_all, HUMAN, BUCKET_REF, state, change).severity is Severity.WARNING
    deleted = event("s3", "DeleteBucketPublicAccessBlock")
    assert decide(deleted, HUMAN, BUCKET_REF, state, change).severity is Severity.CRITICAL


def test_block_public_access_found_by_comparison() -> None:
    change = Comparison(changes=[FieldChange("public_access_block.block_public_acls", True, False)])
    ev = event("s3", "PutBucketVersioning")
    state = state_of("aws_s3_bucket", BUCKET_REF.id)
    assert decide(ev, HUMAN, BUCKET_REF, state, change).severity is Severity.CRITICAL


def test_critical_reason_is_recorded() -> None:
    result = decide(ingress("0.0.0.0/0"), HUMAN, SG_REF, state_of(), DRIFT)
    assert "world" in result.reason


def test_exposes_world_helper() -> None:
    assert exposes_world([("tcp", 22, 22, "0.0.0.0/0")])
    assert not exposes_world([("tcp", 443, 443, "0.0.0.0/0"), ("tcp", 22, 22, "10.0.0.0/8")])


# --- opt-out tag -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "True", "TRUE"])
def test_ignore_tag_in_state_suppresses_alerts(value: str) -> None:
    state = state_of(tags={"clickops:ignore": value})
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state, DRIFT)
    assert (result.outcome, result.severity) == (Outcome.IGNORED, Severity.NONE)


def test_ignore_tag_in_tags_all_and_even_for_critical_changes() -> None:
    state = state_of(tags_all={"clickops:ignore": "true"})
    result = decide(ingress("0.0.0.0/0"), HUMAN, SG_REF, state, DRIFT)
    assert result.outcome is Outcome.IGNORED


def test_other_tag_values_do_not_suppress() -> None:
    state = state_of(tags={"clickops:ignore": "false"})
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state, DRIFT)
    assert result.outcome is Outcome.MANAGED_DRIFT


def test_ignore_tag_on_a_new_resource_comes_from_the_request() -> None:
    ev = event(
        "ec2",
        "CreateSecurityGroup",
        groupName="x",
        tagSpecificationSet={
            "items": [
                {
                    "resourceType": "security-group",
                    "tags": [{"key": "clickops:ignore", "value": "true"}],
                }
            ]
        },
    )
    assert request_tags(ev) == {"clickops:ignore": "true"}
    assert decide(ev, HUMAN, SG_REF, None, None).outcome is Outcome.IGNORED
    lam = event(
        "lambda", "CreateFunction20150331", functionName="f", tags={"clickops:ignore": "true"}
    )
    assert request_tags(lam) == {"clickops:ignore": "true"}


# --- config ------------------------------------------------------------------------------------


def test_config_ignore_rules_match_type_and_id_pattern() -> None:
    cfg = config(
        ignore=[
            IgnoreRule(resource_type="aws_security_group", id_pattern="sg-0a1b*", reason="scratch")
        ]
    )
    result = decide(
        event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state_of(), DRIFT, cfg
    )
    assert (result.outcome, result.reason) == (Outcome.IGNORED, "scratch")
    other = config(ignore=[IgnoreRule(resource_type="aws_s3_bucket")])
    assert (
        decide(
            event("ec2", "RevokeSecurityGroupIngress"), HUMAN, SG_REF, state_of(), DRIFT, other
        ).outcome
        is Outcome.MANAGED_DRIFT
    )


def test_config_severity_override_by_outcome_and_by_type() -> None:
    drift = config(
        severity_overrides=[SeverityOverride(outcome=Outcome.MANAGED_DRIFT, severity=Severity.INFO)]
    )
    ev = event("ec2", "RevokeSecurityGroupIngress")
    assert decide(ev, HUMAN, SG_REF, state_of(), DRIFT, drift).severity is Severity.INFO
    typed = config(
        severity_overrides=[
            SeverityOverride(outcome=Outcome.MANAGED_DRIFT, severity=Severity.INFO),
            SeverityOverride(
                outcome=Outcome.MANAGED_DRIFT,
                resource_type="aws_security_group",
                severity=Severity.CRITICAL,
            ),
        ]
    )
    assert decide(ev, HUMAN, SG_REF, state_of(), DRIFT, typed).severity is Severity.CRITICAL
    shadow = config(
        severity_overrides=[
            SeverityOverride(outcome=Outcome.SHADOW_CREATE, severity=Severity.WARNING)
        ]
    )
    created = event("ec2", "CreateSecurityGroup")
    assert decide(created, HUMAN, SG_REF, None, None, shadow).severity is Severity.WARNING


def test_config_overrides_never_lower_a_critical_override() -> None:
    cfg = config(
        severity_overrides=[SeverityOverride(outcome=Outcome.MANAGED_DRIFT, severity=Severity.INFO)]
    )
    result = decide(ingress("0.0.0.0/0"), HUMAN, SG_REF, state_of(), DRIFT, cfg)
    assert result.severity is Severity.CRITICAL


def test_config_overrides_do_not_apply_to_ignored_events() -> None:
    cfg = config(
        severity_overrides=[SeverityOverride(outcome=Outcome.IGNORED, severity=Severity.WARNING)]
    )
    ci = Actor(actor_class=ActorClass.CI, display_name="ci")
    result = decide(event("ec2", "RevokeSecurityGroupIngress"), ci, SG_REF, state_of(), DRIFT, cfg)
    assert result.severity is Severity.NONE
