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


def test_example_config_is_valid_once_placeholders_are_replaced(tmp_path: Path) -> None:
    text = (ROOT / "clickops.example.yaml").read_text()
    text = text.replace("<account-id>", "123456789012").replace("<trusted-role>", "ci")
    filled = tmp_path / "clickops.yaml"
    filled.write_text(text)
    assert len(load_config(filled).state_locations) == 2


def test_example_config_placeholders_are_reported() -> None:
    with pytest.raises(ConfigError, match=r"<account-id>.*<trusted-role>|<trusted-role>"):
        load_config(ROOT / "clickops.example.yaml")


def test_placeholder_in_a_comment_is_fine(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(VALID + "# replace <account-id> later\n")
    assert load_config(path).region == "ap-south-1"


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
        VALID + "ignore:\n  - reason: matches everything\n",
        VALID + "ignore:\n  - id_pattern: ''\n",
        VALID + "region: mars\n",
        VALID.replace("arn:aws:iam::123456789012:role/ci", "arn:aws:iam::123456789012:user/bob"),
        "state_locations: [{bucket: '', key: k}]",
        "state_locations: [{bucket: b, key: ''}]",
        "state_locations: [{bucket: 's3://b', key: k}]",
        "state_locations: [{bucket: b, key: /k}]",
        "state_locations: [{bucket: b, key: k, region: mars}]",
    ],
)
def test_invalid_config(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_binary_file(tmp_path: Path) -> None:
    path = tmp_path / "clickops.yaml"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(path)
