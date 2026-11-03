import json
from pathlib import Path

import pytest
from conftest import fixture_paths, load_fixture

from clickops.actors import classify
from clickops.events import normalize
from clickops.models import ActorClass, NormalizedEvent

ACCOUNT = "111122223333"
SELF_ROLE = f"arn:aws:iam::{ACCOUNT}:role/clickops-detector"
TRUSTED = [f"arn:aws:iam::{ACCOUNT}:role/deploy-bot"]

# Fixture file suffix (name.<suffix>.json) -> expected actor class and display name.
EXPECTED = {
    "": (ActorClass.CLI_HUMAN, "asha@example.com"),
    "console": (ActorClass.CONSOLE_HUMAN, "asha@example.com"),
    "ci": (ActorClass.CI, "GitHubActions"),
    "service-linked": (ActorClass.AWS_SERVICE, "AutoScaling"),
    "cloudformation": (ActorClass.AWS_SERVICE, "cloudformation.amazonaws.com"),
    "self": (ActorClass.CLICKOPS_SELF, "clickops-detector"),
}


def _event(service: str, name: str) -> NormalizedEvent:
    event = normalize(load_fixture(service, name))
    assert event is not None
    return event


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_fixture_has_expected_actor(path: Path) -> None:
    suffix = path.stem.split(".", 1)[1] if "." in path.stem else ""
    expected_class, expected_name = EXPECTED[suffix]
    event = normalize(json.loads(path.read_text()))
    assert event is not None
    actor = classify(event, TRUSTED, SELF_ROLE)
    assert actor.actor_class is expected_class
    assert actor.display_name == expected_name


def test_identity_center_person_console_and_cli() -> None:
    cli = classify(_event("ec2", "AuthorizeSecurityGroupIngress"))
    console = classify(_event("ec2", "AuthorizeSecurityGroupIngress.console"))
    assert cli.actor_class is ActorClass.CLI_HUMAN
    assert console.actor_class is ActorClass.CONSOLE_HUMAN
    assert cli.display_name == console.display_name == "asha@example.com"


def test_clickops_ci_matches_by_name_without_config() -> None:
    assert classify(_event("ec2", "AuthorizeSecurityGroupIngress.ci")).actor_class is ActorClass.CI


def test_trusted_role_from_config_is_ci() -> None:
    event = _event("ec2", "AuthorizeSecurityGroupIngress")
    event.user_identity["arn"] = f"arn:aws:sts::{ACCOUNT}:assumed-role/deploy-bot/job-42"
    event.user_identity["sessionContext"]["sessionIssuer"]["arn"] = (
        f"arn:aws:iam::{ACCOUNT}:role/deploy-bot"
    )
    actor = classify(event, TRUSTED)
    assert actor.actor_class is ActorClass.CI
    assert actor.display_name == "job-42"


def test_trusted_role_matches_despite_iam_path() -> None:
    event = _event("ec2", "AuthorizeSecurityGroupIngress")
    event.user_identity["sessionContext"]["sessionIssuer"]["arn"] = (
        f"arn:aws:iam::{ACCOUNT}:role/ci/deploy-bot"
    )
    event.user_identity["arn"] = f"arn:aws:sts::{ACCOUNT}:assumed-role/deploy-bot/x"
    assert classify(event, TRUSTED).actor_class is ActorClass.CI


def test_self_role_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLICKOPS_SELF_ROLE_ARN", raising=False)
    event = _event("iam", "PutRolePolicy.self")
    assert classify(event).actor_class is ActorClass.CLI_HUMAN
    monkeypatch.setenv("CLICKOPS_SELF_ROLE_ARN", SELF_ROLE)
    assert classify(event).actor_class is ActorClass.CLICKOPS_SELF


def test_self_wins_over_ci_and_ci_wins_over_service() -> None:
    event = _event("ec2", "AuthorizeSecurityGroupIngress.ci")
    ci_arn = f"arn:aws:iam::{ACCOUNT}:role/clickops-ci"
    assert classify(event, (), ci_arn).actor_class is ActorClass.CLICKOPS_SELF
    event.user_identity["invokedBy"] = "cloudformation.amazonaws.com"
    assert classify(event).actor_class is ActorClass.CI


def test_aws_service_principal() -> None:
    event = _event("ec2", "StopInstances")
    event.user_identity.clear()
    event.user_identity.update({"type": "AWSService", "invokedBy": "ec2.amazonaws.com"})
    actor = classify(event)
    assert actor.actor_class is ActorClass.AWS_SERVICE
    assert actor.display_name == "ec2.amazonaws.com"


def test_iam_user_and_root_display_names() -> None:
    event = _event("ec2", "StopInstances")
    event.user_identity.clear()
    event.user_identity.update(
        {"type": "IAMUser", "userName": "bob", "arn": f"arn:aws:iam::{ACCOUNT}:user/bob"}
    )
    assert classify(event).display_name == "bob"
    event.user_identity.clear()
    event.user_identity.update({"type": "Root", "arn": f"arn:aws:iam::{ACCOUNT}:root"})
    assert classify(event).display_name == "root"


def test_console_flag_at_top_level_of_record_is_honoured() -> None:
    raw = load_fixture("ec2", "AuthorizeSecurityGroupIngress")
    raw["detail"]["sessionCredentialFromConsole"] = "true"
    event = normalize(raw)
    assert event is not None
    assert classify(event).actor_class is ActorClass.CONSOLE_HUMAN


def test_empty_identity_is_cli_human() -> None:
    event = _event("ec2", "StopInstances")
    event.user_identity.clear()
    assert classify(event).actor_class is ActorClass.CLI_HUMAN
