"""The README keeps the planned section order, and everything it points to exists."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()

SECTIONS = [
    "The problem",
    "Demo",
    "What it detects",
    "Architecture",
    "Quickstart",
    "Cost",
    "Security model",
    "Limitations",
    "How it differs from a scheduled `terraform plan`",
]


def test_sections_in_planned_order() -> None:
    headings = re.findall(r"^## (.+)$", README, flags=re.MULTILINE)
    positions = [headings.index(name) for name in SECTIONS]
    assert positions == sorted(positions)


def test_relative_links_resolve() -> None:
    targets = re.findall(r"\]\((?!https?:|#)([^)#]+)", README)
    missing = [t for t in targets if not (ROOT / t).exists() and t != "demo/demo.gif"]
    assert missing == []


def test_demo_gif_is_the_only_missing_link() -> None:
    # The GIF is recorded by the owner; when it exists this test is no longer needed.
    assert "demo/demo.gif" in README


def test_architecture_diagram_is_mermaid() -> None:
    assert "```mermaid" in README


def test_quickstart_has_five_numbered_steps() -> None:
    quick = README.split("## Quickstart")[1].split("\n## ")[0]
    assert re.findall(r"^(\d)\. \*\*", quick, flags=re.MULTILINE) == ["1", "2", "3", "4", "5"]


def test_quickstart_files_and_scripts_exist() -> None:
    quick = README.split("## Quickstart")[1].split("\n## ")[0]
    for script in set(re.findall(r"scripts/[\w.]+", quick)):
        assert (ROOT / script).is_file(), script
    for example in re.findall(r"([\w.]+\.example(?:\.yaml)?)", quick):
        found = list(ROOT.rglob(example))
        assert found, example


def test_limitations_are_stated() -> None:
    limits = README.split("## Limitations")[1].split("\n## ")[0]
    for phrase in (
        "Six resource types",
        "One AWS account",
        "ap-south-1",
        "few minutes",
        "never reverts",
    ):
        assert phrase in limits


def test_demo_tape_runs_the_planned_commands() -> None:
    tape = (ROOT / "demo" / "demo.tape").read_text()
    assert (
        tape.index("clickops scan") < tape.index("clickops import") < tape.index("clickops events")
    )
    for helper in ("prepare.sh", "cleanup.sh"):
        assert (ROOT / "demo" / helper).is_file()
