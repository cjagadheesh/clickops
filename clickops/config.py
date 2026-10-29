"""``clickops.yaml`` model and loader."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from clickops.models import Outcome, Severity


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid."""


class StateLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket: str
    key: str
    region: str = "ap-south-1"


class IgnoreRule(BaseModel):
    """Suppress alerts for resources matching a type and/or id glob."""

    model_config = ConfigDict(extra="forbid")

    resource_type: str | None = None
    id_pattern: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _has_a_matcher(self) -> IgnoreRule:
        if self.resource_type is None and self.id_pattern is None:
            raise ValueError(
                "ignore rule needs resource_type or id_pattern, or it matches everything"
            )
        return self


class SeverityOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    resource_type: str | None = None
    severity: Severity


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: str = "ap-south-1"
    state_locations: list[StateLocation] = Field(min_length=1)
    trusted_roles: list[str] = Field(default_factory=list)
    ignore: list[IgnoreRule] = Field(default_factory=list)
    severity_overrides: list[SeverityOverride] = Field(default_factory=list)

    @field_validator("trusted_roles")
    @classmethod
    def _roles_are_arns(cls, roles: list[str]) -> list[str]:
        for role in roles:
            if not role.startswith("arn:aws:iam::"):
                raise ValueError(f"trusted role must be an IAM ARN: {role}")
        return roles


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} is not a UTF-8 text file") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
