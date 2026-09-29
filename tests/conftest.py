from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from escape_engine.core.models import Flight, Money

LONDON = ZoneInfo("Europe/London")
KRAKOW = ZoneInfo("Europe/Warsaw")
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=LONDON)


def at(y: int, mo: int, d: int, h: int, mi: int, tz: ZoneInfo) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=tz)


def flight(
    origin: str,
    destination: str,
    departs: datetime,
    arrives: datetime,
    price: str = "20",
    currency: str = "GBP",
    **extra: object,
) -> Flight:
    fields: dict[str, object] = {
        "carrier": "FR",
        "flight_number": "1234",
        "origin": origin,
        "destination": destination,
        "departs_at": departs,
        "arrives_at": arrives,
        "price": Money(amount=Decimal(price), currency=currency),
        "source": "test",
        "fetched_at": NOW,
    }
    fields.update(extra)
    return Flight.model_validate(fields)


@pytest.fixture
def out_leg() -> Flight:
    """STN 06:30 -> KRK 09:55 local on Mon 2 Nov 2026."""
    return flight("STN", "KRK", at(2026, 11, 2, 6, 30, LONDON), at(2026, 11, 2, 9, 55, KRAKOW))


@pytest.fixture
def back_leg() -> Flight:
    """KRK 20:40 -> STN 22:05 UK on the same day."""
    return flight("KRK", "STN", at(2026, 11, 2, 20, 40, KRAKOW), at(2026, 11, 2, 22, 5, LONDON))


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Keep every test away from the real settings, credentials, update state and cache."""
    from escape_engine import cache, keystore, settings, update

    home = tmp_path_factory.mktemp("user")
    monkeypatch.setattr(settings, "settings_path", lambda: home / "settings.json")
    monkeypatch.setattr(keystore, "credentials_path", lambda: home / "credentials.json")
    monkeypatch.setattr(update, "_state_path", lambda: home / "update.json")
    monkeypatch.setattr(cache, "default_path", lambda: home / "cache.sqlite3")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    return home
