"""Core pydantic models shared by the CLI and the Lambda."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActorClass(StrEnum):
    CLICKOPS_SELF = "clickops-self"
    CI = "ci"
    AWS_SERVICE = "aws-service"
    CONSOLE_HUMAN = "console-human"
    CLI_HUMAN = "cli-human"


class Outcome(StrEnum):
    MANAGED_DRIFT = "managed-drift"
    MANAGED_DELETE = "managed-delete"
    SHADOW_CREATE = "shadow-create"
    IGNORED = "ignored"
    TAMPER = "tamper"
    UNRESOLVED = "unresolved"


class Severity(StrEnum):
    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class NormalizedEvent(BaseModel):
    """A CloudTrail write call, reduced to the fields clickops uses."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    time: datetime
    source: str
    name: str
    region: str
    account: str
    user_identity: dict[str, Any] = Field(default_factory=dict)
    request_parameters: dict[str, Any] = Field(default_factory=dict)
    response_elements: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    source_ip: str | None = None
    user_agent: str | None = None


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor_class: ActorClass
    display_name: str
    arn: str | None = None


class ResourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    id: str
    arn: str | None = None
    region: str | None = None

    @property
    def key(self) -> str:
        """Partition key used in the event store, for example ``sg#sg-0abc``."""
        return f"{self.type}#{self.id}"


class Finding(BaseModel):
    event: NormalizedEvent
    actor: Actor
    resource: ResourceRef | None = None
    outcome: Outcome
    severity: Severity
    diff: dict[str, Any] = Field(default_factory=dict)
