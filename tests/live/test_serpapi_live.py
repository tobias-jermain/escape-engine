"""Live SerpApi calls. Costs quota: run explicitly with ``uv run pytest -m live``."""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

import pytest

from escape_engine.providers.base import OneWayQuery
from escape_engine.providers.serpapi import KEY_ENV, SerpApiFlights

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get(KEY_ENV), reason=f"{KEY_ENV} not set"),
]


def test_stansted_to_krakow_one_way() -> None:
    day = date.today() + timedelta(days=30)
    query = OneWayQuery(origins=("STN", "LTN"), destinations=("KRK",), day=day)
    flights = asyncio.run(SerpApiFlights().one_way(query))
    assert flights, "expected at least one direct flight London -> Krakow"
    for f in flights:
        assert f.origin in {"STN", "LTN"}
        assert f.destination == "KRK"
        assert f.stops == 0
        assert f.departs_at.date() == day
        assert f.price.currency == "GBP"
        assert f.price.amount > 0
