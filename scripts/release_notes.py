"""Release helpers: map a tag to a version and extract that version's CHANGELOG notes.

    uv run python scripts/release_notes.py --tag v0.1.0-rc1 --changelog CHANGELOG.md \
        --pyproject pyproject.toml > notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

TAG = re.compile(r"^v(?P<base>\d+\.\d+\.\d+)(?P<pre>-[0-9A-Za-z.-]+)?$")


class ReleaseError(Exception):
    """The tag, the project version or the changelog do not line up."""


def parse_tag(tag: str) -> tuple[str, bool]:
    """(version without the pre-release suffix, is it a pre-release) for a tag like v0.1.0-rc1."""
    match = TAG.match(tag)
    if not match:
        raise ReleaseError(f"tag {tag!r} must look like v1.2.3 or v1.2.3-rc1")
    return match["base"], bool(match["pre"])


def project_version(pyproject: Path) -> str:
    return str(tomllib.loads(pyproject.read_text())["project"]["version"])


def changelog_section(changelog: str, version: str) -> str:
    """The body of the ``## [version]`` section."""
    heading = re.compile(rf"^## \[{re.escape(version)}\].*$", re.M)
    start = heading.search(changelog)
    if not start:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}")
    rest = changelog[start.end() :]
    nxt = re.search(r"^## \[", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip() + "\n"


def notes_for(tag: str, changelog: str, pyproject_version: str) -> tuple[str, bool]:
    """Release notes for a tag, checking the tag matches the project version."""
    base, prerelease = parse_tag(tag)
    if base != pyproject_version:
        raise ReleaseError(f"tag {tag} does not match the project version {pyproject_version}")
    notes = changelog_section(changelog, base)
    if prerelease:
        notes = f"Pre-release of {base}.\n\n{notes}"
    return notes, prerelease


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument(
        "--prerelease-flag", action="store_true", help="print only 'true' or 'false' for the tag"
    )
    args = parser.parse_args(argv)
    try:
        if args.prerelease_flag:
            print(str(parse_tag(args.tag)[1]).lower())
            return 0
        notes, _ = notes_for(args.tag, args.changelog.read_text(), project_version(args.pyproject))
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
