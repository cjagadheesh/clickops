import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clickops import importer
from clickops.importer import ImporterError, TerraformMissing
from clickops.scan import ShadowResource

ZONE = "Z0123456789ABCDEFGHIJ"
RESOURCES = [
    ShadowResource("sg", "sg-0123456789abcdef0", "scratch"),
    ShadowResource("iam-role", "my-role", "my-role"),
    ShadowResource("iam-policy", "arn:aws:iam::111122223333:policy/extra", "extra"),
    ShadowResource("s3", "clicked-bucket", "clicked-bucket"),
    ShadowResource("ec2", "i-0123456789abcdef0", "web box"),
    ShadowResource("lambda", "my-fn", "my-fn"),
    ShadowResource("route53-zone", ZONE, "scratch.internal"),
    ShadowResource("route53-record", f"{ZONE}_app.scratch.internal_A", "app.scratch.internal"),
]


def test_import_blocks_use_each_types_terraform_type_and_import_id() -> None:
    text = importer.render_imports(RESOURCES)
    expected = [
        ("aws_security_group.scratch", "sg-0123456789abcdef0"),
        ("aws_iam_role.my_role", "my-role"),
        ("aws_iam_policy.extra", "arn:aws:iam::111122223333:policy/extra"),
        ("aws_s3_bucket.clicked_bucket", "clicked-bucket"),
        ("aws_instance.web_box", "i-0123456789abcdef0"),
        ("aws_lambda_function.my_fn", "my-fn"),
        ("aws_route53_zone.scratch_internal", ZONE),
        ("aws_route53_record.app_scratch_internal_a", f"{ZONE}_app.scratch.internal_A"),
    ]
    for target, ident in expected:
        assert f'import {{\n  to = {target}\n  id = "{ident}"\n}}' in text
    assert text.count("import {") == len(RESOURCES)


def test_names_are_valid_unique_identifiers() -> None:
    taken: set[tuple[str, str]] = set()
    names = [
        importer.tf_name(ShadowResource("s3", "same-name", "same-name"), taken),
        importer.tf_name(ShadowResource("s3", "same_name", "same_name"), taken),
        importer.tf_name(ShadowResource("s3", "123-bucket", "123-bucket"), taken),
        importer.tf_name(ShadowResource("s3", "***", "***"), taken),
        importer.tf_name(ShadowResource("iam-role", "same-name", "same-name"), taken),
    ]
    assert names == ["same_name", "same_name_2", "r_123_bucket", "imported", "same_name"]


def test_route53_records_of_different_types_get_different_names() -> None:
    a = ShadowResource("route53-record", f"{ZONE}_x.example_A", "x.example")
    txt = ShadowResource("route53-record", f"{ZONE}_x.example_TXT", "x.example")
    text = importer.render_imports([a, txt])
    assert "aws_route53_record.x_example_a" in text and "aws_route53_record.x_example_txt" in text


def test_write_imports_makes_a_timestamped_folder(tmp_path: Path) -> None:
    now = datetime(2026, 10, 26, 10, 15, 30, tzinfo=UTC)
    directory, path = importer.write_imports(RESOURCES[:1], tmp_path / "imports", now)
    assert directory == tmp_path / "imports" / "20261026T101530Z"
    assert path == directory / "imports.tf" and "aws_security_group.scratch" in path.read_text()


def test_providers_file_pins_terraform_and_provider() -> None:
    text = importer.providers_tf("ap-south-1")
    assert 'required_version = ">= 1.10"' in text and 'version = "~> 5.81"' in text
    assert 'region = "ap-south-1"' in text


# --- terraform steps with a fake runner ---------------------------------------------------------

PLAN_OUT = (
    "Terraform will perform the following actions:\n\n"
    "Plan: 1 to import, 0 to add, 0 to change, 0 to destroy.\n"
)
GENERATED = 'resource "aws_s3_bucket" "clicked_bucket" {\n  bucket = "clicked-bucket"\n}\n'


