import json
import logging
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from conftest import load_fixture
from moto import mock_aws

from clickops import alerts, store
from clickops.actors import classify
from clickops.events import normalize
from clickops.models import Actor, ActorClass, Finding, Outcome, ResourceRef, Severity

WEBHOOK = "https://hooks.example.test/services/T000/B000/not-a-real-secret"
SG = ResourceRef(type="sg", id="sg-0a1b2c3d4e5f60718")
DIFF = {
    "ingress": {
        "state": ["tcp 443-443 0.0.0.0/0"],
        "live": ["tcp 22-22 0.0.0.0/0", "tcp 443-443 0.0.0.0/0"],
    }
}


def finding(
    outcome: Outcome = Outcome.MANAGED_DRIFT,
    severity: Severity = Severity.CRITICAL,
    fixture: tuple[str, str] = ("ec2", "AuthorizeSecurityGroupIngress"),
    diff: dict[str, Any] | None = None,
    resource: ResourceRef | None = SG,
) -> Finding:
    event = normalize(load_fixture(*fixture))
    assert event is not None
    return Finding(
        event=event,
        actor=classify(event),
        resource=resource,
        outcome=outcome,
        severity=severity,
        diff=DIFF if diff is None else diff,
    )


def texts(payload: dict[str, Any]) -> str:
    return json.dumps(payload["blocks"])


# --- rendering ---------------------------------------------------------------------------------


def test_critical_drift_payload() -> None:
    payload = alerts.render_slack(
        finding(),
        "ingress from the world",
        ["aws_security_group.web", "aws_vpc_security_group_ingress_rule.web_https"],
    )
    blocks = payload["blocks"]
    assert blocks[0]["type"] == "header"
    assert "🔴" in blocks[0]["text"]["text"]
    assert "changed outside Terraform" in blocks[0]["text"]["text"]
    fields = " ".join(f["text"] for f in blocks[1]["fields"])
    for expected in (
        "critical",
        "managed-drift",
        "sg#sg-0a1b2c3d4e5f60718",
        "asha@example.com",
        "CLI or API",
        "AuthorizeSecurityGroupIngress",
        "2026-10-26 10:15:30",
    ):
        assert expected in fields
    diff_block = blocks[2]["text"]["text"]
    assert diff_block.startswith("```") and "+ tcp 22-22 0.0.0.0/0" in diff_block
    assert "- tcp 443" not in diff_block  # still present live, so not removed
    restore = blocks[3]["text"]["text"]
    assert (
        "terraform apply -target=aws_security_group.web "
        "-target=aws_vpc_security_group_ingress_rule.web_https"
    ) in restore
    assert blocks[4]["type"] == "context" and "ingress from the world" in texts(payload)
    assert payload["text"].startswith("🔴 critical:")


def test_console_actor_is_labelled() -> None:
    payload = alerts.render_slack(finding(fixture=("ec2", "AuthorizeSecurityGroupIngress.console")))
    assert "AWS console" in texts(payload)


def test_warning_drift_payload() -> None:
    payload = alerts.render_slack(
        finding(
            severity=Severity.WARNING,
            fixture=("iam", "AttachRolePolicy"),
            diff={"attached_policy_arns": {"state": [], "live": ["arn:x"]}},
        ),
        targets=["aws_iam_role.app"],
    )
    assert "🟠" in payload["blocks"][0]["text"]["text"]
    assert "+ arn:x" in texts(payload)


def test_managed_delete_payload() -> None:
    payload = alerts.render_slack(
        finding(Outcome.MANAGED_DELETE, diff={}, fixture=("ec2", "DeleteSecurityGroup")),
        targets=["aws_security_group.web"],
    )
    assert "deleted outside Terraform" in payload["blocks"][0]["text"]["text"]
    assert "terraform apply -target=aws_security_group.web" in texts(payload)
    assert "```" in texts(payload)  # only the restore block, no diff block
    assert "Changes" not in texts(payload)


def test_shadow_create_payload_has_no_restore_command() -> None:
    payload = alerts.render_slack(
        finding(
            Outcome.SHADOW_CREATE,
            Severity.INFO,
            diff={},
            fixture=("s3", "CreateBucket"),
            resource=ResourceRef(type="s3", id="b"),
        )
    )
    assert "🔵" in payload["blocks"][0]["text"]["text"]
    assert "created outside Terraform" in payload["blocks"][0]["text"]["text"]
    assert "terraform apply" not in texts(payload)


