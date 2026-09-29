"""Ordering of valid trips: price, then closest date, then usable hours (configurable)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from escape_engine.core.models import DayTrip

SortKey = Literal["price", "date", "usable"]
DEFAULT_ORDER: tuple[SortKey, ...] = ("price", "date", "usable")


def _key_fns(today: date) -> dict[SortKey, Callable[[DayTrip], Decimal | int | float]]:
    return {
        "price": lambda t: t.price.amount,
        "date": lambda t: (t.trip_date - today).days,
        "usable": lambda t: -t.usable_time.total_seconds(),  # more usable time first
    }


def rank(
    trips: Iterable[DayTrip], *, today: date, order: Sequence[SortKey] = DEFAULT_ORDER
) -> list[DayTrip]:
    """Sort trips by ``order``; keys not named are appended in default order as tie-breakers."""
    fns = _key_fns(today)
    unknown = set(order) - fns.keys()
    if unknown:
        raise ValueError(f"unknown sort key(s): {', '.join(sorted(unknown))}")
    full = list(dict.fromkeys([*order, *DEFAULT_ORDER]))
    return sorted(trips, key=lambda t: tuple(fns[k](t) for k in full))
