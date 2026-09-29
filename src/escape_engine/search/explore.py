"""Mode (c): day trips to anywhere within a date window, cheapest first.

1. Discover: one Travel Explore call per calendar month in the window lists cheap
   destinations with their cheapest one-way date and price (indicative only).
2. Shortlist (free): direct, inside the window, short enough for a day trip, under the cap.
3. Verify: the best candidates get a full live out-and-back ``check`` against the rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from escape_engine.core import airports
from escape_engine.core.models import Candidate, TripRules
from escape_engine.core.ranking import DEFAULT_ORDER, SortKey, rank
from escape_engine.providers.base import ExploreQuery, ProviderError
from escape_engine.search.engine import BudgetError, Engine, SearchResult

MAX_FLIGHT_MINUTES = 240
"""Longer flights leave too little of the day at the destination."""


class Discovery(Protocol):
    name: str

    def configured(self) -> bool: ...

    async def explore(self, query: ExploreQuery) -> list[Candidate]: ...


@dataclass
class ExploreResult(SearchResult):
    checked: list[Candidate] = field(default_factory=list)
    """Candidates that were verified live, in the order they were chosen."""
    shortlist_size: int = 0
    """How many destinations passed the free shortlist filters."""
    outside_window: int = 0
    """Cheap destinations whose cheapest date fell outside the window (not checked)."""


def window(today: date, days: int) -> tuple[date, date]:
    """Tomorrow through ``days`` days from today (today's early flights have gone)."""
    return today + timedelta(days=1), today + timedelta(days=days)


def months_in(start: date, end: date) -> list[int]:
    """Calendar months touched by the window, skipping one that contributes under 3 days."""
    spans: dict[int, int] = {}
    day = start
    while day <= end:
        spans[day.month] = spans.get(day.month, 0) + 1
        day += timedelta(days=1)
    keep = [m for m, n in spans.items() if n >= 3]
    return keep or [max(spans, key=lambda m: spans[m])]


def shortlist(
    candidates: Sequence[Candidate],
    *,
    start: date,
    end: date,
    rules: TripRules,
    origins: Sequence[str],
    max_flight_minutes: int = MAX_FLIGHT_MINUTES,
) -> tuple[list[Candidate], int]:
    """Filter and order candidates; returns (shortlist, how many fell outside the window)."""
    cap = rules.max_price * (1 + rules.stretch)
    best: dict[str, Candidate] = {}
    outside = 0
    for c in candidates:
        if c.destination in origins or c.price.currency != rules.currency:
            continue
        if c.stops and not rules.allow_connections:
            continue
        if c.flight_minutes is not None and c.flight_minutes > max_flight_minutes:
            continue
        if c.price.amount >= cap:  # the return still has to fit
            continue
        if not start <= c.day <= end:
            outside += 1
            continue
        kept = best.get(c.destination)
        if kept is None or (c.price.amount, c.day) < (kept.price.amount, kept.day):
            best[c.destination] = c
    ordered = sorted(best.values(), key=lambda c: (c.price.amount, c.day))
    return ordered, outside


async def explore(
    engine: Engine,
    discovery: Discovery,
    *,
    origins: Sequence[str],
    rules: TripRules,
    days: int = 21,
    pax: int = 1,
    budget: int = 10,
    max_flight_minutes: int = MAX_FLIGHT_MINUTES,
    order: Sequence[SortKey] = DEFAULT_ORDER,
    now: datetime | None = None,
) -> ExploreResult:
    if not discovery.configured() or not engine.providers:
        raise ProviderError("no provider is configured (set up your SerpApi key)")
    now = now or datetime.now(UTC)
    today = now.astimezone(airports.timezone(origins[0])).date()
    start, end = window(today, days)
    months = months_in(start, end)
    per_check = engine.calls_needed(origins, rules)
    if budget < len(months) + per_check:
        raise BudgetError(
            f"needs at least {len(months) + per_check} live calls, budget is {budget}"
        )

    calls = 0
    errors: list[str] = []
    found: list[Candidate] = []
    for month in months:
        query = ExploreQuery(
            tuple(origins), month, pax, rules.currency, not rules.allow_connections
        )
        key = f"{discovery.name}|{query.cache_key()}"
        cached = engine.cache.get_payload(key) if engine.cache and engine.use_cache else None
        if cached is not None:
            found += [Candidate.model_validate(c) for c in cached]
            continue
        calls += 1
        try:
            batch = await discovery.explore(query)
        except ProviderError as exc:
            errors.append(f"{discovery.name}: {exc}")
            continue
        if engine.cache:
            engine.cache.put_payload(key, [c.model_dump(mode="json") for c in batch])
        found += batch

    short, outside = shortlist(
        found,
        start=start,
        end=end,
        rules=rules,
        origins=origins,
        max_flight_minutes=max_flight_minutes,
    )
    slots = (budget - calls) // per_check
    chosen = short[:slots]

    async def verify(c: Candidate) -> SearchResult | None:
        try:
            return await engine.check(
                origins=origins,
                destination=c.destination,
                day=c.day,
                rules=rules,
                pax=pax,
                budget=per_check,
                order=order,
                now=now,
            )
        except (ProviderError, BudgetError) as exc:
            errors.append(f"{c.destination}: {exc}")
            return None

    checked = [r for r in await asyncio.gather(*(verify(c) for c in chosen)) if r]
    return ExploreResult(
        trips=rank([t for r in checked for t in r.trips], today=today, order=order),
        just_over=rank([t for r in checked for t in r.just_over], today=today, order=order),
        rejected=[t for r in checked for t in r.rejected],
        calls_used=calls + sum(r.calls_used for r in checked),
        errors=errors + [e for r in checked for e in r.errors],
        checked=chosen,
        shortlist_size=len(short),
        outside_window=outside,
    )
