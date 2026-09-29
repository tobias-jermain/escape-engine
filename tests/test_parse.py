from __future__ import annotations

from datetime import time, timedelta

import pytest

from escape_engine.core.parse import parse_clock, parse_duration, parse_return_by


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6h", timedelta(hours=6)),
        ("90m", timedelta(minutes=90)),
        ("5h30m", timedelta(hours=5, minutes=30)),
    ],
)
def test_parse_duration(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize("bad", ["", "6", "h", "6x", "-1h"])
def test_parse_duration_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_parse_clock() -> None:
    assert parse_clock("05:00") == time(5, 0)
    with pytest.raises(ValueError):
        parse_clock("02:30+1")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("23:59", timedelta(hours=23, minutes=59)),
        ("02:30+1", timedelta(hours=26, minutes=30)),
        ("26:30", timedelta(hours=26, minutes=30)),
    ],
)
def test_parse_return_by(text: str, expected: timedelta) -> None:
    assert parse_return_by(text) == expected


@pytest.mark.parametrize("bad", ["24:00+1", "12:60", "noon"])
def test_parse_return_by_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_return_by(bad)
