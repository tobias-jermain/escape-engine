from __future__ import annotations

import pytest

from escape_engine.core import airports


def test_london_group() -> None:
    assert airports.resolve("LON") == ["LHR", "LGW", "STN", "LTN", "SEN", "LCY"]


def test_uk_group_contains_london_and_regions_without_duplicates() -> None:
    uk = airports.resolve("UK,STN")
    assert uk[:6] == airports.resolve("LON")
    assert {"BHX", "MAN", "BRS", "EDI"} <= set(uk)
    assert len(uk) == len(set(uk))


def test_every_group_member_is_known() -> None:
    for name in airports.groups():
        for code in airports.resolve(name):
            assert airports.get(code).iata == code


def test_lookup_and_timezone() -> None:
    assert airports.get("krk").city == "Krakow"
    assert airports.timezone("STN").key == "Europe/London"


def test_unknown_airport() -> None:
    with pytest.raises(airports.UnknownAirportError):
        airports.resolve("LON,XXX")
