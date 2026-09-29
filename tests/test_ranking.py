from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from escape_engine.core.models import DayTrip, Flight, Money, Verdict
from escape_engine.core.ranking import rank

TODAY = date(2026, 11, 1)


def trip(base: Flight, price: str, day: int, usable_h: int) -> DayTrip:
    return DayTrip(
        outbound=base,
        inbound=base,
        trip_date=date(2026, 11, day),
        verdict=Verdict.OK,
        price=Money(amount=Decimal(price), currency="GBP"),
        ground_time=timedelta(hours=usable_h + 2),
        usable_time=timedelta(hours=usable_h),
    )


def test_default_order_price_then_date_then_usable(out_leg: Flight) -> None:
    a = trip(out_leg, "40", 10, 8)
    b = trip(out_leg, "30", 20, 5)
    c = trip(out_leg, "40", 5, 6)
    d = trip(out_leg, "40", 5, 9)
    assert rank([a, b, c, d], today=TODAY) == [b, d, c, a]


def test_custom_order(out_leg: Flight) -> None:
    a = trip(out_leg, "40", 10, 8)
    b = trip(out_leg, "30", 20, 5)
    assert rank([a, b], today=TODAY, order=["date"]) == [a, b]
    assert rank([a, b], today=TODAY, order=["usable"]) == [a, b]


def test_unknown_key(out_leg: Flight) -> None:
    with pytest.raises(ValueError):
        rank([], today=TODAY, order=["vibes"])  # type: ignore[list-item]