def test_tamper_payload() -> None:
    payload = alerts.render_slack(finding(Outcome.TAMPER, Severity.CRITICAL, diff={}))
    assert "tampered" in payload["blocks"][0]["text"]["text"]


def test_repeat_count_is_shown() -> None:
    assert "3 similar event(s) suppressed" in texts(alerts.render_slack(finding(), repeats=3))


def test_shell_special_targets_are_quoted() -> None:
    command = alerts.restore_command(['aws_route53_record.r["a b"]'])
    assert command == "terraform apply '-target=aws_route53_record.r[\"a b\"]'" or "'" in str(
        command
    )
    assert alerts.restore_command([]) is None


def test_diff_formats() -> None:
    text = alerts.format_diff(
        {
            "ingress": {"state": ["a", "b"], "live": ["b", "c"]},
            "timeout": {"state": 10, "live": 60},
            "inline_policies": {"state": {"read": 1, "gone": 1}, "live": {"read": 2, "new": 1}},
        }
    )
    assert "  + c" in text and "  - a" in text and "  b" not in text
    assert "  - 10" in text and "  + 60" in text
    assert "  ~ read" in text and "  + new" in text and "  - gone" in text


def test_long_diffs_are_clipped() -> None:
    big = {"ingress": {"state": [], "live": [f"tcp {i}-{i} 10.0.0.0/8" for i in range(100)]}}
    text = alerts.format_diff(big)
    assert len(text.splitlines()) <= alerts.MAX_DIFF_LINES + 1
    assert "more lines" in text


def test_email_body_for_critical_finding() -> None:
    subject, body = alerts.render_email(
        finding(), "ingress from the world", ["aws_security_group.web"]
    )
    assert subject == "[clickops critical] managed-drift: sg#sg-0a1b2c3d4e5f60718"
    for expected in (
        "asha@example.com",
        "AuthorizeSecurityGroupIngress",
        "ingress from the world",
        "+ tcp 22-22 0.0.0.0/0",
        "terraform apply -target=aws_security_group.web",
    ):
        assert expected in body


@pytest.mark.parametrize(
    ("outcome", "severity", "expected"),
    [
        (Outcome.MANAGED_DRIFT, Severity.WARNING, True),
        (Outcome.MANAGED_DELETE, Severity.CRITICAL, True),
        (Outcome.SHADOW_CREATE, Severity.INFO, True),
        (Outcome.TAMPER, Severity.CRITICAL, True),
        (Outcome.IGNORED, Severity.NONE, False),
        (Outcome.UNRESOLVED, Severity.NONE, False),
        (Outcome.MANAGED_DRIFT, Severity.NONE, False),
    ],
)
def test_should_alert(outcome: Outcome, severity: Severity, expected: bool) -> None:
    assert alerts.should_alert(finding(outcome, severity)) is expected


# --- delivery ----------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 26, 10, 15, tzinfo=UTC).timestamp()

    def __call__(self) -> float:
        return self.now


class FakeSns:
    def __init__(self) -> None:
        self.published: list[dict[str, str]] = []

    def publish(self, **kwargs: str) -> None:
        self.published.append(kwargs)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("CLICKOPS_CRITICAL_TOPIC_ARN", "arn:aws:sns:ap-south-1:1:clickops-critical")
    monkeypatch.delenv("CLICKOPS_SLACK_PARAM", raising=False)
    with mock_aws():
        boto3.client("dynamodb").create_table(**store.TABLE_DEFINITION)
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name="/clickops/slack-webhook", Type="SecureString", Value=WEBHOOK)
        yield boto3.resource("dynamodb").Table(store.TABLE_NAME), ssm


def notifier(env, posted: list, sns: FakeSns, clock: Clock | None = None):  # type: ignore[no-untyped-def]
    table, ssm = env
    return alerts.Notifier(
        table,
        ssm=ssm,
        sns=sns,
        post=lambda url, payload: posted.append((url, payload)),
        clock=clock or Clock(),
    )


