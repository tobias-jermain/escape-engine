"""`escape` command-line interface: a thin layer over the engine."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from escape_engine import __version__
from escape_engine.cache import Cache
from escape_engine.core import airports
from escape_engine.core.models import DayTrip, TripRules
from escape_engine.core.parse import parse_clock, parse_duration, parse_return_by
from escape_engine.core.ranking import SortKey
from escape_engine.core.rules import fmt_duration
from escape_engine.fx import fetch_rates
from escape_engine.providers.base import ProviderError
from escape_engine.providers.serpapi import KEY_ENV, SerpApiFlights
from escape_engine.search.engine import BudgetError, Engine, SearchResult

JSON_SCHEMA = "escape.v1"

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


def _fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(2)


@app.command("providers")
def providers_cmd() -> None:
    """Show flight data providers and whether they are ready to use."""
    for p in [SerpApiFlights()]:
        state = "ready" if p.configured() else f"not configured (set {KEY_ENV})"
        kind = "live" if p.live else "discovery"
        typer.echo(f"{p.name:<10} {kind:<10} {state}")


@app.command("check")
def check_cmd(
    to: Annotated[str, typer.Option("--to", help="Destination airport code, e.g. KRK.")],
    on: Annotated[str, typer.Option("--date", help="Trip date, YYYY-MM-DD.")],
    origin: Annotated[str, typer.Option("--from", help="Home airports or groups.")] = "LON",
    max_price: Annotated[str, typer.Option("--max", help="Return fare per person.")] = "75",
    stretch: Annotated[str, typer.Option(help="Extra fraction shown as 'just over'.")] = "0.20",
    currency: Annotated[str, typer.Option(help="Home currency.")] = "GBP",
    pax: Annotated[int, typer.Option(min=1, max=9, help="Passengers.")] = 1,
    depart_after: Annotated[str, typer.Option(help="Earliest departure, HH:MM.")] = "05:00",
    return_by: Annotated[str, typer.Option(help="Latest landing: 23:59 or 02:30+1.")] = "23:59",
    min_ground: Annotated[str, typer.Option(help="Min time at destination.")] = "6h",
    min_usable: Annotated[str, typer.Option(help="Warn below this usable time.")] = "4h",
    overnight: Annotated[bool, typer.Option(help="Allow a night away.")] = False,
    allow_connections: Annotated[bool, typer.Option(help="Last resort: allow stops.")] = False,
    open_jaw: Annotated[bool, typer.Option(help="Allow returning to another home airport.")] = True,
    budget: Annotated[int, typer.Option(min=1, help="Max live provider calls.")] = 10,
    fresh: Annotated[bool, typer.Option(help="Ignore cached results.")] = False,
    sort: Annotated[str, typer.Option(help="Sort keys: price,date,usable.")] = "price,date,usable",
    explain: Annotated[bool, typer.Option(help="Also list rejected pairs and why.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Find valid day trips to one destination on one date (live prices)."""
    try:
        day = date.fromisoformat(on)
        origins = airports.resolve(origin)
        destination = airports.get(to).iata
        rules = TripRules(
            depart_after=parse_clock(depart_after),
            return_by=parse_return_by(return_by),
            min_ground=parse_duration(min_ground),
            min_usable=parse_duration(min_usable),
            overnight=overnight,
            allow_connections=allow_connections,
            allow_open_jaw=open_jaw,
            max_price=Decimal(max_price),
            stretch=Decimal(stretch),
            currency=currency.upper(),
        )
        order: list[SortKey] = [k.strip() for k in sort.split(",") if k.strip()]  # type: ignore[misc]
    except (ValueError, LookupError, ArithmeticError) as exc:
        raise _fail(str(exc)) from None

    cache = Cache()
    engine = Engine([SerpApiFlights()], cache=cache, rates=fetch_rates, use_cache=not fresh)
    try:
        result = asyncio.run(
            engine.check(
                origins=origins,
                destination=destination,
                day=day,
                rules=rules,
                pax=pax,
                budget=budget,
                order=order,
            )
        )
    except (ProviderError, BudgetError, ValueError) as exc:
        raise _fail(str(exc)) from None
    finally:
        cache.close()

    if as_json:
        query = {"from": origins, "to": destination, "date": day.isoformat(), "pax": pax}
        typer.echo(json.dumps(to_json(result, query, rules), indent=2))
    else:
        render(result, explain=explain)


def _trip_json(t: DayTrip) -> dict[str, Any]:
    data: dict[str, Any] = t.model_dump(mode="json")
    data["ground_minutes"] = int(t.ground_time.total_seconds() // 60)
    data["usable_minutes"] = int(t.usable_time.total_seconds() // 60)
    return data


def to_json(result: SearchResult, query: dict[str, Any], rules: TripRules) -> dict[str, Any]:
    return {
        "schema": JSON_SCHEMA,
        "query": query,
        "rules": rules.model_dump(mode="json"),
        "trips": [_trip_json(t) for t in result.trips],
        "just_over": [_trip_json(t) for t in result.just_over],
        "rejected": {"count": len(result.rejected), "top_reasons": result.top_reasons()},
        "calls_used": result.calls_used,
        "errors": result.errors,
    }


def _table(title: str, trips: list[DayTrip]) -> Table:
    table = Table(title=title, title_justify="left")
    for col in ("Price", "Out", "Back", "Usable", "Notes"):
        table.add_column(col)
    for t in trips:
        o, b = t.outbound, t.inbound
        leaves = o.departs_at.astimezone(airports.timezone(o.origin))
        lands = b.arrives_at.astimezone(airports.timezone(b.destination))
        table.add_row(
            str(t.price),
            f"{o.origin} {leaves:%H:%M} {o.carrier}{o.flight_number}",
            f"{b.destination} {lands:%H:%M} {b.carrier}{b.flight_number}",
            fmt_duration(t.usable_time),
            "; ".join(t.warnings),
        )
    return table


def render(result: SearchResult, *, explain: bool = False) -> None:
    console = Console()
    if result.trips:
        console.print(_table("Day trips", result.trips))
    else:
        console.print("No valid day trips under the limit.")
    if result.just_over:
        console.print(_table("Just over", result.just_over))
    if result.rejected:
        reasons = ", ".join(f"{k} ({n})" for k, n in result.top_reasons())
        console.print(f"{len(result.rejected)} pairs rejected: {reasons}")
    if explain:
        for t in result.rejected:
            o, b = t.outbound, t.inbound
            console.print(
                f"  x {o.carrier}{o.flight_number} + {b.carrier}{b.flight_number}: "
                + "; ".join(t.reasons)
            )
    for err in result.errors:
        console.print(f"[yellow]warning:[/yellow] {err}")
    console.print(f"Live calls used: {result.calls_used}")


def main() -> None:
    app()
