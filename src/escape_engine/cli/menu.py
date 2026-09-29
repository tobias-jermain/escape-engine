"""Guided menu: the friendly front door the Mac app opens.

First run: a short guide, then a setup wizard (API key, home airports, budget, times,
updates). After that: find trips, change settings, update the app.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypeVar

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from escape_engine import __version__, keystore, update
from escape_engine import settings as settings_mod
from escape_engine.core import airports
from escape_engine.core.models import Airport
from escape_engine.core.parse import parse_clock, parse_duration, parse_return_by
from escape_engine.providers.base import ProviderError
from escape_engine.providers.serpapi import KEY_ENV, check_key
from escape_engine.search.engine import BudgetError
from escape_engine.settings import Settings

T = TypeVar("T")

GUIDE = """[bold]Welcome to Escape Engine[/bold]

It finds [bold]extreme day trips[/bold]: fly out early, fly back late,
same day, for around [bold]£75 return[/bold].

[bold]How it works[/bold]

1. Choose where you fly from (all London airports by default).
2. Choose a destination city and a date.
3. It checks [bold]live[/bold] Google Flights prices and shows trips that fit:
   out early, home the same night, at least 6 hours there.

Trips a little over budget are shown separately as [bold]"Just over"[/bold].
Prices are per person, with the free small bag only."""

KEY_INFO = """You need a free [bold]SerpApi[/bold] key for live prices.

1. Sign up at [bold]serpapi.com[/bold]
2. Open your Dashboard and copy [bold]"Your Private API Key"[/bold]
3. Paste it below (it stays hidden while you type)