def test_critical_finding_goes_to_slack_and_email(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    sns = FakeSns()
    assert notifier(env, posted, sns).notify(finding(), "why", ["aws_security_group.web"]) == "sent"
    assert len(posted) == 1 and posted[0][0] == WEBHOOK
    assert "terraform apply" in texts(posted[0][1])
    assert sns.published[0]["TopicArn"].endswith(":clickops-critical")
    assert sns.published[0]["Subject"].startswith("[clickops critical]")
    assert "asha@example.com" in sns.published[0]["Message"]


def test_warning_finding_is_slack_only(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    sns = FakeSns()
    assert notifier(env, posted, sns).notify(finding(severity=Severity.WARNING)) == "sent"
    assert len(posted) == 1 and sns.published == []


def test_ignored_finding_sends_nothing(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    sns = FakeSns()
    result = notifier(env, posted, sns).notify(finding(Outcome.IGNORED, Severity.NONE))
    assert result == "skipped" and posted == [] and sns.published == []


def test_repeats_within_ten_minutes_only_update_a_counter(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    sns = FakeSns()
    clock = Clock()
    n = notifier(env, posted, sns, clock)
    assert n.notify(finding()) == "sent"
    clock.now += 120
    assert n.notify(finding()) == "suppressed"
    clock.now += 120
    assert n.notify(finding()) == "suppressed"
    assert len(posted) == 1 and len(sns.published) == 1
    row = env[0].get_item(
        Key={"resource_key": "alert#sg#sg-0a1b2c3d4e5f60718#asha@example.com", "sk": "window"}
    )["Item"]
    assert int(row["repeats"]) == 2


def test_alert_after_the_window_reports_suppressed_repeats(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    sns = FakeSns()
    clock = Clock()
    n = notifier(env, posted, sns, clock)
    n.notify(finding())
    clock.now += 60
    n.notify(finding())
    clock.now += 601
    assert n.notify(finding()) == "sent"
    assert len(posted) == 2
    assert "1 similar event(s) suppressed" in texts(posted[1][1])


def test_other_resources_and_actors_are_not_deduplicated(env) -> None:  # type: ignore[no-untyped-def]
    posted: list = []
    n = notifier(env, posted, FakeSns())
    n.notify(finding())
    n.notify(finding(resource=ResourceRef(type="sg", id="sg-other")))
    other_actor = finding()
    other_actor = other_actor.model_copy(
        update={"actor": Actor(actor_class=ActorClass.CLI_HUMAN, display_name="bob")}
    )
    n.notify(other_actor)
    assert len(posted) == 3


def test_missing_webhook_skips_slack_but_still_emails_critical(env, caplog) -> None:  # type: ignore[no-untyped-def]
    table, ssm = env
    ssm.delete_parameter(Name="/clickops/slack-webhook")
    posted: list = []
    sns = FakeSns()
    with caplog.at_level(logging.WARNING, logger="clickops"):
        assert notifier(env, posted, sns).notify(finding()) == "sent"
    assert posted == [] and len(sns.published) == 1
    assert "not set" in caplog.text


def test_slack_failure_raises_and_a_retry_still_alerts(env) -> None:  # type: ignore[no-untyped-def]
    table, ssm = env
    attempts: list = []

    def flaky(url: str, payload: dict[str, Any]) -> None:
        attempts.append(url)
        if len(attempts) == 1:
            raise RuntimeError("Slack is down")

    n = alerts.Notifier(table, ssm=ssm, sns=FakeSns(), post=flaky, clock=Clock())
    with pytest.raises(RuntimeError):
        n.notify(finding())
    assert n.notify(finding()) == "sent"
    assert len(attempts) == 2


def test_webhook_url_is_never_logged(env, caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.DEBUG):
        notifier(env, [], FakeSns()).notify(finding())
    assert "not-a-real-secret" not in caplog.text


def test_no_topic_configured_means_no_email(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CLICKOPS_CRITICAL_TOPIC_ARN")
    sns = FakeSns()
    notifier(env, [], sns).notify(finding())
    assert sns.published == []


def test_post_json_requires_https() -> None:
    with pytest.raises(ValueError, match="https"):
        alerts.post_json("http://hooks.example.test/x", {})


def test_post_json_sends_json_and_checks_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int) -> Response:
        seen["url"], seen["body"], seen["timeout"] = request.full_url, request.data, timeout
        seen["type"] = request.get_header("Content-type")
        return Response(seen.get("status", 200))

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    alerts.post_json(WEBHOOK, {"text": "hi"})
    assert seen["url"] == WEBHOOK and json.loads(seen["body"]) == {"text": "hi"}
    assert seen["type"] == "application/json" and seen["timeout"] == 5
    seen["status"] = 500
    with pytest.raises(RuntimeError, match="500"):
        alerts.post_json(WEBHOOK, {})
