from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from escape_engine.cache import Cache
from escape_engine.core.models import Flight, TripRules
from escape_engine.providers.base import OneWayQuery, ProviderError
from escape_engine.search.engine import BudgetError, Engine

from .conftest import KRAKOW, LONDON, NOW, at, flight

DAY = date(2026, 11, 2)
LON = ["LHR", "LGW", "STN", "LTN", "SEN", "LCY"]


class FakeProvider:
    live = True

    def __init__(self, name: str, flights: list[Flight], *, fail: bool = False) -> None:
        self.name = name
        self.flights = flights
        self.fail = fail
        self.calls: list[OneWayQuery] = []

    def configured(self) -> bool:
        return True

    async def one_way(self, query: OneWayQuery) -> Sequence[Flight]:
        self.calls.append(query)
        if self.fail:
            raise ProviderError("quota exhausted")
        return [
            f
            for f in self.flights
            if f.origin in query.origins
            and f.destination in query.destinations
            and f.departs_at.date() == query.day
        ]


def legs() -> list[Flight]:
    return [
        flight("STN", "KRK", at(2026, 11, 2, 6, 30, LONDON), at(2026, 11, 2, 9, 55, KRAKOW), "15"),
        flight(
            "LTN",
            "KRK",
            at(2026, 11, 2, 12, 0, LONDON),
            at(2026, 11, 2, 15, 25, KRAKOW),
            "9",
            flight_number="777",
        ),
        flight(
            "KRK",
            "STN",
            at(2026, 11, 2, 20, 40, KRAKOW),
            at(2026, 11, 2, 22, 5, LONDON),
            "25",
            flight_number="4321",
        ),
        flight(
            "KRK",
            "LTN",
            at(2026, 11, 2, 21, 0, KRAKOW),
            at(2026, 11, 2, 22, 30, LONDON),
            "60",
            flight_number="999",
        ),
    ]


def run(engine: Engine, **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "origins": LON,
        "destination": "KRK",
        "day": DAY,
        "rules": TripRules(),
        "now": NOW,
    }
    args.update(kw)
    return asyncio.run(engine.check(**args))  # type: ignore[arg-type]


def test_pairs_filters_and_ranks() -> None:
    result = run(Engine([FakeProvider("fake", legs())]))
    # The 12:00 LTN departure lands 15:25, under 6h before either return, so both its pairs fail.
    # STN out + LTN back = 15 + 60 = 75: exactly the limit, so it is a valid open-jaw trip.
    assert [(t.outbound.origin, t.inbound.destination, t.price.amount) for t in result.trips] == [
        ("STN", "STN", Decimal("40")),
        ("STN", "LTN", Decimal("75")),
    ]
    assert len(result.rejected) == 2
    assert result.top_reasons() == [("on the ground", 2)]
    assert result.calls_used == 2


def test_open_jaw_and_just_over_band() -> None:
    result = run(Engine([FakeProvider("fake", legs())]), rules=TripRules(max_price=Decimal("70")))
    assert [t.price.amount for t in result.trips] == [Decimal("40")]
    assert [(t.inbound.destination, t.price.amount) for t in result.just_over] == [
        ("LTN", Decimal("75"))
    ]


def test_same_flight_from_two_providers_is_deduped_cheapest_kept() -> None:
    cheaper = [f.model_copy(update={"source": "b"}) for f in legs()]
    cheaper[0] = cheaper[0].model_copy(
        update={"price": cheaper[0].price.model_copy(update={"amount": Decimal("5")})}
    )
    result = run(Engine([FakeProvider("a", legs()), FakeProvider("b", cheaper)]))
    assert result.trips[0].price.amount == Decimal("30")
    assert result.calls_used == 4


def test_budget_checked_before_spending() -> None:
    fake = FakeProvider("fake", legs())
    with pytest.raises(BudgetError):
        run(Engine([fake]), budget=1)
    assert fake.calls == []


def test_large_home_groups_are_split_into_chunks() -> None:
    fake = FakeProvider("fake", legs())
    many = [*LON, "BHX", "MAN", "BRS"]
    run(Engine([fake]), origins=many)
    assert len(fake.calls) == 4  # 9 airports -> 2 chunks each way
    assert all(len(q.origins) <= 7 for q in fake.calls if q.destinations == ("KRK",))


def test_overnight_also_searches_next_day_returns() -> None:
    fake = FakeProvider("fake", legs())
    run(Engine([fake]), rules=TripRules(overnight=True))
    assert sorted(q.day for q in fake.calls) == [DAY, DAY, date(2026, 11, 3)]


def test_provider_error_is_reported_not_fatal() -> None:
    result = run(Engine([FakeProvider("ok", legs()), FakeProvider("bad", [], fail=True)]))
    assert result.trips
    assert result.errors == ["bad: quota exhausted", "bad: quota exhausted"]


def test_no_configured_provider() -> None:
    with pytest.raises(ProviderError):
        run(Engine([]))


def test_cache_hits_do_not_spend_budget(tmp_path: Path) -> None:
    fake = FakeProvider("fake", legs())
    cache = Cache(tmp_path / "c.sqlite3")
    engine = Engine([fake], cache=cache)
    run(engine)
    second = run(engine)
    assert second.calls_used == 0
    assert len(fake.calls) == 2
    assert run(Engine([fake], cache=cache, use_cache=False)).calls_used == 2
    cache.close()


def test_foreign_fares_use_rates() -> None:
    eur = [
        f.model_copy(update={"price": f.price.model_copy(update={"currency": "EUR"})})
        for f in legs()
    ]

    async def rates(target: str) -> dict[str, Decimal]:
        assert target == "GBP"
        return {"EUR": Decimal("0.5")}

    result = run(Engine([FakeProvider("fake", eur)], rates=rates))
    assert result.trips[0].price.amount == Decimal("20.00")
