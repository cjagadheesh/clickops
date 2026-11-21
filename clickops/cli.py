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

from clickops import __version__, store
from clickops.config import ConfigError, load_config
from clickops.doctor import run_checks
from clickops.importer import ImporterError, generate_config, write_imports
from clickops.scan import ShadowResource, open_table
from clickops.scan import scan as run_scan
from clickops.state import StateError, StateReader
from clickops.status import collect as collect_status

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


def _show_version(show: bool) -> None:
    if show:
        typer.echo(f"clickops {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
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


def shadow_table(resources: list[ShadowResource]) -> Table:
    table = Table(title="Shadow resources (in AWS, in no Terraform state)")
    for col in ("Type", "ID", "Name", "Created (UTC)", "Creator"):
        table.add_column(col, overflow="fold")
    for r in resources:
        created = f"{r.created:%Y-%m-%d %H:%M}" if r.created else ""
        table.add_row(
            escape(r.type), escape(r.id), escape(r.name), created, escape(r.creator or "")
        )
    return table


@app.command()
def scan(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to clickops.yaml.")] = Path(
        "clickops.yaml"
    ),
    region: Annotated[str, typer.Option(help="Region to scan.")] = "ap-south-1",
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """List shadow resources: they exist in AWS but in no configured Terraform state."""
    try:
        index = StateReader(load_config(config).state_locations).load()
    except (ConfigError, StateError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    resources = run_scan(index, region, open_table(region))
    if as_json:
        typer.echo(json.dumps([r.to_json() for r in resources], indent=2))
    elif resources:
        Console().print(shadow_table(resources))
    else:
        Console().print("No shadow resources: everything found is in Terraform state.")


def pick_resources(resources: list[ShadowResource], only: list[str]) -> list[ShadowResource]:
    """Keep resources whose ID or ``type/id`` is in ``only`` (all of them when it is empty)."""
    if not only:
        return resources
    wanted = set(only)
    return [r for r in resources if r.id in wanted or f"{r.type}/{r.id}" in wanted]


@app.command(name="import")
def import_shadow(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to clickops.yaml.")] = Path(
        "clickops.yaml"
    ),
    region: Annotated[str, typer.Option(help="Region to scan and import from.")] = "ap-south-1",
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Import just this ID or type/id (repeatable)."),
    ] = None,
    out: Annotated[Path, typer.Option(help="Folder for the timestamped output.")] = Path("imports"),
    no_terraform: Annotated[
        bool, typer.Option("--no-terraform", help="Only write the import blocks.")
    ] = False,
    terraform: Annotated[str, typer.Option(help="Terraform binary.")] = "terraform",
) -> None:
    """Write Terraform import blocks for shadow resources and draft their configuration.

    Runs `terraform plan -generate-config-out` in a temporary directory; nothing is applied.
    """
    console = Console()
    try:
        index = StateReader(load_config(config).state_locations).load()
    except (ConfigError, StateError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    chosen = pick_resources(run_scan(index, region, open_table(region)), only or [])
    if not chosen:
        console.print("Nothing to import: no matching shadow resources.")
        return
    directory, imports_path = write_imports(chosen, out)
    console.print(f"Wrote {len(chosen)} import block(s) to {escape(str(imports_path))}")
    if no_terraform:
        return
    try:
        result = generate_config(directory, region, terraform)
    except ImporterError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(f"The import blocks are kept in {imports_path}.", err=True)
        raise typer.Exit(3) from exc
    if result.plan_summary:
        console.print(escape(result.plan_summary))
    if result.validate_ok:
        console.print(f"Generated config validates: {escape(str(result.generated_path))}")
        return
    console.print("[yellow]Generated config does not validate yet:[/]")
    for error in result.errors:
        console.print(f"  - {escape(' '.join(error.split()))}")
    console.print(f"Kept as a starting point: {escape(str(result.generated_path))}")
    raise typer.Exit(1)


@app.command()
def status(
    region: Annotated[str, typer.Option(help="Region of the detector.")] = "ap-south-1",
) -> None:
    """Check the trail, the event rules, the dead-letter queue and the alarms."""
    rows = collect_status(region)
    table = Table(title="clickops status")
    for col in ("Check", "Result", "Detail"):
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            escape(row.name), "[green]ok[/]" if row.ok else "[red]problem[/]", escape(row.detail)
        )
    Console().print(table)
    if not all(r.ok for r in rows):
        raise typer.Exit(1)
