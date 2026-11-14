"""Slack and email alerts for findings, with a 10-minute repeat window per resource and actor."""

from __future__ import annotations

import json
import logging
import os
import shlex
import time
import urllib.request
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from clickops.models import ActorClass, Finding, Outcome, Severity

logger = logging.getLogger("clickops")
# botocore's debug logging prints response bodies, which would include the webhook URL.
logging.getLogger("botocore").setLevel(logging.WARNING)

SLACK_PARAM_ENV = "CLICKOPS_SLACK_PARAM"
DEFAULT_SLACK_PARAM = "/clickops/slack-webhook"
TOPIC_ENV = "CLICKOPS_CRITICAL_TOPIC_ARN"
DEDUP_WINDOW_SECONDS = 600
DEDUP_TTL_SECONDS = 3600
MAX_DIFF_LINES = 14
MAX_DIFF_CHARS = 2500

_SEVERITY_ICON = {Severity.CRITICAL: "🔴", Severity.WARNING: "🟠", Severity.INFO: "🔵"}
_TITLES = {
    Outcome.MANAGED_DRIFT: "Terraform-managed resource changed outside Terraform",
    Outcome.MANAGED_DELETE: "Terraform-managed resource deleted outside Terraform",
    Outcome.SHADOW_CREATE: "Resource created outside Terraform",
    Outcome.TAMPER: "clickops itself was tampered with",
}
_SOURCES = {
    ActorClass.CONSOLE_HUMAN: "AWS console",
    ActorClass.CLI_HUMAN: "CLI or API",
}


def should_alert(finding: Finding) -> bool:
    """Ignored and unresolved findings are stored but never alerted."""
    return finding.severity is not Severity.NONE and finding.outcome in _TITLES


# --- rendering --------------------------------------------------------------------------------


def _lines_for(field: str, state: Any, live: Any) -> list[str]:
    out = [f"{field}:"]
    if isinstance(state, list) and isinstance(live, list):
        out += [f"  + {item}" for item in live if item not in state]
        out += [f"  - {item}" for item in state if item not in live]
    elif isinstance(state, dict) and isinstance(live, dict):
        for key in sorted(set(state) | set(live)):
            if key not in state:
                out.append(f"  + {key}")
            elif key not in live:
                out.append(f"  - {key}")
            elif state[key] != live[key]:
                out.append(f"  ~ {key}")
    else:
        out += [f"  - {json.dumps(state, default=str)}", f"  + {json.dumps(live, default=str)}"]
    return out


def format_diff(diff: dict[str, Any]) -> str:
    """A short diff, ``-`` for what Terraform expects and ``+`` for what is live."""
    lines: list[str] = []
    for field, change in diff.items():
        lines += _lines_for(field, change.get("state"), change.get("live"))
    clipped = lines[:MAX_DIFF_LINES]
    text = "\n".join(clipped)
    if len(lines) > MAX_DIFF_LINES or len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + f"\n... ({len(lines) - len(clipped)} more lines)"
    return text


def restore_command(targets: list[str]) -> str | None:
    if not targets:
        return None
    return "terraform apply " + " ".join(f"-target={shlex.quote(t)}" for t in targets)


def _source(finding: Finding) -> str:
    return _SOURCES.get(finding.actor.actor_class, finding.actor.actor_class.value)


