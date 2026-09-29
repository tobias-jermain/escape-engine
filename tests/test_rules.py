from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from escape_engine.core.models import Flight, TripRules, Verdict
from escape_engine.core.pricing import MissingRateError
from escape_engine.core.rules import evaluate, fmt_duration

from .conftest import KRAKOW, LONDON, NOW, at, flight

HOME = {"STN", "LTN", "LGW", "LHR", "SEN", "LCY"}
RATES = {"EUR": Decimal("0.85"), "PLN": Decimal("0.19")}


def run(out: Flight, back: Flight, **rule_overrides: object):  # type: ignore[no-untyped-def]
    rules = TripRules.model_validate(rule_overrides)
    return evaluate(
        out, back, rules=rules, home_airports=HOME, home_tz=LONDON, now=NOW, rates=RATES
    )


def test_classic_day_trip_is_ok(out_leg: Flight, back_leg: Flight) -> None:
    trip = run(out_leg, back_leg)
    assert trip.verdict is Verdict.OK, trip.reasons
    assert trip.price.amount == Decimal("40")
    assert trip.ground_time == timedelta(hours=10, minutes=45)
    assert trip.usable_time == timedelta(hours=8, minutes=30)
    assert trip.warnings == ()


def test_departure_rule_uses_home_time_not_destination_time(back_leg: Flight) -> None:
    # 04:30 UK is 05:30 in Krakow: must still be rejected against a 05:00 UK rule.
    early = flight("STN", "KRK", at(2026, 11, 2, 4, 30, LONDON), at(2026, 11, 2, 7, 55, KRAKOW))
    trip = run(early, back_leg)
    assert trip.verdict is Verdict.REJECTED
    assert "before 05:00" in trip.reasons[0]
    assert run(early, back_leg, depart_after=time(4, 0)).verdict is Verdict.OK


def test_late_return_needs_next_day_slider(out_leg: Flight) -> None:
    late = flight("KRK", "STN", at(2026, 11, 3, 0, 5, KRAKOW), at(2026, 11, 3, 1, 30, LONDON))
    assert run(out_leg, late).verdict is Verdict.REJECTED
    assert run(out_leg, late, return_by=timedelta(hours=26, minutes=30)).verdict is Verdict.OK


def test_return_by_cannot_exceed_0230_next_day() -> None:
    with pytest.raises(ValidationError):
        TripRules(return_by=timedelta(hours=26, minutes=31))


def test_overnight_moves_deadline_a_day(out_leg: Flight) -> None:
    next_night = flight(
        "KRK", "STN", at(2026, 11, 3, 20, 40, KRAKOW), at(2026, 11, 3, 22, 5, LONDON)
    )
    assert run(out_leg, next_night).verdict is Verdict.REJECTED
    assert run(out_leg, next_night, overnight=True).verdict is Verdict.OK


def test_too_little_ground_time_is_rejected(out_leg: Flight) -> None:
    quick = flight("KRK", "STN", at(2026, 11, 2, 15, 0, KRAKOW), at(2026, 11, 2, 16, 25, LONDON))
    trip = run(out_leg, quick)
    assert trip.verdict is Verdict.REJECTED
    assert "on the ground" in trip.reasons[0]


def test_tight_but_legal_trip_is_kept_with_warning(out_leg: Flight) -> None:
    # 6h15m on the ground; 2h15m of airport buffers leaves 4h00m usable, under a 5h minimum.
    back = flight("KRK", "STN", at(2026, 11, 2, 16, 10, KRAKOW), at(2026, 11, 2, 17, 35, LONDON))
    trip = run(out_leg, back, min_usable=timedelta(hours=5))
    assert trip.verdict is Verdict.OK
    assert any(w.startswith("tight") for w in trip.warnings)


def test_open_jaw_home_airport(out_leg: Flight) -> None:
    to_luton = flight("KRK", "LTN", at(2026, 11, 2, 20, 40, KRAKOW), at(2026, 11, 2, 22, 5, LONDON))
    allowed = run(out_leg, to_luton)
    assert allowed.verdict is Verdict.OK
    assert "returns to LTN, not STN" in allowed.warnings
    assert run(out_leg, to_luton, allow_open_jaw=False).verdict is Verdict.REJECTED


def test_return_from_different_destination_is_rejected(out_leg: Flight) -> None:
    from_wroclaw = flight(
        "WRO", "STN", at(2026, 11, 2, 20, 40, KRAKOW), at(2026, 11, 2, 22, 5, LONDON)
    )
    assert run(out_leg, from_wroclaw).verdict is Verdict.REJECTED


def test_return_to_non_home_airport_is_rejected(out_leg: Flight) -> None:
    to_bristol = flight(
        "KRK", "BRS", at(2026, 11, 2, 20, 40, KRAKOW), at(2026, 11, 2, 22, 5, LONDON)
    )
    trip = run(out_leg, to_bristol)
    assert trip.verdict is Verdict.REJECTED
    assert any("not a home airport" in r for r in trip.reasons)


