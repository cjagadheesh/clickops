from pathlib import Path

import pytest

from clickops.config import ConfigError, load_config
from clickops.models import Outcome, Severity

ROOT = Path(__file__).resolve().parent.parent

VALID = """
state_locations:
  - bucket: b
    key: sandbox/terraform.tfstate
trusted_roles:
  - arn:aws:iam::123456789012:role/ci
severity_overrides:
  - outcome: shadow-create
    severity: warning
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "clickops.yaml"
    path.write_text(text)
    return path


def test_valid_config(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.region == "ap-south-1"
    assert cfg.state_locations[0].bucket == "b"
    assert cfg.severity_overrides[0].outcome is Outcome.SHADOW_CREATE
    assert cfg.severity_overrides[0].severity is Severity.WARNING


def test_example_config_is_valid() -> None:
    cfg = load_config(ROOT / "clickops.example.yaml")
    assert len(cfg.state_locations) == 2


@pytest.mark.parametrize(
    "text",
    [
        "just a string",
        "state_locations: []",
        "state_locations: [{bucket: b}]",
        VALID + "unknown_key: 1\n",
        VALID.replace("arn:aws:iam::123456789012:role/ci", "not-an-arn"),
        VALID.replace("severity: warning", "severity: loud"),
        "state_locations: [unclosed",
    ],
)
def test_invalid_config(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")
