"""Typer CLI entry point."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import boto3
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clickops import store
from clickops.doctor import run_checks

app = typer.Typer(help="Detect and import out-of-Terraform AWS changes.", no_args_is_help=True)

_DURATION = re.compile(r"^(\d+)([mhd])$")
_SEVERITY_STYLE = {"critical": "red", "warning": "yellow", "info": "cyan", "none": "dim"}


def parse_duration(text: str) -> timedelta:
    """Parse ``30m``, ``1h`` or ``2d`` into a timedelta."""
    match = _DURATION.match(text.strip().lower())
    if not match:
        raise ValueError(f"cannot parse {text!r}; use a number and m, h or d, for example 1h")
    amount, unit = int(match.group(1)), match.group(2)
    if amount == 0:
        raise ValueError("duration must be greater than zero")
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }[unit]


@app.callback()
def main() -> None:
    """clickops command line."""


@app.command()
def doctor(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to clickops.yaml.")] = Path(
        "clickops.yaml"
    ),
) -> None:
    """Check credentials, Terraform, config and state access."""
    results = run_checks(config)
    table = Table(title="clickops doctor")
    for col in ("Check", "Result", "Detail", "Fix"):
        table.add_column(col, overflow="fold")
    for r in results:
        table.add_row(
            escape(r.name),
            "[green]pass[/]" if r.ok else "[red]fail[/]",
            escape(r.detail),
            escape(r.hint),
        )
    Console().print(table)
    if not all(r.ok for r in results):
        raise typer.Exit(1)


def events_table(items: list[dict[str, Any]]) -> Table:
    table = Table(title="clickops events")
    for col in ("Time (UTC)", "Actor", "Event", "Resource", "Outcome", "Severity"):
        table.add_column(col, overflow="fold")
    for item in items:
        severity = str(item.get("severity", "none"))
        style = _SEVERITY_STYLE.get(severity, "white")
        table.add_row(
            escape(str(item.get("ts", ""))),
            escape(f"{item.get('actor_name', '?')} ({item.get('actor_class', '?')})"),
            escape(str(item.get("event_name", ""))),
            escape(str(item.get(store.HASH_KEY, ""))),
            escape(str(item.get("outcome", ""))),
            f"[{style}]{escape(severity)}[/]",
        )
    return table


@app.command()
def events(
    since: Annotated[str, typer.Option("--since", help="How far back, e.g. 30m, 1h, 2d.")] = "1h",
    region: Annotated[str, typer.Option(help="Region of the events table.")] = "ap-south-1",
    table_name: Annotated[str, typer.Option("--table", help="DynamoDB table name.")] = (
        store.TABLE_NAME
    ),
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """Show stored events from the last period, oldest first."""
    try:
        delta = parse_duration(since)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--since") from exc
    now = datetime.now(UTC)
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    items = store.query_since(table, now - delta, now)
    if as_json:
        typer.echo(json.dumps(items, indent=2, default=str))
    elif items:
        Console().print(events_table(items))
    else:
        Console().print(f"No events in the last {since}.")
