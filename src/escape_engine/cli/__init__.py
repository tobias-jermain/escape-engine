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

from escape_engine import __version__, settings
from escape_engine.cache import Cache
from escape_engine.core import airports
from escape_engine.core.models import DayTrip, TripRules
from escape_engine.core.parse import parse_clock, parse_duration, parse_return_by
from escape_engine.core.ranking import SortKey
from escape_engine.core.rules import fmt_duration
from escape_engine.fx import fetch_rates
from escape_engine.providers.base import ProviderError
from escape_engine.providers.serpapi import KEY_ENV, SerpApiExplore, SerpApiFlights
from escape_engine.search.engine import BudgetError, Engine, SearchResult
from escape_engine.search.explore import MAX_FLIGHT_MINUTES, ExploreResult, explore

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
    origin: Annotated[
        str | None, typer.Option("--from", help="Home airports or groups. [default: setup]")
    ] = None,
    max_price: Annotated[
        str | None, typer.Option("--max", help="Return fare per person. [default: setup]")
    ] = None,
    stretch: Annotated[str, typer.Option(help="Extra fraction shown as 'just over'.")] = "0.20",
    currency: Annotated[str | None, typer.Option(help="Home currency. [default: setup]")] = None,
    pax: Annotated[int, typer.Option(min=1, max=9, help="Passengers.")] = 1,
    depart_after: Annotated[
        str | None, typer.Option(help="Earliest departure, HH:MM. [default: setup]")
    ] = None,
    return_by: Annotated[
        str | None, typer.Option(help="Latest landing: 23:59 or 02:30+1. [default: setup]")
    ] = None,
    min_ground: Annotated[
        str | None, typer.Option(help="Min time at destination. [default: setup]")
    ] = None,
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
    saved = settings.load()
    try:
        day = date.fromisoformat(on)
        origins = airports.resolve(origin or saved.home)
        destination = airports.get(to).iata
        rules = saved.rules(
            depart_after=parse_clock(depart_after) if depart_after else None,
            return_by=parse_return_by(return_by) if return_by else None,
            min_ground=parse_duration(min_ground) if min_ground else None,
            min_usable=parse_duration(min_usable),
            overnight=overnight,
            allow_connections=allow_connections,
            allow_open_jaw=open_jaw,
            max_price=Decimal(max_price) if max_price else None,
            stretch=Decimal(stretch),
            currency=currency.upper() if currency else None,
        )
        order: list[SortKey] = [k.strip() for k in sort.split(",") if k.strip()]  # type: ignore[misc]
    except (ValueError, LookupError, ArithmeticError) as exc:
        raise _fail(str(exc)) from None

    try:
        result = run_search(
            origins=origins,
            destination=destination,
            day=day,
            rules=rules,
            pax=pax,
            budget=budget,
            order=order,
            fresh=fresh,
        )
    except (ProviderError, BudgetError, ValueError) as exc:
        raise _fail(str(exc)) from None

    if as_json:
        query = {"from": origins, "to": destination, "date": day.isoformat(), "pax": pax}
        typer.echo(json.dumps(to_json(result, query, rules), indent=2))
    else:
        render(result, explain=explain)


def run_search(
    *,
    origins: list[str],
    destination: str,
    day: date,
    rules: TripRules,
    pax: int = 1,
    budget: int = 10,
    order: list[SortKey] | None = None,
    fresh: bool = False,
) -> SearchResult:
    """One live search, shared by ``escape check`` and ``escape menu``."""
    cache = Cache()
    engine = Engine([SerpApiFlights()], cache=cache, rates=fetch_rates, use_cache=not fresh)
    try:
        return asyncio.run(
            engine.check(
                origins=origins,
                destination=destination,
                day=day,
                rules=rules,
                pax=pax,
                budget=budget,
                order=order or ["price", "date", "usable"],
            )
        )
    finally:
        cache.close()


def run_explore(
    *,
    origins: list[str],
    rules: TripRules,
    days: int = 21,
    pax: int = 1,
    budget: int = 10,
    max_flight_minutes: int = MAX_FLIGHT_MINUTES,
    fresh: bool = False,
) -> ExploreResult:
    """Cheapest day trips anywhere in the next ``days`` days (shared by CLI and menu)."""
    cache = Cache()
    engine = Engine([SerpApiFlights()], cache=cache, rates=fetch_rates, use_cache=not fresh)
    try:
        return asyncio.run(
            explore(
                engine,
                SerpApiExplore(),
                origins=origins,
                rules=rules,
                days=days,
                pax=pax,
                budget=budget,
                max_flight_minutes=max_flight_minutes,
            )
        )
    finally:
        cache.close()


