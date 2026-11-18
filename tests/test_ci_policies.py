"""The clickops-ci permission templates stay small, named and free of broad wildcards."""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
POLICIES = ROOT / "infra" / "bootstrap" / "policies"
VALUES = {
    "account_id": "111122223333",
    "region": "ap-south-1",
    "state_bucket": "clickops-tfstate-111122223333",
}
TEMPLATES = sorted(POLICIES.glob("*.json.tftpl"))
READ = ("Describe", "List", "Get")
# Calls that AWS only lets you allow on Resource "*", and why.
STAR_ALLOWED = {
    "cloudtrail:DescribeTrails",
    "logs:DescribeLogGroups",
    "cloudwatch:DescribeAlarms",
    "route53:CreateHostedZone",
    "route53:ListHostedZones",
    "route53:ListHostedZonesByName",
    "route53:GetChange",
    "kms:ListAliases",
    "access-analyzer:ValidatePolicy",
}


def render(path: Path) -> dict[str, Any]:
    text = re.sub(r"\$\{(\w+)\}", lambda m: VALUES[m.group(1)], path.read_text())
    loaded = json.loads(text)
    assert isinstance(loaded, dict)
    return loaded


def statements(path: Path) -> list[dict[str, Any]]:
    return list(render(path)["Statement"])


def as_list(value: Any) -> list[str]:
    return value if isinstance(value, list) else [value]


def test_every_template_renders_to_valid_json() -> None:
    assert len(TEMPLATES) == 5
    for path in TEMPLATES:
        assert render(path)["Version"] == "2012-10-17"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_policy_fits_the_managed_policy_size_limit(path: Path) -> None:
    compact = "".join(json.dumps(render(path)).split())
    assert len(compact) < 6144


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_no_wildcard_actions(path: Path) -> None:
    for statement in statements(path):
        for action in as_list(statement["Action"]):
            assert "*" not in action, f"{path.name}: {statement['Sid']} allows {action}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_star_resources_only_for_calls_aws_cannot_scope(path: Path) -> None:
    for statement in statements(path):
        if "*" not in as_list(statement["Resource"]):
            continue
        for action in as_list(statement["Action"]):
            assert action in STAR_ALLOWED or action.split(":")[1].startswith(READ), (
                f"{path.name}: {action} on Resource *"
            )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_resources_stay_in_this_account_and_region(path: Path) -> None:
    for statement in statements(path):
        for resource in as_list(statement["Resource"]):
            if resource == "*":
                continue
            assert resource.startswith("arn:aws:"), resource
            if ":s3:::" in resource or "arn:aws:iam::aws:" in resource:
                continue
            if resource == "arn:aws:ec2:ap-south-1::image/*":  # AMIs have no account ID
                continue
            assert "111122223333" in resource or ":route53:::" in resource, resource
            assert not re.search(r":(?!ap-south-1|us-east-1)[a-z]{2}-[a-z]+-\d:", resource)


def test_iam_role_actions_are_limited_to_the_three_clickops_roles() -> None:
    path = POLICIES / "ci_iam_lambda.json.tftpl"
    roles = {
        "arn:aws:iam::111122223333:role/clickops-sandbox-app",
        "arn:aws:iam::111122223333:role/clickops-detector",
        "arn:aws:iam::111122223333:role/clickops-event-forwarder",
    }
    for statement in statements(path):
        if any(a.startswith("iam:") for a in as_list(statement["Action"])):
            assert set(as_list(statement["Resource"])) <= roles, statement["Sid"]


def test_attaching_policies_is_limited_to_the_lambda_logging_policy() -> None:
    attach = [
        s
        for s in statements(POLICIES / "ci_iam_lambda.json.tftpl")
        if "iam:AttachRolePolicy" in as_list(s["Action"])
    ]
    assert len(attach) == 1
    condition = attach[0]["Condition"]["ArnEquals"]["iam:PolicyARN"]
    assert condition == ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"]


def test_pass_role_names_the_service_it_may_pass_to() -> None:
    for statement in statements(POLICIES / "ci_iam_lambda.json.tftpl"):
        if "iam:PassRole" in as_list(statement["Action"]):
            assert "iam:PassedToService" in statement["Condition"]["StringEquals"]


def test_state_access_is_limited_to_the_two_roots() -> None:
    objects = next(
        s for s in statements(POLICIES / "ci_state_s3.json.tftpl") if s["Sid"] == "StateObjects"
    )
    assert sorted(as_list(objects["Resource"])) == [
        "arn:aws:s3:::clickops-tfstate-111122223333/detector/*",
        "arn:aws:s3:::clickops-tfstate-111122223333/sandbox/*",
    ]


