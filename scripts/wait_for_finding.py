"""Wait for the detector to store a finding, then check its outcome and severity.

Used by the live end-to-end runs: it polls the events table through the day index until an item
for the resource and event appears, prints the measured delay and fails if the outcome or
severity differ from what was expected.

    uv run python scripts/wait_for_finding.py --resource sg#sg-0abc \
        --event AuthorizeSecurityGroupIngress --since 2026-10-26T10:00:00Z \
        --expect-outcome managed-drift --expect-severity critical
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from clickops import store


def find_item(table: Any, since: datetime, resource: str, event: str) -> dict[str, Any] | None:
    for item in store.query_since(table, since, datetime.now(UTC)):
        if item.get(store.HASH_KEY) == resource and item.get("event_name") == event:
            return item
    return None


def wait(
    table: Any,
    *,
    since: datetime,
    resource: str,
    event: str,
    timeout: float = 900,
    interval: float = 15,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any] | None, float]:
    """The stored item (or None on timeout) and the seconds waited."""
    started = clock()
    while True:
        item = find_item(table, since, resource, event)
        waited = clock() - started
        if item is not None or waited >= timeout:
            return item, waited
        sleep(interval)


def check(item: dict[str, Any], outcome: str | None, severity: str | None) -> list[str]:
    problems = []
    if outcome and item.get("outcome") != outcome:
        problems.append(f"outcome is {item.get('outcome')}, expected {outcome}")
    if severity and item.get("severity") != severity:
        problems.append(f"severity is {item.get('severity')}, expected {severity}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True, help="resource key, for example sg#sg-0abc")
    parser.add_argument("--event", required=True, help="CloudTrail event name")
    parser.add_argument("--since", required=True, help="UTC time the change was made")
    parser.add_argument("--expect-outcome")
    parser.add_argument("--expect-severity")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--label", default="", help="name of the scenario, kept in the output")
    parser.add_argument("--append", type=Path, help="also append the JSON result to this file")
    parser.add_argument("--region", default="ap-south-1")
    args = parser.parse_args(argv)

    since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    table = boto3.resource("dynamodb", region_name=args.region).Table(store.TABLE_NAME)
    item, waited = wait(
        table, since=since, resource=args.resource, event=args.event, timeout=args.timeout
    )
    expected = {"expect_outcome": args.expect_outcome, "expect_severity": args.expect_severity}
    if item is None:
        problems = ["no finding stored before the timeout"]
        result: dict[str, Any] = {
            "label": args.label,
            "found": False,
            "waited_seconds": round(waited),
            "problems": problems,
            **expected,
        }
    else:
        problems = check(item, args.expect_outcome, args.expect_severity)
        result = {
            "label": args.label,
            "found": True,
            "delay_seconds": round(datetime.now(UTC).timestamp() - since.timestamp()),
            "actor": f"{item.get('actor_name')} ({item.get('actor_class')})",
            "outcome": item.get("outcome"),
            "severity": item.get("severity"),
            "problems": problems,
            **expected,
        }
    line = json.dumps(result)
    print(line)
    if args.append:
        with args.append.open("a") as fh:
            fh.write(line + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
