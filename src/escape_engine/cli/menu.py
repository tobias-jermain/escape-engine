"""Guided menu: the friendly front door the Mac app opens. Shows a guide on first run."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from platformdirs import user_config_dir
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from escape_engine import __version__
from escape_engine.core import airports
from escape_engine.core.models import Airport, TripRules
from escape_engine.providers.base import ProviderError
from escape_engine.providers.serpapi import KEY_ENV, SerpApiFlights
from escape_engine.search.engine import BudgetError

KEY_HELP = f"""[bold]How to add your SerpApi key[/bold] (one time only)

1. Get a free key at [bold]serpapi.com[/bold] (Dashboard, "Your Private API Key").
   The free plan gives 250 searches a month. Each day-trip search uses 2.

2. In this window, type:   [bold]nano ~/.zshrc[/bold]   and press Enter.

3. Add this line at the bottom, with your key between the quotes:
   [bold]export {KEY_ENV}="your-key-here"[/bold]

4. Press Control+O, Enter, then Control+X to save and exit.

5. Close this window and open [bold]Escape Engine[/bold] again."""

GUIDE = """[bold]Welcome to Escape Engine[/bold]

It finds [bold]extreme day trips[/bold]: fly out early, fly back late,
same day, for around [bold]£75 return[/bold].

[bold]How it works[/bold]

1. Choose where you fly from (all London airports by default).
2. Choose a destination city and a date.
3. It checks [bold]live[/bold] Google Flights prices and shows trips that fit:
   out from 05:00, home by midnight, at least 6 hours there.

Trips a little over budget are shown separately as [bold]"Just over"[/bold].
Prices are per person, with the free small bag only."""


def state_path() -> Path:
    return Path(user_config_dir("escape-engine")) / "state.json"


def _load_state(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), "utf-8")


def next_saturday(today: date) -> date:
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def show_guide(console: Console) -> None:
    console.print(Panel(GUIDE, title="ESCAPE ENGINE", padding=(1, 3)))
    if not SerpApiFlights().configured():
        console.print(Panel(KEY_HELP, title="Before your first search", padding=(1, 3)))
    Prompt.ask("\nPress [bold]Enter[/bold] to continue", default="", show_default=False)


def choose_destination(console: Console) -> Airport | None:
    while True:
        text = Prompt.ask(
            "\n[bold]Where to?[/bold] Type a city or airport code (or Enter to go back)"
        )
        if not text.strip():
            return None
        matches = airports.search(text)
        if not matches:
            console.print("No airport found. Try another spelling, e.g. [bold]Krakow[/bold].")
            continue
        if len(matches) == 1:
            return matches[0]
        for i, a in enumerate(matches, 1):
            console.print(f"  [bold]{i}[/bold]  {a.iata}  {a.city}, {a.country}  ({a.name})")
        pick = IntPrompt.ask("Which one? (0 to search again)", default=1)
        if 1 <= pick <= len(matches):
            return matches[pick - 1]


def find_trip(console: Console, today: date) -> None:
    from escape_engine.cli import render, run_search

    if not SerpApiFlights().configured():
        console.print(Panel(KEY_HELP, title="A SerpApi key is needed first", padding=(1, 3)))
        return
    origin = Prompt.ask("\n[bold]Fly from?[/bold] (LON = all London airports)", default="LON")
    try:
        origins = airports.resolve(origin)
    except (LookupError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return
    dest = choose_destination(console)
    if dest is None:
        return
    default_day = next_saturday(today).isoformat()
    try:
        day = date.fromisoformat(
            Prompt.ask("[bold]Which date?[/bold] (YYYY-MM-DD)", default=default_day)
        )
        max_price = Decimal(Prompt.ask("[bold]Max price per person, £?[/bold]", default="75"))
    except (ValueError, InvalidOperation):
        console.print("[red]That date or price didn't look right.[/red]")
        return
    if day < today:
        console.print("[red]That date is in the past.[/red]")
        return
    if not Confirm.ask(f"Search {origin} → {dest.city} on {day:%a %d %b}? Uses up to 2 searches"):
        return
    console.print("Searching live prices…")
    try:
        result = run_search(
            origins=origins,
            destination=dest.iata,
            day=day,
            rules=TripRules(max_price=max_price),
            budget=2,
        )
    except (ProviderError, BudgetError, ValueError) as exc:
        console.print(f"[red]Search failed: {exc}[/red]")
        return
    render(result, console=console)


def check_setup(console: Console) -> None:
    key = "[green]set[/green]" if SerpApiFlights().configured() else "[red]missing[/red]"
    console.print(
        Panel(
            f"Version: {__version__}\nSerpApi key: {key}",
            title="Setup",
            padding=(1, 3),
        )
    )
    if not SerpApiFlights().configured():
        console.print(Panel(KEY_HELP, padding=(1, 3)))


MENU = """[bold]1[/bold]  Find a day trip
[bold]2[/bold]  Show the guide again
[bold]3[/bold]  Check my setup
[bold]4[/bold]  Quit"""


def run_menu(
    *, console: Console | None = None, state_file: Path | None = None, today: date | None = None
) -> None:
    console = console or Console()
    path = state_file or state_path()
    today = today or date.today()
    state = _load_state(path)
    if not state.get("guide_seen"):
        show_guide(console)
        state["guide_seen"] = True
        _save_state(path, state)
    while True:
        console.print(Panel(MENU, title="ESCAPE ENGINE", padding=(1, 3)))
        choice = Prompt.ask("Choose", choices=["1", "2", "3", "4"], default="1")
        if choice == "1":
            find_trip(console, today)
        elif choice == "2":
            show_guide(console)
        elif choice == "3":
            check_setup(console)
        else:
            console.print("Bye! Safe travels.")
            return
