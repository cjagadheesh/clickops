"""Typer CLI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from clickops.doctor import run_checks

app = typer.Typer(help="Detect and import out-of-Terraform AWS changes.", no_args_is_help=True)


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