def test_ec2_writes_are_pinned_to_the_region() -> None:
    for statement in statements(POLICIES / "ci_ec2.json.tftpl"):
        assert statement["Condition"]["StringEquals"]["aws:RequestedRegion"] == "ap-south-1"


def test_no_admin_or_non_clickops_services_are_granted() -> None:
    granted = {a for p in TEMPLATES for s in statements(p) for a in as_list(s["Action"])}
    assert not {
        a
        for a in granted
        if a.startswith(("iam:CreateUser", "iam:CreatePolicy", "organizations:", "sts:"))
    }
    assert "iam:PutRolePolicy" in granted  # needed for the sandbox and detector roles only


def test_bootstrap_terraform_attaches_all_templates() -> None:
    tf = (ROOT / "infra" / "bootstrap" / "ci_role.tf").read_text()
    for path in TEMPLATES:
        assert f'"{path.name.removesuffix(".json.tftpl")}"' in tf
    assert "templatefile(" in tf and "aws_iam_role_policy_attachment" in tf
    assert 'resource "aws_iam_role_policy" "ci"' not in tf  # the old broad inline policy is gone


# --- scripts/validate_policies.py --------------------------------------------------------------


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_policies", ROOT / "scripts" / "validate_policies.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


class FakeAnalyzer:
    def __init__(self, findings: list[dict[str, str]]) -> None:
        self.findings = findings
        self.calls: list[dict[str, Any]] = []

    def get_paginator(self, name: str) -> "FakeAnalyzer":
        assert name == "validate_policy"
        return self

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return [{"findings": self.findings}]


def finding(kind: str) -> dict[str, str]:
    return {"findingType": kind, "issueCode": "X", "findingDetails": "details"}


def test_validator_reads_every_template_and_fails_only_on_errors_and_security_warnings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_script()
    policies = module.template_policies(POLICIES)
    assert len(policies) == 5 and "${" not in policies[0].document
    clean = FakeAnalyzer([finding("SUGGESTION"), finding("WARNING")])
    assert module.run(clean, policies) == 0
    assert all(c["policyType"] == "IDENTITY_POLICY" for c in clean.calls)
    bad = FakeAnalyzer([finding("ERROR")])
    assert module.run(bad, policies) == 5
    assert "ERROR" in capsys.readouterr().out
    assert module.run(FakeAnalyzer([finding("SECURITY_WARNING")]), policies) == 5


def test_validator_extracts_policies_from_a_terraform_plan() -> None:
    module = load_script()
    plan = {
        "resource_changes": [
            {
                "address": "aws_iam_role_policy.x",
                "type": "aws_iam_role_policy",
                "change": {"after": {"policy": '{"Version": "2012-10-17"}'}},
            },
            {
                "address": "aws_iam_role.r",
                "type": "aws_iam_role",
                "change": {"after": {"assume_role_policy": '{"Version": "2012-10-17"}'}},
            },
            {
                "address": "aws_iam_policy.unknown",
                "type": "aws_iam_policy",
                "change": {"after": {"policy": None}},
            },
            {"address": "aws_s3_bucket.b", "type": "aws_s3_bucket", "change": {"after": {}}},
        ]
    }
    found = module.plan_policies(plan)
    assert [(p.source, p.kind) for p in found] == [
        ("aws_iam_role_policy.x.policy", "identity"),
        ("aws_iam_role.r.assume_role_policy", "trust"),
    ]
    fake = FakeAnalyzer([])
    module.run(fake, found)
    assert fake.calls[1]["validatePolicyResourceType"] == "AWS::IAM::AssumeRolePolicyDocument"
    assert fake.calls[1]["policyType"] == "RESOURCE_POLICY"


def test_threat_model_covers_each_role_and_the_known_gaps() -> None:
    text = (ROOT / "docs" / "threat-model.md").read_text()
    for needle in (
        "clickops-ci",
        "clickops-detector",
        "clickops-event-forwarder",
        "read the Terraform state",
        "Slack webhook",
        "does not protect against",
        "clickops:ignore=true",
        "Access Analyzer",
    ):
        assert needle in text, needle


def test_workflow_validates_plans_and_templates_with_access_analyzer() -> None:
    text = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    assert "validate_policies.py --plan" in text
    assert "validate_policies.py --templates infra/bootstrap/policies" in text
    assert "terraform show -json tfplan" in text and "-out=tfplan" in text
