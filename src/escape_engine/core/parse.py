"""Parsing of human-friendly slider values used by the CLI and config."""

from __future__ import annotations

import re
from datetime import time, timedelta

_DURATION = re.compile(r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?$")
_CLOCK = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})(?P<next>\+1)?$")


def parse_duration(text: str) -> timedelta:
    """``"6h"``, ``"90m"``, ``"5h30m"`` -> timedelta."""
    m = _DURATION.match(text.strip().lower())
    if not m or not (m["h"] or m["m"]):
        raise ValueError(f"invalid duration {text!r} (try 6h, 90m or 5h30m)")
    return timedelta(hours=int(m["h"] or 0), minutes=int(m["m"] or 0))


def parse_clock(text: str) -> time:
    """``"05:00"`` -> time."""
    m = _CLOCK.match(text.strip())
    if not m or m["next"]:
        raise ValueError(f"invalid time {text!r} (try 05:00)")
    return time(int(m["h"]), int(m["m"]))


def parse_return_by(text: str) -> timedelta:
    """Latest landing as an offset from midnight of the trip day.

    Accepts ``"23:59"``, ``"02:30+1"`` (next day) or ``"26:30"``.
    """
    m = _CLOCK.match(text.strip())
    if not m:
        raise ValueError(f"invalid return time {text!r} (try 23:59 or 02:30+1)")
    hours, minutes = int(m["h"]), int(m["m"])
    if minutes > 59 or (m["next"] and hours > 23):
        raise ValueError(f"invalid return time {text!r}")
    return timedelta(days=1 if m["next"] else 0, hours=hours, minutes=minutes)
