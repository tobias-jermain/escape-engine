"""Core data models shared by the engine, CLI and (later) the HTTP API."""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

# Latest a return flight may land, measured from midnight of the trip day (02:30 next day).
RETURN_BY_CEILING = timedelta(hours=26, minutes=30)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Money(_Frozen):
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError(f"cannot add {other.currency} to {self.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


class Airport(_Frozen):
    iata: str
    icao: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    tz: str


class Flight(_Frozen):
    """One flight leg as quoted by a provider. Times are timezone-aware."""

    carrier: str
    flight_number: str
    origin: str
    destination: str
    departs_at: AwareDatetime
    arrives_at: AwareDatetime
    stops: int = 0
    price: Money
    """One-way fare per person with the minimum add-ons the provider offers."""
    includes: tuple[str, ...] = ()
    """Extras bundled into the fare (e.g. ``"cabin_bag"``) that make it more than the minimum."""
    source: str
    fetched_at: AwareDatetime
    booking_url: str | None = None


class TripRules(_Frozen):
    """The user-adjustable "sliders" that define a valid extreme day trip."""

    depart_after: time = time(5, 0)
    """Earliest outbound departure, home-local time."""
    return_by: timedelta = timedelta(hours=23, minutes=59)
    """Latest inbound landing, measured from midnight of the trip day (max 26:30)."""
    min_ground: timedelta = timedelta(hours=6)
    """Minimum landing-to-return-departure time at the destination."""
    min_usable: timedelta = timedelta(hours=4)
    """Below this many usable hours a trip is still shown, but with a warning."""
    arrival_buffer: timedelta = timedelta(minutes=45)
    departure_buffer: timedelta = timedelta(minutes=90)
    overnight: bool = False
    """Allow a night away: the return deadline moves one day later."""
    allow_connections: bool = False
    allow_open_jaw: bool = True
    """Allow returning to a different home airport than the one departed from."""
    max_price: Decimal = Decimal("75")
    """Return fare per person, in ``currency``."""
    stretch: Decimal = Decimal("0.20")
    """Fraction above ``max_price`` still shown in the "just over" section."""
    currency: str = Field(default="GBP", pattern=r"^[A-Z]{3}$")
    max_age: timedelta = timedelta(hours=3)
    """Oldest a fare may be and still be shown as bookable."""

    @field_validator("return_by")
    @classmethod
    def _return_by_ceiling(cls, v: timedelta) -> timedelta:
        if not timedelta(0) < v <= RETURN_BY_CEILING:
            raise ValueError("return_by must be after 00:00 and no later than 02:30 next day")
        return v

    @field_validator("stretch", "max_price")
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("must not be negative")
        return v


class Verdict(StrEnum):
    OK = "ok"
    JUST_OVER = "just_over"
    REJECTED = "rejected"


class DayTrip(_Frozen):
    """An outbound + inbound pair evaluated against ``TripRules``."""

    outbound: Flight
    inbound: Flight
    trip_date: date
    """Home-local date of the outbound departure."""
    verdict: Verdict
    price: Money
    """Return fare per person in the rules' currency."""
    ground_time: timedelta
    usable_time: timedelta
    reasons: tuple[str, ...] = ()
    """Why the trip was rejected (empty unless ``verdict`` is ``rejected``)."""
    warnings: tuple[str, ...] = ()


class Candidate(_Frozen):
    """A cheap destination found by discovery. Indicative only: never shown as bookable."""

    destination: str
    """IATA code of the arrival airport."""
    city: str
    country: str
    day: date
    """The date the discovery source found the cheapest one-way fare."""
    price: Money
    """Cheapest one-way fare per person on ``day`` (indicative)."""
    flight_minutes: int | None = None
    stops: int = 0
    airline: str = ""
    source: str