class FakeTerraform:
    def __init__(
        self,
        validate_diagnostics: list[dict[str, str]] | None = None,
        fail_at: str | None = None,
        generate: bool = True,
    ) -> None:
        self.calls: list[list[str]] = []
        self.cwds: list[Path] = []
        self.diagnostics = validate_diagnostics or []
        self.fail_at = fail_at
        self.generate = generate

    def __call__(self, command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        self.cwds.append(cwd)
        step = command[1]
        if step == self.fail_at:
            return subprocess.CompletedProcess(command, 1, "", "Error: boom\nsecond line")
        if step == "plan":
            assert (cwd / "imports.tf").exists() and (cwd / "providers.tf").exists()
            if self.generate:
                (cwd / "generated.tf").write_text(GENERATED)
            return subprocess.CompletedProcess(command, 0, PLAN_OUT, "")
        if step == "validate":
            ok = not self.diagnostics
            out = json.dumps({"valid": ok, "diagnostics": self.diagnostics})
            return subprocess.CompletedProcess(command, 0 if ok else 1, out, "")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def imports_dir(tmp_path: Path) -> Path:
    directory, _ = importer.write_imports(RESOURCES[3:4], tmp_path / "imports")
    return directory


def test_generate_config_runs_init_plan_and_validate_in_order(imports_dir: Path) -> None:
    fake = FakeTerraform()
    result = importer.generate_config(imports_dir, "ap-south-1", runner=fake)
    assert [c[:2] for c in fake.calls] == [
        ["terraform", "init"],
        ["terraform", "plan"],
        ["terraform", "validate"],
    ]
    assert "-generate-config-out=generated.tf" in fake.calls[1]
    assert "-input=false" in fake.calls[0] and "-input=false" in fake.calls[1]
    assert result.plan_summary == "Plan: 1 to import, 0 to add, 0 to change, 0 to destroy."
    assert result.validate_ok is True and result.errors == []
    assert result.generated_path == imports_dir / "generated.tf"
    assert result.generated_path.read_text() == GENERATED
    assert len(set(fake.cwds)) == 1 and fake.cwds[0] != imports_dir  # a temporary directory
    assert not fake.cwds[0].exists()  # and it is cleaned up


def test_nothing_is_applied(imports_dir: Path) -> None:
    fake = FakeTerraform()
    importer.generate_config(imports_dir, "ap-south-1", runner=fake)
    assert all(c[1] not in {"apply", "destroy"} for c in fake.calls)


def test_validation_errors_are_kept_in_a_header_and_reported(imports_dir: Path) -> None:
    fake = FakeTerraform(
        [
            {
                "severity": "error",
                "summary": "Missing required argument",
                "detail": 'The argument "bucket" is required.',
            },
            {"severity": "warning", "summary": "Deprecated", "detail": "x"},
        ]
    )
    result = importer.generate_config(imports_dir, "ap-south-1", runner=fake)
    assert result.validate_ok is False
    assert result.errors == ['Missing required argument: The argument "bucket" is required.']
    text = (imports_dir / "generated.tf").read_text()
    assert text.startswith("# clickops: `terraform validate` reported errors")
    assert '#   - Missing required argument: The argument "bucket" is required.' in text
    assert text.endswith(GENERATED)  # the generated file is kept below the header
    assert "Deprecated" not in text


def test_a_failed_init_or_plan_raises_with_the_tail_of_the_output(imports_dir: Path) -> None:
    with pytest.raises(ImporterError, match="(?s)init failed.*boom"):
        importer.generate_config(imports_dir, "ap-south-1", runner=FakeTerraform(fail_at="init"))
    with pytest.raises(ImporterError, match="(?s)plan failed.*second line"):
        importer.generate_config(imports_dir, "ap-south-1", runner=FakeTerraform(fail_at="plan"))
    assert not (imports_dir / "generated.tf").exists()


def test_missing_generated_file_is_an_error(imports_dir: Path) -> None:
    with pytest.raises(ImporterError, match="did not generate"):
        importer.generate_config(imports_dir, "ap-south-1", runner=FakeTerraform(generate=False))


def test_missing_terraform_binary_is_reported(imports_dir: Path) -> None:
    with pytest.raises(TerraformMissing, match="install Terraform"):
        importer.generate_config(
            imports_dir, "ap-south-1", terraform="definitely-not-terraform-xyz"
        )


def test_validate_output_that_is_not_json_still_gives_an_error() -> None:
    assert importer._validate_errors("Segmentation fault") == ["Segmentation fault"]


def test_live_import_script_needs_confirmation_and_cleans_up() -> None:
    script = (
        Path(__file__).resolve().parent.parent / "scripts" / "test_import_bucket.sh"
    ).read_text()
    assert 'CONFIRM:-}" != "yes"' in script
    assert "trap" in script and "delete-bucket" in script
    assert "1 to import, 0 to add, 0 to change, 0 to destroy" in script
    assert "terraform apply" not in script


def test_generated_output_folder_is_gitignored() -> None:
    root = Path(__file__).resolve().parent.parent
    assert "imports/" in (root / ".gitignore").read_text().split()
