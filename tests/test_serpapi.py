from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from escape_engine.providers.base import OneWayQuery, Provider, ProviderConfigError, ProviderError
from escape_engine.providers.serpapi import SerpApiFlights, parse

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "serpapi_one_way.json").read_text())
QUERY = OneWayQuery(origins=("STN", "LTN", "LGW"), destinations=("KRK",), day=date(2026, 11, 14))
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


def test_is_a_provider() -> None:
    assert isinstance(SerpApiFlights("k"), Provider)


def test_parse_fixture() -> None:
    flights = parse(FIXTURE, query=QUERY, fetched_at=NOW)
    by_number = {f.carrier + f.flight_number: f for f in flights}
    # duplicate FR2446 keeps the cheaper quote; the priceless option is dropped
    assert set(by_number) == {"FR2446", "W95301", "U28871/1995"}
    fr = by_number["FR2446"]
    assert fr.price.amount == Decimal("19.00")
    assert fr.price.currency == "GBP"
    assert fr.departs_at.utcoffset() == timedelta(0)  # London, winter
    assert fr.arrives_at.utcoffset() == timedelta(hours=1)  # Krakow, winter
    assert fr.stops == 0
    assert fr.fetched_at == NOW
    assert by_number["U28871/1995"].stops == 1


def test_price_is_per_person() -> None:
    query = OneWayQuery(origins=("STN",), destinations=("KRK",), day=date(2026, 11, 14), pax=2)
    flights = parse(FIXTURE, query=query, fetched_at=NOW)
    assert min(f.price.amount for f in flights) == Decimal("9.50")


def test_no_results_is_empty_not_error() -> None:
    data = {"error": "Google Flights hasn't returned any results for this query."}
    assert parse(data, query=QUERY, fetched_at=NOW) == []


def test_other_errors_raise() -> None:
    with pytest.raises(ProviderError, match="Invalid API key"):
        parse({"error": "Invalid API key."}, query=QUERY, fetched_at=NOW)


def test_params() -> None:
    p = SerpApiFlights("k").params(QUERY)
    assert p["type"] == "2"
    assert p["departure_id"] == "STN,LTN,LGW"
    assert p["stops"] == "1"
    assert "api_key" not in p


def test_missing_key() -> None:
    with pytest.raises(ProviderConfigError):
        asyncio.run(SerpApiFlights("").one_way(QUERY))


def test_http_call_sends_key_as_header_not_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FIXTURE)

    async def go() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return len(await SerpApiFlights("secret", client=client).one_way(QUERY))

    assert asyncio.run(go()) == 3
    assert seen[0].headers["Authorization"] == "Bearer secret"
    assert "secret" not in str(seen[0].url)


def test_network_error_does_not_leak_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await SerpApiFlights("secret", client=client).one_way(QUERY)

    with pytest.raises(ProviderError) as exc:
        asyncio.run(go())
    assert "secret" not in str(exc.value)
