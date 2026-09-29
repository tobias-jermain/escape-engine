from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from escape_engine.cache import Cache
from escape_engine.core.models import Candidate, Money, TripRules
from escape_engine.providers.base import ExploreQuery, ProviderError
from escape_engine.providers.serpapi import SerpApiExplore, parse_explore
from escape_engine.search.engine import BudgetError, Engine
from escape_engine.search.explore import explore, months_in, shortlist, window

from .conftest import KRAKOW, LONDON, at, flight
from .test_engine import LON, FakeProvider

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "serpapi_explore_lon_oct.json").read_text()
)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # window: Fri 2 Oct .. Thu 22 Oct


def cand(code: str, day: date, price: str, minutes: int = 120, stops: int = 0) -> Candidate:
    return Candidate(
        destination=code,
        city=code,
        country="X",
        day=day,
        price=Money(amount=Decimal(price), currency="GBP"),
        flight_minutes=minutes,
        stops=stops,
        source="fake",
    )


class FakeDiscovery:
    name = "fake-explore"

    def __init__(self, candidates: list[Candidate], *, fail: bool = False) -> None:
        self.candidates = candidates
        self.fail = fail
        self.calls: list[ExploreQuery] = []

    def configured(self) -> bool:
        return True

    async def explore(self, query: ExploreQuery) -> list[Candidate]:
        self.calls.append(query)
        if self.fail:
            raise ProviderError("quota exhausted")
        return [c for c in self.candidates if c.day.month == query.month]


# --- Parsing the real response -----------------------------------------------------------


def test_parse_recorded_explore_response() -> None:
    cands = parse_explore(FIXTURE, currency="GBP")
    codes = [c.destination for c in cands]
    assert len(codes) == len(set(codes)) == 44  # 66 rows, duplicates per airport merged
    assert [c.price.amount for c in cands] == sorted(c.price.amount for c in cands)
    ork = next(c for c in cands if c.destination == "ORK")
    assert (ork.city, ork.day, ork.price.amount, ork.airline) == (
        "Cork",
        date(2026, 10, 7),
        Decimal("13"),
        "FR",
    )
    bgy = next(c for c in cands if c.destination == "BGY")
    assert bgy.city == "Milan"  # the airport's city, not "Lake Como"


def test_explore_params() -> None:
    p = SerpApiExplore("k").explore_params(ExploreQuery(("STN", "LTN"), 10))
    assert p["engine"] == "google_travel_explore"
    assert (p["type"], p["month"], p["stops"], p["departure_id"]) == ("2", "10", "1", "STN,LTN")


# --- Window and shortlist ----------------------------------------------------------------


def test_window_and_months() -> None:
    assert window(date(2026, 9, 29), 21) == (date(2026, 9, 30), date(2026, 10, 20))
    assert months_in(date(2026, 9, 30), date(2026, 10, 20)) == [10]  # 1 day of Sep skipped
    assert months_in(date(2026, 10, 25), date(2026, 11, 14)) == [10, 11]
    assert months_in(date(2026, 12, 20), date(2027, 1, 9)) == [12, 1]


def test_shortlist_filters_and_orders() -> None:
    rules = TripRules()
    start, end = date(2026, 10, 2), date(2026, 10, 22)
    found = [
        cand("DUB", date(2026, 10, 7), "15"),
        cand("ORK", date(2026, 10, 7), "13"),
        cand("ORK", date(2026, 10, 9), "13"),  # same price, later date: dropped
        cand("BCN", date(2026, 10, 28), "10"),  # outside the window
        cand("AYT", date(2026, 10, 10), "20", minutes=245),  # too long for a day trip
        cand("KRK", date(2026, 10, 10), "95"),  # can't fit with a return
        cand("PRG", date(2026, 10, 10), "20", stops=1),  # not direct
        cand("STN", date(2026, 10, 10), "5"),  # a home airport
        cand("NCE", date(2026, 10, 12), "15"),
    ]
    short, outside = shortlist(found, start=start, end=end, rules=rules, origins=LON)
    assert [(c.destination, c.day.day) for c in short] == [("ORK", 7), ("DUB", 7), ("NCE", 12)]
    assert outside == 1


# --- End to end with fakes ---------------------------------------------------------------


def krk_legs() -> list:  # type: ignore[type-arg]
    return [
        flight("STN", "KRK", at(2026, 10, 7, 6, 30, LONDON), at(2026, 10, 7, 9, 55, KRAKOW), "12"),
        flight(
            "KRK",
            "STN",
            at(2026, 10, 7, 20, 40, KRAKOW),
            at(2026, 10, 7, 22, 5, LONDON),
            "14",
            flight_number="4321",
            fetched_at=NOW,
        ),
    ]


def run(engine: Engine, discovery: FakeDiscovery, **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {"origins": LON, "rules": TripRules(), "now": NOW}
    args.update(kw)
    return asyncio.run(explore(engine, discovery, **args))  # type: ignore[arg-type]


def fresh(legs: list) -> list:  # type: ignore[type-arg]
    return [f.model_copy(update={"fetched_at": NOW}) for f in legs]


def test_explore_discovers_then_verifies_cheapest_first() -> None:
    provider = FakeProvider("fake", fresh(krk_legs()))
    discovery = FakeDiscovery(
        [
            cand("KRK", date(2026, 10, 7), "12"),
            cand("BCN", date(2026, 10, 8), "30"),
            cand("MAD", date(2026, 10, 9), "40"),
            cand("OPO", date(2026, 10, 10), "50"),
            cand("LIS", date(2026, 10, 11), "60"),
        ]
    )
    result = run(Engine([provider]), discovery)
    assert [q.month for q in discovery.calls] == [10]
    # budget 10 = 1 discovery + 4 checks x 2 calls: the 4 cheapest are verified
    assert [c.destination for c in result.checked] == ["KRK", "BCN", "MAD", "OPO"]
    assert result.shortlist_size == 5
    assert result.calls_used == 9
    assert [(t.outbound.destination, t.price.amount) for t in result.trips] == [
        ("KRK", Decimal("26"))
    ]


def test_budget_too_small() -> None:
    with pytest.raises(BudgetError):
        run(Engine([FakeProvider("fake", [])]), FakeDiscovery([]), budget=2)


def test_discovery_is_cached(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "c.sqlite3")
    discovery = FakeDiscovery([cand("KRK", date(2026, 10, 7), "12")])
    engine = Engine([FakeProvider("fake", fresh(krk_legs()))], cache=cache)
    first = run(engine, discovery)
    second = run(engine, discovery)
    assert len(discovery.calls) == 1
    assert (first.calls_used, second.calls_used) == (3, 0)
    cache.close()


def test_discovery_failure_is_reported() -> None:
    result = run(Engine([FakeProvider("fake", [])]), FakeDiscovery([], fail=True))
    assert result.errors == ["fake-explore: quota exhausted"]
    assert result.trips == [] and result.checked == []
