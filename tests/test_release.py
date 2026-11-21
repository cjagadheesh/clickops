import functools
import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from typer.testing import CliRunner

import clickops
from clickops.cli import app

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()


@functools.cache
def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts" / "release_notes.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pyproject() -> dict:  # type: ignore[type-arg]
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_project_exposes_the_clickops_console_script() -> None:
    assert pyproject()["project"]["scripts"]["clickops"] == "clickops.cli:app"
    assert pyproject()["project"]["requires-python"] == ">=3.12"
    assert pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["clickops"]


def test_version_is_consistent_across_pyproject_package_and_changelog() -> None:
    version = pyproject()["project"]["version"]
    assert version == "0.1.0"
    assert clickops.__version__ == version
    assert f"## [{version}]" in CHANGELOG


def test_version_flag_prints_the_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0 and result.output.strip() == f"clickops {clickops.__version__}"


# --- tag and notes -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v0.1.0", ("0.1.0", False)),
        ("v0.1.0-rc1", ("0.1.0", True)),
        ("v1.20.3-beta.2", ("1.20.3", True)),
    ],
)
def test_parse_tag(tag: str, expected: tuple[str, bool]) -> None:
    assert load().parse_tag(tag) == expected


@pytest.mark.parametrize("tag", ["0.1.0", "v1", "v1.2", "vx.y.z", "v0.1.0rc1", "release-1"])
def test_bad_tags_are_rejected(tag: str) -> None:
    with pytest.raises(load().ReleaseError):
        load().parse_tag(tag)


def test_notes_come_from_the_matching_changelog_section() -> None:
    module = load()
    notes, pre = module.notes_for("v0.1.0", CHANGELOG, "0.1.0")
    assert pre is False
    assert notes.startswith("First release.") and "### Added" in notes
    assert "Keep a Changelog" not in notes and "## [" not in notes


def test_a_pre_release_uses_the_base_version_section_and_says_so() -> None:
    notes, pre = load().notes_for("v0.1.0-rc1", CHANGELOG, "0.1.0")
    assert pre is True and notes.startswith("Pre-release of 0.1.0.")
    assert "### Known limitations" in notes


def test_only_the_requested_section_is_returned() -> None:
    text = "# Changelog\n\n## [0.2.0] - x\n\nnew\n\n## [0.1.0] - y\n\nold\n"
    module = load()
    assert module.changelog_section(text, "0.2.0") == "new\n"
    assert module.changelog_section(text, "0.1.0") == "old\n"


def test_a_tag_that_does_not_match_the_project_version_fails() -> None:
    module = load()
    with pytest.raises(module.ReleaseError, match="does not match"):
        module.notes_for("v0.2.0", CHANGELOG, "0.1.0")
    with pytest.raises(module.ReleaseError, match="no section"):
        module.notes_for("v0.2.0", CHANGELOG, "0.2.0")


def test_main_prints_notes_and_the_prerelease_flag(capsys: pytest.CaptureFixture[str]) -> None:
    module = load()
    assert module.main(["--tag", "v0.1.0-rc1", "--prerelease-flag"]) == 0
    assert capsys.readouterr().out.strip() == "true"
    assert module.main(["--tag", "v0.1.0", "--prerelease-flag"]) == 0
    assert capsys.readouterr().out.strip() == "false"
    assert (
        module.main(
            [
                "--tag",
                "v0.1.0",
                "--changelog",
                str(ROOT / "CHANGELOG.md"),
                "--pyproject",
                str(ROOT / "pyproject.toml"),
            ]
        )
        == 0
    )
    assert "First release." in capsys.readouterr().out
    assert module.main(["--tag", "v9.9.9"]) == 1


# --- workflow ----------------------------------------------------------------------------------


def workflow() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())


def test_release_runs_on_version_tags_and_can_write_releases() -> None:
    wf = workflow()
    assert wf[True]["push"]["tags"] == ["v*"]
    assert wf["permissions"]["contents"] == "write"


def test_release_checks_builds_and_attaches_both_files() -> None:
    steps = workflow()["jobs"]["release"]["steps"]
    text = "\n".join(str(s.get("run", "")) for s in steps)
    order = [
        text.index(x)
        for x in (
            "make check",
            "release_notes.py",
            "uv build --wheel",
            "build_lambda.sh",
            "smoke_install.sh",
            "gh release create",
        )
    ]
    assert order == sorted(order)
    assert "dist/*.whl" in text and "dist/clickops-detector-*.zip" in text
    assert "--notes-file release-notes.md" in text and "--prerelease" in text
    assert "SHA256SUMS" in text


def test_release_secrets_are_not_stored_in_the_workflow() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "secrets.GITHUB_TOKEN" in text
    assert "AWS_ACCESS_KEY_ID" not in text


def test_smoke_script_installs_in_a_clean_environment_and_runs_doctor() -> None:
    text = (ROOT / "scripts" / "smoke_install.sh").read_text()
    assert "clickops --version" in text and 'clickops" doctor' in text
    assert "uv venv" in text and "mktemp -d" in text
