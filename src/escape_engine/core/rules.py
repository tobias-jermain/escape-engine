"""Day-trip validity: turns an outbound + inbound flight pair into an evaluated ``DayTrip``.

All time rules are applied in the traveller's home timezone, so the same code works for
any home region. Nothing here touches the network.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from escape_engine.core.models import DayTrip, Flight, TripRules, Verdict
from escape_engine.core.pricing import classify, convert


def _utc(dt: datetime) -> datetime:
    # Python ignores UTC offsets when both operands share a tzinfo object, which gives
    # wall-clock (not elapsed) results across DST changes. Always compare in UTC.
    return dt.astimezone(UTC)


def fmt_duration(td: timedelta) -> str:
    sign = "-" if td < timedelta(0) else ""
    minutes = abs(int(td.total_seconds())) // 60
    return f"{sign}{minutes // 60}h{minutes % 60:02d}m"


def evaluate(
    outbound: Flight,
    inbound: Flight,
    *,
    rules: TripRules,
    home_airports: Collection[str],
    home_tz: ZoneInfo,
    now: datetime,
    rates: Mapping[str, Decimal],
) -> DayTrip:
    """Evaluate a flight pair. Rejections are collected, not raised, so callers can explain them.

    Raises ``MissingRateError`` if a fare's currency cannot be converted: that is a
    configuration error, not a property of the trip.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    # --- Route shape -------------------------------------------------------------------
    if outbound.origin not in home_airports:
        reasons.append(f"outbound departs {outbound.origin}, not a home airport")
    if inbound.destination not in home_airports:
        reasons.append(f"return lands at {inbound.destination}, not a home airport")
    if inbound.origin != outbound.destination:
        reasons.append(
            f"return departs {inbound.origin}, but outbound lands at {outbound.destination}"
        )
    if inbound.destination != outbound.origin:
        if rules.allow_open_jaw:
            warnings.append(f"returns to {inbound.destination}, not {outbound.origin}")
        else:
            reasons.append(f"returns to {inbound.destination}, not {outbound.origin}")

    for leg in (outbound, inbound):
        if leg.stops:
            msg = f"{leg.carrier}{leg.flight_number} has {leg.stops} stop(s)"
            (warnings if rules.allow_connections else reasons).append(msg)
        if _utc(leg.arrives_at) <= _utc(leg.departs_at):
            reasons.append(f"{leg.carrier}{leg.flight_number} arrives before it departs")

    # --- Timing (home-local) -------------------------------------------------------------
    local_departure = outbound.departs_at.astimezone(home_tz)
    trip_date = local_departure.date()
    if local_departure.time() < rules.depart_after:
        reasons.append(f"departs {local_departure:%H:%M}, before {rules.depart_after:%H:%M}")

    # Wall-clock arithmetic from local midnight, so "23:59" means 23:59 even on DST days.
    deadline = datetime.combine(trip_date, time(0), tzinfo=home_tz) + rules.return_by
    if rules.overnight:
        deadline += timedelta(days=1)
    local_return = inbound.arrives_at.astimezone(home_tz)
    if _utc(inbound.arrives_at) > _utc(deadline):
        reasons.append(f"lands home {local_return:%a %H:%M}, after {deadline:%a %H:%M}")

    ground_time = _utc(inbound.departs_at) - _utc(outbound.arrives_at)
    usable_time = ground_time - rules.arrival_buffer - rules.departure_buffer
    if ground_time < timedelta(0):
        reasons.append("return departs before outbound lands")
    elif ground_time < rules.min_ground:
        reasons.append(
            f"only {fmt_duration(ground_time)} on the ground, need {fmt_duration(rules.min_ground)}"
        )
    elif usable_time < rules.min_usable:
        warnings.append(f"tight: about {fmt_duration(usable_time)} usable after airport buffers")

    # --- Freshness -----------------------------------------------------------------------
    for leg in (outbound, inbound):
        age = _utc(now) - _utc(leg.fetched_at)
        if age > rules.max_age:
            reasons.append(
                f"{leg.carrier}{leg.flight_number} fare is {fmt_duration(age)} old "
                f"(max {fmt_duration(rules.max_age)})"
            )

    # --- Price ---------------------------------------------------------------------------
    price = convert(outbound.price, rules.currency, rates) + convert(
        inbound.price, rules.currency, rates
    )
    for leg in (outbound, inbound):
        if leg.price.currency != rules.currency:
            warnings.append(f"{leg.carrier}{leg.flight_number} converted from {leg.price.currency}")
        if leg.includes:
            warnings.append(
                f"{leg.carrier}{leg.flight_number} fare includes {', '.join(leg.includes)}"
            )

    band = classify(price, rules)
    if band is Verdict.REJECTED:
        reasons.append(f"{price} is over {rules.max_price} {rules.currency} (+{rules.stretch:.0%})")

    return DayTrip(
        outbound=outbound,
        inbound=inbound,
        trip_date=trip_date,
        verdict=Verdict.REJECTED if reasons else band,
        price=price,
        ground_time=ground_time,
        usable_time=usable_time,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
