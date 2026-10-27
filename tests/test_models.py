from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clickops.models import (
    Actor,
    ActorClass,
    Finding,
    NormalizedEvent,
    Outcome,
    ResourceRef,
    Severity,
)


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        event_id="e1",
        time=datetime(2026, 10, 26, tzinfo=UTC),
        source="ec2.amazonaws.com",
        name="AuthorizeSecurityGroupIngress",
        region="ap-south-1",
        account="123456789012",
    )


def test_resource_key() -> None:
    assert ResourceRef(type="sg", id="sg-0abc").key == "sg#sg-0abc"


def test_finding_round_trips_through_json() -> None:
    finding = Finding(
        event=_event(),
        actor=Actor(actor_class=ActorClass.CLI_HUMAN, display_name="asha"),
        resource=ResourceRef(type="sg", id="sg-0abc", region="ap-south-1"),
        outcome=Outcome.MANAGED_DRIFT,
        severity=Severity.WARNING,
        diff={"ingress": {"added": ["tcp/22 0.0.0.0/0"]}},
    )
    assert Finding.model_validate_json(finding.model_dump_json()) == finding


def test_invalid_outcome_rejected() -> None:
    with pytest.raises(ValidationError):
        Finding(
            event=_event(),
            actor=Actor(actor_class=ActorClass.CI, display_name="ci"),
            outcome="bogus",  # type: ignore[arg-type]
            severity=Severity.NONE,
        )


def test_event_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _event().name = "x"  # type: ignore[misc]