The free plan gives 250 searches a month. Each day-trip search uses 2."""


@dataclass
class MenuDeps:
    """Everything the menu touches outside itself, so tests can swap it out."""

    settings_file: Path | None = None
    credentials_file: Path | None = None
    check_key: Callable[[str], dict[str, Any]] = check_key
    latest_release: Callable[[], update.Release | None] = update.latest_release
    update_if_due: Callable[[], update.Release | None] = update.check_if_due
    installed_via_pkg: Callable[[], bool] = update.installed_via_pkg
    download: Callable[[update.Release], Path] = update.download
    open_installer: Callable[[Path], None] = update.open_installer


def next_saturday(today: date) -> date:
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def _ask_valid(prompt: str, default: str, check: Callable[[str], T], console: Console) -> str:
    """Ask until ``check`` accepts the answer; return the answer as typed."""
    while True:
        answer = Prompt.ask(prompt, default=default).strip()
        try:
            check(answer)
        except (ValueError, LookupError, InvalidOperation) as exc:
            console.print(f"[red]{exc}[/red] Please try again.")
            continue
        return answer


def _positive_price(text: str) -> Decimal:
    value = Decimal(text)
    if value <= 0:
        raise ValueError("price must be more than 0")
    return value


def _has_key(deps: MenuDeps) -> bool:
    return bool(keystore.get(KEY_ENV, deps.credentials_file))


# --- Setup ------------------------------------------------------------------------------


def setup_key(console: Console, deps: MenuDeps) -> None:
    source = keystore.source(KEY_ENV, deps.credentials_file)
    if source == "environment":
        console.print(f"Using the key from the {KEY_ENV} environment variable.")
        return
    console.print(Panel(KEY_INFO, title="API key", padding=(1, 3)))
    hint = "Press Enter to keep your saved key" if source else "Press Enter to skip for now"
    while True:
        key = Prompt.ask(
            f"Paste your key ({hint})", password=True, default="", show_default=False
        ).strip()
        if not key:
            return
        try:
            account = deps.check_key(key)
        except ProviderError as exc:
            console.print(f"[red]{exc}.[/red]")
            if Confirm.ask("Save it anyway?", default=False):
                keystore.put(KEY_ENV, key, deps.credentials_file)
                return
            continue
        keystore.put(KEY_ENV, key, deps.credentials_file)
        left = account.get("plan_searches_left", account.get("total_searches_left", "?"))
        plan = account.get("plan_name", "SerpApi")
        console.print(f"[green]Key saved.[/green] {plan}: {left} searches left this month.")
        return


def run_setup(console: Console, deps: MenuDeps, current: Settings) -> Settings:
    console.print(Panel("[bold]Setup[/bold]: five quick questions.", padding=(1, 3)))

    console.print("\n[bold]1 of 5 · API key[/bold]")
    setup_key(console, deps)

    console.print(
        "\n[bold]2 of 5 · Where do you fly from?[/bold]\n"
        "  LON = all 6 London airports (1 search each way)\n"
        "  UK  = every UK airport (about 4 searches each way)\n"
        "  or airport codes, e.g. STN,LTN"
    )
    home = _ask_valid("Home airports", current.home, airports.resolve, console).upper()

    console.print("\n[bold]3 of 5 · Budget[/bold]")
    max_price = _ask_valid(
        f"Max return price per person ({current.currency})",
        current.max_price,
        _positive_price,
        console,
    )

    console.print("\n[bold]4 of 5 · Times[/bold]")
    depart_after = _ask_valid(
        "Earliest departure (HH:MM)", current.depart_after, parse_clock, console
    )
    return_by = _ask_valid(
        "Latest landing home (23:59, or 02:30+1 for after midnight)",
        current.return_by,
        parse_return_by,
        console,
    )
    min_ground = _ask_valid(
        "Minimum time at the destination (e.g. 6h)", current.min_ground, parse_duration, console
    )

    console.print("\n[bold]5 of 5 · Updates[/bold]")
    auto = Confirm.ask(
        "Check for updates automatically (once a day)?", default=current.auto_update_check
    )

    new = current.model_copy(
        update={
            "home": home,
            "max_price": max_price,
            "depart_after": depart_after,
            "return_by": return_by,
            "min_ground": min_ground,
            "auto_update_check": auto,
            "setup_done": True,
        }
    )
    settings_mod.save(new, deps.settings_file)
    console.print(Panel(_summary(new, deps), title="All set", padding=(1, 3)))
    return new


def _summary(s: Settings, deps: MenuDeps) -> str:
    key = {
        "environment": "[green]from environment[/green]",
        "saved": "[green]saved[/green]",
        "": "[red]missing[/red]",
    }[keystore.source(KEY_ENV, deps.credentials_file)]
    return (
        f"Version:        {__version__}\n"
        f"API key:        {key}\n"
        f"Home airports:  {s.home}\n"
        f"Max price:      {s.max_price} {s.currency} return per person\n"
        f"Depart after:   {s.depart_after}\n"
        f"Home by:        {s.return_by}\n"
        f"Time there:     at least {s.min_ground}\n"
        f"Update check:   {'on' if s.auto_update_check else 'off'}"
    )


# --- Finding trips ----------------------------------------------------------------------


def choose_destination(console: Console) -> Airport | None:
    while True:
        text = Prompt.ask(
            "\n[bold]Where to?[/bold] Type a city or airport code (or Enter to go back)",
            default="",
            show_default=False,
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


def find_trip(console: Console, deps: MenuDeps, s: Settings, today: date) -> None:
    from escape_engine.cli import render, run_search

    if not _has_key(deps):
        console.print("[red]An API key is needed first.[/red] Choose [bold]2[/bold] (Settings).")
        return
    origin = _ask_valid("\n[bold]Fly from?[/bold]", s.home, airports.resolve, console)
    dest = choose_destination(console)
    if dest is None:
        return
    day_text = _ask_valid(
        "[bold]Which date?[/bold] (YYYY-MM-DD)",
        next_saturday(today).isoformat(),
        date.fromisoformat,
        console,
    )
    day = date.fromisoformat(day_text)
    if day < today:
        console.print("[red]That date is in the past.[/red]")
        return
    max_price = _ask_valid(
        f"[bold]Max price per person ({s.currency})?[/bold]", s.max_price, _positive_price, console
    )
    if not Confirm.ask(f"Search {origin} → {dest.city} on {day:%a %d %b}? Uses up to 2 searches"):
        return
    console.print("Searching live prices…")
    try:
        result = run_search(
            origins=airports.resolve(origin),
            destination=dest.iata,
            day=day,
            rules=s.rules(max_price=max_price),
            budget=2,
        )
    except (ProviderError, BudgetError, ValueError) as exc:
        console.print(f"[red]Search failed: {exc}[/red]")
        return
    render(result, console=console)


# --- Updates ----------------------------------------------------------------------------


def do_update(console: Console, deps: MenuDeps) -> bool:
    """Check for, download and open an update. Returns True if the menu should close."""
    console.print("Checking for updates…")
    try:
        release = deps.latest_release()
    except update.UpdateError as exc:
        console.print(f"[red]{exc}[/red]")
        return False
    if release is None:
        console.print("No releases have been published yet.")
        return False
    if not update.is_newer(release.version):
        console.print(f"[green]You're up to date[/green] (version {__version__}).")
        return False
    console.print(f"[bold]Version {release.version} is available[/bold] (you have {__version__}).")
    if not deps.installed_via_pkg():
        console.print("This is a developer copy: update it with [bold]git pull && uv sync[/bold].")
        return False
    if not Confirm.ask("Download and install it now?", default=True):
        return False
    try:
        pkg = deps.download(release)
        deps.open_installer(pkg)
    except (update.UpdateError, OSError) as exc:
        console.print(f"[red]Update failed: {exc}[/red]")
        return False
    console.print(
        Panel(
            "The installer is open. Follow its steps, then open\n"
            "[bold]Escape Engine[/bold] again to use the new version.",
            title="Updating",
            padding=(1, 3),
        )
    )
    return True


# --- Main loop --------------------------------------------------------------------------

MENU = """[bold]1[/bold]  Find a day trip
[bold]2[/bold]  Settings and API key
[bold]3[/bold]  Check for updates
[bold]4[/bold]  Show the guide
[bold]5[/bold]  Quit"""


def run_menu(
    *, console: Console | None = None, deps: MenuDeps | None = None, today: date | None = None
) -> None:
    console = console or Console()
    deps = deps or MenuDeps()
    today = today or date.today()
    s = settings_mod.load(deps.settings_file)

    if not s.setup_done:
        console.print(Panel(GUIDE, title="ESCAPE ENGINE", padding=(1, 3)))
        Prompt.ask("\nPress [bold]Enter[/bold] to start setup", default="", show_default=False)
        s = run_setup(console, deps, s)
    elif s.auto_update_check:
        newer = deps.update_if_due()
        if newer:
            console.print(
                Panel(
                    f"Version {newer.version} is available. Choose [bold]3[/bold] to update.",
                    title="Update",
                    padding=(0, 3),
                )
            )

    while True:
        console.print(Panel(MENU, title="ESCAPE ENGINE", padding=(1, 3)))
        choice = Prompt.ask("Choose", choices=["1", "2", "3", "4", "5"], default="1")
        if choice == "1":
            find_trip(console, deps, s, today)
        elif choice == "2":
            console.print(Panel(_summary(s, deps), title="Current settings", padding=(1, 3)))
            if Confirm.ask("Change them?", default=False):
                s = run_setup(console, deps, s)
        elif choice == "3":
            if do_update(console, deps):
                return
        elif choice == "4":
            console.print(Panel(GUIDE, title="ESCAPE ENGINE", padding=(1, 3)))
        else:
            console.print("Bye! Safe travels.")
            return