def render_slack(
    finding: Finding, reason: str = "", targets: list[str] | None = None, repeats: int = 0
) -> dict[str, Any]:
    """Block Kit payload (with a plain-text fallback) for one finding."""
    icon = _SEVERITY_ICON.get(finding.severity, "⚪")
    title = _TITLES.get(finding.outcome, finding.outcome.value)
    resource = finding.resource.key if finding.resource else "unknown"
    actor = finding.actor
    fields = [
        {"type": "mrkdwn", "text": f"*Severity*\n{finding.severity.value}"},
        {"type": "mrkdwn", "text": f"*Outcome*\n{finding.outcome.value}"},
        {"type": "mrkdwn", "text": f"*Resource*\n`{resource}`"},
        {"type": "mrkdwn", "text": f"*Who*\n{actor.display_name} ({_source(finding)})"},
        {"type": "mrkdwn", "text": f"*Event*\n{finding.event.name}"},
        {"type": "mrkdwn", "text": f"*When (UTC)*\n{finding.event.time:%Y-%m-%d %H:%M:%S}"},
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{icon} {title}"[:150]}},
        {"type": "section", "fields": fields},
    ]
    if finding.diff:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{format_diff(finding.diff)}```"},
            }
        )
    if command := restore_command(targets or []):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Restore the coded state*\n```{command}```"},
            }
        )
    context = [reason] if reason else []
    if repeats:
        context.append(f"{repeats} similar event(s) suppressed since the last alert")
    if context:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context)}]}
        )
    fallback = f"{icon} {finding.severity.value}: {title} - {resource} by {actor.display_name}"
    return {"text": fallback, "blocks": blocks}


def render_email(
    finding: Finding, reason: str = "", targets: list[str] | None = None
) -> tuple[str, str]:
    """Subject and plain-text body for a critical finding."""
    resource = finding.resource.key if finding.resource else "unknown"
    subject = f"[clickops critical] {finding.outcome.value}: {resource}"[:100]
    lines = [
        _TITLES.get(finding.outcome, finding.outcome.value),
        "",
        f"Resource: {resource}",
        f"Who:      {finding.actor.display_name} ({_source(finding)})",
        f"Event:    {finding.event.name} at {finding.event.time:%Y-%m-%d %H:%M:%S} UTC",
    ]
    if reason:
        lines.append(f"Why:      {reason}")
    if finding.diff:
        lines += ["", "Changes (- coded, + live):", format_diff(finding.diff)]
    if command := restore_command(targets or []):
        lines += ["", "To restore the coded state:", command]
    return subject, "\n".join(lines)


# --- delivery ---------------------------------------------------------------------------------


def post_json(url: str, payload: dict[str, Any]) -> None:
    """POST a JSON payload to a webhook, raising on any failure."""
    if not url.startswith("https://"):
        raise ValueError("Slack webhook must be an https URL")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status >= 300:
            raise RuntimeError(f"Slack webhook returned HTTP {response.status}")


class Notifier:
    """Sends findings to Slack and, for critical ones, to the email topic."""

    def __init__(
        self,
        table: Any,
        *,
        ssm: Any = None,
        sns: Any = None,
        post: Callable[[str, dict[str, Any]], None] = post_json,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._table = table
        self._ssm = ssm
        self._sns = sns
        self._post = post
        self._clock = clock
        self._webhook: str | None = None

    # The webhook URL is a secret: it is cached in memory and never logged.
    def _webhook_url(self) -> str | None:
        if self._webhook is None:
            ssm = self._ssm or boto3.client("ssm")
            name = os.environ.get(SLACK_PARAM_ENV, DEFAULT_SLACK_PARAM)
            try:
                self._webhook = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"][
                    "Value"
                ]
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ParameterNotFound":
                    raise
                logger.warning("slack webhook parameter %s is not set; skipping Slack", name)
                return None
        return self._webhook

    @staticmethod
    def _dedup_key(finding: Finding) -> str:
        resource = finding.resource.key if finding.resource else finding.event.name
        return f"alert#{resource}#{finding.actor.display_name}"

    def _suppress_repeat(self, key: str, now: int) -> bool:
        """Count a repeat inside the window and return True, or False when a new alert is due."""
        try:
            self._table.update_item(
                Key={"resource_key": key, "sk": "window"},
                UpdateExpression="ADD #n :one",
                ConditionExpression="attribute_exists(window_start) AND window_start > :cutoff",
                ExpressionAttributeNames={"#n": "repeats"},
                ExpressionAttributeValues={":one": 1, ":cutoff": now - DEDUP_WINDOW_SECONDS},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def _open_window(self, key: str, now: int) -> int:
        """Start a new window; returns how many repeats the previous window suppressed."""
        old = self._table.put_item(
            Item={
                "resource_key": key,
                "sk": "window",
                "window_start": now,
                "repeats": 0,
                "expires_at": now + DEDUP_TTL_SECONDS,
            },
            ReturnValues="ALL_OLD",
        ).get("Attributes", {})
        return int(old.get("repeats", 0))

    def notify(self, finding: Finding, reason: str = "", targets: list[str] | None = None) -> str:
        """Alert for a finding. Returns ``sent``, ``suppressed`` or ``skipped``."""
        if not should_alert(finding):
            return "skipped"
        key, now = self._dedup_key(finding), int(self._clock())
        if self._suppress_repeat(key, now):
            return "suppressed"
        repeats = self._previous_repeats(key)
        if url := self._webhook_url():
            self._post(url, render_slack(finding, reason, targets, repeats))
        topic = os.environ.get(TOPIC_ENV)
        if finding.severity is Severity.CRITICAL and topic:
            subject, body = render_email(finding, reason, targets)
            (self._sns or boto3.client("sns")).publish(
                TopicArn=topic, Subject=subject, Message=body
            )
        self._open_window(key, now)
        return "sent"

    def _previous_repeats(self, key: str) -> int:
        item = self._table.get_item(Key={"resource_key": key, "sk": "window"}).get("Item", {})
        return int(item.get("repeats", 0))