def test_connections_are_last_resort_flag(out_leg: Flight) -> None:
    via = flight(
        "KRK", "STN", at(2026, 11, 2, 18, 0, KRAKOW), at(2026, 11, 2, 22, 5, LONDON), stops=1
    )
    assert run(out_leg, via).verdict is Verdict.REJECTED
    allowed = run(out_leg, via, allow_connections=True)
    assert allowed.verdict is Verdict.OK
    assert any("stop" in w for w in allowed.warnings)


def test_stale_fare_is_never_bookable(out_leg: Flight, back_leg: Flight) -> None:
    stale = back_leg.model_copy(update={"fetched_at": NOW - timedelta(hours=3, minutes=1)})
    trip = run(out_leg, stale)
    assert trip.verdict is Verdict.REJECTED
    assert "old" in trip.reasons[0]
    fresh_enough = back_leg.model_copy(update={"fetched_at": NOW - timedelta(hours=3)})
    assert run(out_leg, fresh_enough).verdict is Verdict.OK


@pytest.mark.parametrize(
    ("back_price", "verdict"),
    [
        ("55", Verdict.OK),  # 75.00 exactly
        ("70", Verdict.JUST_OVER),  # 90.00 = 75 + 20%
        ("70.01", Verdict.REJECTED),
    ],
)
def test_price_bands(out_leg: Flight, back_leg: Flight, back_price: str, verdict: Verdict) -> None:
    back = back_leg.model_copy(
        update={"price": back_leg.price.model_copy(update={"amount": Decimal(back_price)})}
    )
    assert run(out_leg, back).verdict is verdict


def test_foreign_currency_is_converted_with_warning(out_leg: Flight) -> None:
    back = flight(
        "KRK",
        "STN",
        at(2026, 11, 2, 20, 40, KRAKOW),
        at(2026, 11, 2, 22, 5, LONDON),
        price="100",
        currency="PLN",
    )
    trip = run(out_leg, back)
    assert trip.price.amount == Decimal("39.00")
    assert "FR1234 converted from PLN" in trip.warnings


def test_missing_rate_is_a_config_error(out_leg: Flight) -> None:
    back = flight(
        "KRK",
        "STN",
        at(2026, 11, 2, 20, 40, KRAKOW),
        at(2026, 11, 2, 22, 5, LONDON),
        price="10",
        currency="HUF",
    )
    with pytest.raises(MissingRateError):
        run(out_leg, back)


def test_bundled_extras_warn_not_reject(out_leg: Flight, back_leg: Flight) -> None:
    bagged = back_leg.model_copy(update={"includes": ("cabin_bag",)})
    trip = run(out_leg, bagged)
    assert trip.verdict is Verdict.OK
    assert "FR1234 fare includes cabin_bag" in trip.warnings


def test_dst_change_day_deadline_is_wall_clock() -> None:
    # UK clocks go back at 02:00 on Sun 25 Oct 2026: the day is 25 hours long.
    out = flight("STN", "KRK", at(2026, 10, 25, 6, 0, LONDON), at(2026, 10, 25, 9, 25, KRAKOW))
    back = flight("KRK", "STN", at(2026, 10, 25, 22, 30, KRAKOW), at(2026, 10, 25, 23, 55, LONDON))
    trip = run(out, back)
    assert trip.verdict is Verdict.OK, trip.reasons
    assert trip.ground_time == timedelta(hours=13, minutes=5)


def test_ground_time_is_elapsed_time_across_dst_change() -> None:
    # Dublin clocks go back at 02:00 on 25 Oct 2026: 00:30 -> 07:00 local is 7h30m elapsed.
    dub = ZoneInfo("Europe/Dublin")
    out = flight("STN", "DUB", at(2026, 10, 24, 23, 0, LONDON), at(2026, 10, 25, 0, 30, dub))
    back = flight("DUB", "STN", at(2026, 10, 25, 7, 0, dub), at(2026, 10, 25, 8, 15, LONDON))
    trip = run(out, back, overnight=True, min_ground=timedelta(hours=7))
    assert trip.ground_time == timedelta(hours=7, minutes=30)
    assert trip.verdict is Verdict.OK, trip.reasons


def test_other_home_region_needs_no_code_change() -> None:
    ny = ZoneInfo("America/New_York")
    out = flight(
        "JFK", "BOS", at(2026, 11, 2, 6, 0, ny), at(2026, 11, 2, 7, 20, ny), currency="USD"
    )
    back = flight(
        "BOS", "JFK", at(2026, 11, 2, 20, 0, ny), at(2026, 11, 2, 21, 20, ny), currency="USD"
    )
    trip = evaluate(
        out,
        back,
        rules=TripRules(currency="USD", max_price=Decimal("100")),
        home_airports={"JFK"},
        home_tz=ny,
        now=NOW,
        rates={},
    )
    assert trip.verdict is Verdict.OK, trip.reasons


def test_fmt_duration() -> None:
    assert fmt_duration(timedelta(hours=6, minutes=5)) == "6h05m"
    assert fmt_duration(timedelta(minutes=-30)) == "-0h30m"
