"""`escape` command-line interface: a thin layer over the engine."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from escape_engine import __version__
from escape_engine.core import airports

app = typer.Typer(
    help="Find ultra-cheap extreme day-trip flights.", no_args_is_help=True, add_completion=False
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"escape {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    pass


@app.command("airports")
def airports_cmd(
    spec: Annotated[str, typer.Argument(help="Airport codes and/or groups, e.g. LON,BHX")],
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Expand airport codes and groups and show their timezones."""
    try:
        found = [airports.get(code) for code in airports.resolve(spec)]
    except (LookupError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    if as_json:
        typer.echo(json.dumps([a.model_dump() for a in found], indent=2))
        return
    for a in found:
        typer.echo(f"{a.iata}  {a.name:<45.45}  {a.country}  {a.tz}")


def main() -> None:
    app()
