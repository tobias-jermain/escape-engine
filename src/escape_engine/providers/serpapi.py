"""SerpApi Google Flights provider (live quotes). Docs: https://serpapi.com/google-flights-api

The user supplies their own key via the ``SERPAPI_API_KEY`` environment variable.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from escape_engine.core import airports
from escape_engine.core.models import Flight, Money
from escape_engine.providers.base import OneWayQuery, ProviderConfigError, ProviderError

ENDPOINT = "https://serpapi.com/search.json"
KEY_ENV = "SERPAPI_API_KEY"
_NO_RESULTS = "hasn't returned any results"


class SerpApiFlights:
    name = "serpapi"
    live = True

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._key = api_key if api_key is not None else os.environ.get(KEY_ENV, "")
        self._client = client
        self._timeout = timeout

    def configured(self) -> bool:
        return bool(self._key)

    def params(self, query: OneWayQuery) -> dict[str, str]:
        params = {
            "engine": "google_flights",
            "type": "2",  # one way: out and back are searched separately (open-jaw friendly)
            "departure_id": ",".join(query.origins),
            "arrival_id": ",".join(query.destinations),
            "outbound_date": query.day.isoformat(),
            "adults": str(query.pax),
            "currency": query.currency,
            "hl": "en",
            "gl": "uk",
            "show_hidden": "true",
        }
        if query.nonstop:
            params["stops"] = "1"
        return params

    async def one_way(self, query: OneWayQuery) -> Sequence[Flight]:
        if not self.configured():
            raise ProviderConfigError(f"{KEY_ENV} is not set")
        # Key goes in a header, never the URL, so it cannot leak into logs or error messages.
        headers = {"Authorization": f"Bearer {self._key}"}
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.get(ENDPOINT, params=self.params(query), headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"serpapi request failed: {type(exc).__name__}") from None
        finally:
            if self._client is None:
                await client.aclose()
        try:
            data = resp.json()
        except ValueError:
            raise ProviderError(f"serpapi returned HTTP {resp.status_code}, not JSON") from None
        if not isinstance(data, dict):
            raise ProviderError(f"serpapi returned HTTP {resp.status_code}, unexpected body")
        if resp.status_code != 200 and not data.get("error"):
            raise ProviderError(f"serpapi returned HTTP {resp.status_code}")
        return parse(data, query=query, fetched_at=datetime.now(UTC))


def parse(data: Mapping[str, Any], *, query: OneWayQuery, fetched_at: datetime) -> list[Flight]:
    """Turn a Google Flights response into ``Flight`` objects (pure; used by tests)."""
    error = data.get("error")
    if error:
        if _NO_RESULTS in str(error):
            return []
        raise ProviderError(f"serpapi: {error}")

    booking_url = (data.get("search_metadata") or {}).get("google_flights_url")
    seen: dict[tuple[str, datetime], Flight] = {}
    for option in [*data.get("best_flights", []), *data.get("other_flights", [])]:
        flight = _parse_option(option, query=query, fetched_at=fetched_at, url=booking_url)
        if flight is None:
            continue
        key = (flight.carrier + flight.flight_number, flight.departs_at)
        if key not in seen or flight.price.amount < seen[key].price.amount:
            seen[key] = flight
    return list(seen.values())


def _parse_option(
    option: Mapping[str, Any], *, query: OneWayQuery, fetched_at: datetime, url: str | None
) -> Flight | None:
    legs: Sequence[Mapping[str, Any]] = option.get("flights") or []
    price = option.get("price")
    if not legs or price is None:
        return None
    first, last = legs[0], legs[-1]
    try:
        origin = first["departure_airport"]["id"]
        destination = last["arrival_airport"]["id"]
        departs = _local(first["departure_airport"]["time"], origin)
        arrives = _local(last["arrival_airport"]["time"], destination)
    except (KeyError, ValueError, LookupError):
        return None  # unknown airport or malformed leg: skip rather than guess

    numbers = [str(leg.get("flight_number", "")).split() for leg in legs]
    carrier = numbers[0][0] if numbers[0] else ""
    flight_number = "/".join(n[-1] for n in numbers if n)
    # Google Flights quotes the total for all passengers; normalise to per person.
    per_person = (Decimal(str(price)) / query.pax).quantize(Decimal("0.01"))
    return Flight(
        carrier=carrier,
        flight_number=flight_number,
        origin=origin,
        destination=destination,
        departs_at=departs,
        arrives_at=arrives,
        stops=len(legs) - 1,
        price=Money(amount=per_person, currency=query.currency),
        source=SerpApiFlights.name,
        fetched_at=fetched_at,
        booking_url=url,
    )


def _local(text: str, airport: str) -> datetime:
    """``"2026-11-02 06:30"`` at ``airport`` -> aware datetime in that airport's timezone."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=airports.timezone(airport))