@app.command("explore")
def explore_cmd(
    origin: Annotated[
        str | None, typer.Option("--from", help="Home airports or groups. [default: setup]")
    ] = None,
    max_price: Annotated[
        str | None, typer.Option("--max", help="Return fare per person. [default: setup]")
    ] = None,
    days: Annotated[int, typer.Option(min=2, max=90, help="Search the next N days.")] = 21,
    budget: Annotated[
        int, typer.Option(min=3, help="Max live searches (discovery + 2 per destination).")
    ] = 10,
    pax: Annotated[int, typer.Option(min=1, max=9, help="Passengers.")] = 1,
    depart_after: Annotated[
        str | None, typer.Option(help="Earliest departure, HH:MM. [default: setup]")
    ] = None,
    return_by: Annotated[
        str | None, typer.Option(help="Latest landing: 23:59 or 02:30+1. [default: setup]")
    ] = None,
    min_ground: Annotated[
        str | None, typer.Option(help="Min time at destination. [default: setup]")
    ] = None,
    max_flight: Annotated[str, typer.Option(help="Longest one-way flight considered.")] = "4h",
    fresh: Annotated[bool, typer.Option(help="Ignore cached results.")] = False,
    show_all: Annotated[
        bool, typer.Option("--all", help="Every valid pair, not the best.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Cheapest day trips to ANYWHERE in the next few weeks, under your price."""
    saved = settings.load()
    try:
        origins = airports.resolve(origin or saved.home)
        rules = saved.rules(
            depart_after=parse_clock(depart_after) if depart_after else None,
            return_by=parse_return_by(return_by) if return_by else None,
            min_ground=parse_duration(min_ground) if min_ground else None,
            max_price=Decimal(max_price) if max_price else None,
        )
        max_minutes = int(parse_duration(max_flight).total_seconds() // 60)
    except (ValueError, LookupError, ArithmeticError) as exc:
        raise _fail(str(exc)) from None
    try:
        result = run_explore(
            origins=origins,
            rules=rules,
            days=days,
            pax=pax,
            budget=budget,
            max_flight_minutes=max_minutes,
            fresh=fresh,
        )
    except (ProviderError, BudgetError, ValueError) as exc:
        raise _fail(str(exc)) from None
    if as_json:
        query = {"from": origins, "to": "anywhere", "days": days, "pax": pax}
        data = to_json(result, query, rules)
        data["checked"] = [c.model_dump(mode="json") for c in result.checked]
        data["shortlist_size"] = result.shortlist_size
        data["outside_window"] = result.outside_window
        typer.echo(json.dumps(data, indent=2))
    else:
        render(result, show_all=show_all)


@app.command("menu")
def menu_cmd() -> None:
    """Guided, step-by-step menu (what the Mac app opens)."""
    from escape_engine.cli.menu import run_menu

    run_menu()


@app.command("setup")
def setup_cmd() -> None:
    """Run setup: API key, home airports, budget, times and updates."""
    from escape_engine.cli.menu import MenuDeps, run_setup

    run_setup(Console(), MenuDeps(), settings.load())


@app.command("update")
def update_cmd() -> None:
    """Check for a newer version and install it."""
    from escape_engine.cli.menu import MenuDeps, do_update

    do_update(Console(), MenuDeps())


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
    for col in ("Price", "Date", "To", "Out", "Back", "Usable", "Notes"):
        table.add_column(col)
    for t in trips:
        o, b = t.outbound, t.inbound
        leaves = o.departs_at.astimezone(airports.timezone(o.origin))
        lands = b.arrives_at.astimezone(airports.timezone(b.destination))
        table.add_row(
            str(t.price),
            f"{t.trip_date:%a %d %b}",
            f"{airports.get(o.destination).city} ({o.destination})",
            f"{o.origin} {leaves:%H:%M} {o.carrier}{o.flight_number}",
            f"{b.destination} {lands:%H:%M} {b.carrier}{b.flight_number}",
            fmt_duration(t.usable_time),
            "; ".join(t.warnings),
        )
    return table


def best_per_destination(trips: list[DayTrip]) -> list[DayTrip]:
    """Keep the first (best-ranked) trip for each destination and date."""
    seen: set[tuple[str, date]] = set()
    out = []
    for t in trips:
        key = (t.outbound.destination, t.trip_date)
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def render(
    result: SearchResult,
    *,
    explain: bool = False,
    show_all: bool = True,
    console: Console | None = None,
) -> None:
    console = console or Console()
    trips = result.trips if show_all else best_per_destination(result.trips)
    just_over = result.just_over
    if not show_all:
        # A place that already has a trip under budget doesn't need a pricier "just over" one.
        covered = {(t.outbound.destination, t.trip_date) for t in trips}
        just_over = [
            t
            for t in best_per_destination(result.just_over)
            if (t.outbound.destination, t.trip_date) not in covered
        ]
    if trips:
        console.print(_table("Day trips", trips))
    else:
        console.print("No valid day trips under the limit.")
    if just_over:
        console.print(_table("Just over", just_over))
    if isinstance(result, ExploreResult):
        names = ", ".join(f"{c.city} {c.day:%d %b}" for c in result.checked) or "none"
        console.print(
            f"Checked {len(result.checked)} of {result.shortlist_size} cheap destinations: {names}"
        )
        if result.outside_window:
            console.print(
                f"{result.outside_window} more were cheapest outside your dates (not checked)."
            )
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
