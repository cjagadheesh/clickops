import json
import subprocess
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from clickops import doctor as doc
from clickops.cli import app

CFG = """
state_locations:
  - bucket: tfstate
    key: sandbox/terraform.tfstate
"""


@pytest.fixture(autouse=True)
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")


@pytest.mark.parametrize(
    ("out", "expected"),
    [
        (json.dumps({"terraform_version": "1.10.2"}), (1, 10, 2)),
        ("Terraform v1.9.8\non linux", (1, 9, 8)),
        ("garbage", None),
    ],
)
def test_parse_terraform_version(out: str, expected: tuple[int, ...] | None) -> None:
    assert doc.parse_terraform_version(out) == expected


def test_terraform_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    result = doc.check_terraform()
    assert not result.ok
    assert result.hint


def test_config_invalid(tmp_path: Path) -> None:
    result, cfg = doc.check_config(tmp_path / "missing.yaml")
    assert not result.ok
    assert cfg is None


@mock_aws
def test_doctor_all_pass(tmp_path: Path) -> None:
    boto3.client("s3", region_name="ap-south-1").create_bucket(
        Bucket="tfstate", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
    )
    boto3.client("s3", region_name="ap-south-1").put_object(
        Bucket="tfstate", Key="sandbox/terraform.tfstate", Body=b"{}"
    )
    cfg = tmp_path / "clickops.yaml"
    cfg.write_text(CFG)
    ok = doc.CheckResult("Terraform version", True, "1.10.0")
    results = doc.run_checks(cfg, terraform_check=lambda: ok)
    assert all(r.ok for r in results), results
    assert len(results) == 4


@mock_aws
def test_doctor_reports_unreadable_state(tmp_path: Path) -> None:
    cfg = tmp_path / "clickops.yaml"
    cfg.write_text(CFG)
    results = doc.run_checks(cfg, terraform_check=lambda: doc.CheckResult("t", True, "1.10.0"))
    failed = [r for r in results if not r.ok]
    assert len(failed) == 1
    assert failed[0].name.startswith("State s3://tfstate")
    assert failed[0].hint


@mock_aws
def test_doctor_cli_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "clickops.yaml"
    cfg.write_text(CFG)
    monkeypatch.setenv("PATH", "")
    result = CliRunner().invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1
    assert "Terraform version" in result.output
    assert "fail" in result.output


@mock_aws
def test_doctor_cli_survives_brackets_in_errors(tmp_path: Path) -> None:
    # An invalid bucket name makes botocore raise an error whose text contains `[/:]`,
    # which rich would otherwise parse as a markup tag.
    cfg = tmp_path / "clickops.yaml"
    cfg.write_text("state_locations: [{bucket: 'tfstate-<account-id>', key: k}]")
    result = CliRunner().invoke(app, ["doctor", "--config", str(cfg)])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "fail" in result.output


def _terraform_says(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    done = subprocess.CompletedProcess([], 0, stdout, "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)


def test_terraform_too_old(monkeypatch: pytest.MonkeyPatch) -> None:
    _terraform_says(monkeypatch, json.dumps({"terraform_version": "1.9.9"}))
    result = doc.check_terraform()
    assert not result.ok
    assert "older than 1.10" in result.detail


def test_terraform_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    _terraform_says(monkeypatch, "")
    result = doc.check_terraform()
    assert not result.ok
    assert "parse" in result.detail


def test_terraform_new_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    _terraform_says(monkeypatch, json.dumps({"terraform_version": "1.100.0"}))
    assert doc.check_terraform().ok


def test_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    result = doc.check_credentials("ap-south-1")
    assert not result.ok
    assert result.hint
