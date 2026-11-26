#!/usr/bin/env python3
"""Show last month's cost of everything tagged project=clickops, by service.

Makes one Cost Explorer call (AWS bills USD 0.01 per request), so run it deliberately. The tag
must be activated as a cost allocation tag in the Billing console first, or the result is empty.

    AWS_PROFILE=clickops-admin scripts/cost_report.py [YYYY-MM]
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

import boto3


def month_bounds(month: str | None, today: date | None = None) -> tuple[str, str]:
    """Start (inclusive) and end (exclusive) dates of ``month`` (default: the previous one)."""
    today = today or date.today()
    if month:
        year, mon = (int(part) for part in month.split("-"))
    else:
        year, mon = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def summarize(response: dict[str, Any]) -> tuple[list[tuple[str, float]], float]:
    """Per-service costs, largest first, and their total, from a get_cost_and_usage response."""
    totals: dict[str, float] = {}
    for period in response.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            service = group["Keys"][0]
            totals[service] = totals.get(service, 0.0) + float(
                group["Metrics"]["UnblendedCost"]["Amount"]
            )
    rows = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return rows, sum(totals.values())


def render(rows: list[tuple[str, float]], total: float, start: str, end: str) -> str:
    lines = [f"Cost of project=clickops, {start} to {end} (exclusive), USD"]
    lines += [f"  {service:<45} {amount:8.2f}" for service, amount in rows]
    lines.append(f"  {'Total':<45} {total:8.2f}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    start, end = month_bounds(argv[1] if len(argv) > 1 else None)
    # Cost Explorer is a global service served from us-east-1.
    ce = boto3.client("ce", region_name="us-east-1")
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Tags": {"Key": "project", "Values": ["clickops"]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    rows, total = summarize(response)
    print(render(rows, total, start, end))
    if not rows:
        print("No tagged cost found: is the `project` cost allocation tag activated?")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
