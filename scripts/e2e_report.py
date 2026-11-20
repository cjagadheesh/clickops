"""Render docs/e2e-results.md from the JSON lines written by scripts/e2e.sh.

uv run python scripts/e2e_report.py --results results.jsonl --out docs/e2e-results.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HEADER = """# End-to-end results

Written by `scripts/e2e.sh`, which makes six real changes to the sandbox as the admin profile,
waits for the detector's finding in `clickops-events` (up to 10 minutes each), checks its outcome
and severity, then reverts. The delay is the time from making the change to the finding being
stored; Slack and email follow within seconds of that.
"""


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def row(result: dict[str, Any]) -> str:
    expected = f"{result.get('expect_outcome')} / {result.get('expect_severity')}"
    if not result.get("found"):
        actual, who, delay = "not found", "", f"> {result.get('waited_seconds', '?')} s"
    else:
        actual = f"{result.get('outcome')} / {result.get('severity')}"
        who = str(result.get("actor", ""))
        delay = f"{result.get('delay_seconds')} s"
    verdict = "pass" if result.get("found") and not result.get("problems") else "FAIL"
    return f"| {result.get('label', '')} | {expected} | {actual} | {who} | {delay} | {verdict} |"


def render(results: list[dict[str, Any]], when: datetime | None = None) -> str:
    scenarios = [r for r in results if r.get("kind") != "revert"]
    reverts = [r for r in results if r.get("kind") == "revert"]
    passed = sum(1 for r in scenarios if r.get("found") and not r.get("problems"))
    when = when or datetime.now(UTC)
    lines = [
        HEADER,
        f"Run on {when:%Y-%m-%d %H:%M} UTC.",
        "",
        "| Scenario | Expected | Stored | Actor | Delay | Result |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [row(r) for r in scenarios]
    delays = [r["delay_seconds"] for r in scenarios if r.get("found")]
    lines += ["", f"{passed} of {len(scenarios)} scenarios passed."]
    if delays:
        lines.append(
            f"Delay: fastest {min(delays)} s, slowest {max(delays)} s, "
            f"mean {round(sum(delays) / len(delays))} s."
        )
    for revert in reverts:
        state = (
            "reverted, and `terraform plan` shows no changes"
            if revert.get("ok")
            else "the revert did not finish cleanly: check `terraform plan` in infra/sandbox"
        )
        lines.append(f"Revert: {state}.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    results = load(args.results)
    args.out.write_text(render(results))
    return 0 if all(r.get("ok", not r.get("problems", [])) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
