import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from test_importer import GENERATED, FakeTerraform
from typer.testing import CliRunner

from clickops import importer, store
from clickops.cli import app, pick_resources
from clickops.scan import ShadowResource

REGION = "ap-south-1"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        for bucket in ("tfstate", "coded", "clicked", "other-clicked"):
            s3.create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION}
            )
        state = {
            "version": 4,
            "resources": [
                {
                    "mode": "managed",
                    "type": "aws_s3_bucket",
                    "name": name,
                    "instances": [{"attributes": {"id": name}}],
                }
                for name in ("tfstate", "coded")
            ],
        }
        s3.put_object(Bucket="tfstate", Key="s.tfstate", Body=json.dumps(state))
        boto3.client("dynamodb", region_name=REGION).create_table(**store.TABLE_DEFINITION)
        config = tmp_path / "clickops.yaml"
        config.write_text("state_locations:\n  - bucket: tfstate\n    key: s.tfstate\n")
        yield config, tmp_path / "imports"


def invoke(config: Path, out: Path, *extra: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(
        app, ["import", "--config", str(config), "--out", str(out), *extra], env={"COLUMNS": "200"}
    )


def test_pick_resources_by_id_or_type_and_id() -> None:
    items = [ShadowResource("s3", "a"), ShadowResource("sg", "a"), ShadowResource("s3", "b")]
    assert pick_resources(items, []) == items
    assert [r.type for r in pick_resources(items, ["a"])] == ["s3", "sg"]
    assert [(r.type, r.id) for r in pick_resources(items, ["s3/b"])] == [("s3", "b")]
    assert pick_resources(items, ["zzz"]) == []


def test_import_writes_blocks_and_reports_the_plan(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    fake = FakeTerraform()
    monkeypatch.setattr(importer, "run_command", fake)
    result = invoke(config, out, "--only", "s3/clicked")
    assert result.exit_code == 0, result.output
    [folder] = list(out.iterdir())
    assert "to = aws_s3_bucket.clicked" in (folder / "imports.tf").read_text()
    assert "other_clicked" not in (folder / "imports.tf").read_text()
    assert (folder / "generated.tf").read_text() == GENERATED
    assert "1 to import, 0 to add, 0 to change, 0 to destroy" in result.output
    assert "validates" in result.output


def test_import_everything_that_is_unmanaged(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    monkeypatch.setattr(importer, "run_command", FakeTerraform())
    assert invoke(config, out).exit_code == 0
    [folder] = list(out.iterdir())
    text = (folder / "imports.tf").read_text()
    assert text.count("import {") == 2 and "coded" not in text


def test_no_terraform_flag_only_writes_the_blocks(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    fake = FakeTerraform()
    monkeypatch.setattr(importer, "run_command", fake)
    assert invoke(config, out, "--no-terraform").exit_code == 0
    assert fake.calls == []
    [folder] = list(out.iterdir())
    assert not (folder / "generated.tf").exists()


def test_validation_failure_exits_1_and_prints_the_errors(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    fake = FakeTerraform([{"severity": "error", "summary": "Bad", "detail": "reference"}])
    monkeypatch.setattr(importer, "run_command", fake)
    result = invoke(config, out, "--only", "clicked")
    assert result.exit_code == 1
    assert "does not validate" in result.output and "Bad: reference" in result.output
    [folder] = list(out.iterdir())
    assert (folder / "generated.tf").read_text().startswith("# clickops:")


def test_terraform_failure_exits_3_and_keeps_the_import_blocks(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    monkeypatch.setattr(importer, "run_command", FakeTerraform(fail_at="plan"))
    result = invoke(config, out, "--only", "clicked")
    assert result.exit_code == 3
    assert "plan failed" in result.output and "imports.tf" in result.output
    assert (next(out.iterdir()) / "imports.tf").exists()


def test_missing_terraform_exits_3(env) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    result = invoke(config, out, "--only", "clicked", "--terraform", "no-such-terraform-xyz")
    assert result.exit_code == 3 and "install Terraform" in result.output


def test_nothing_to_import(env) -> None:  # type: ignore[no-untyped-def]
    config, out = env
    result = invoke(config, out, "--only", "does-not-exist")
    assert result.exit_code == 0 and "Nothing to import" in result.output
    assert not out.exists()


def test_bad_config_exits_2(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, out = env
    assert invoke(tmp_path / "missing.yaml", out).exit_code == 2
