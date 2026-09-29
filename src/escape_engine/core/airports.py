"""Airport lookup and airport-group expansion from bundled, data-driven files."""

from __future__ import annotations

import csv
import tomllib
from functools import cache
from importlib import resources
from zoneinfo import ZoneInfo

from escape_engine.core.models import Airport


class UnknownAirportError(LookupError):
    pass


@cache
def _airports() -> dict[str, Airport]:
    text = resources.files("escape_engine.data").joinpath("airports.csv").read_text("utf-8")
    return {row["iata"]: Airport.model_validate(row) for row in csv.DictReader(text.splitlines())}


@cache
def _groups() -> dict[str, tuple[str, ...]]:
    text = resources.files("escape_engine.data").joinpath("groups.toml").read_text("utf-8")
    return {
        name.upper(): tuple(c.upper() for c in codes) for name, codes in tomllib.loads(text).items()
    }


def get(code: str) -> Airport:
    try:
        return _airports()[code.upper()]
    except KeyError:
        raise UnknownAirportError(f"unknown airport {code!r}") from None


def timezone(code: str) -> ZoneInfo:
    return ZoneInfo(get(code).tz)


def groups() -> dict[str, tuple[str, ...]]:
    return dict(_groups())


def resolve(spec: str) -> list[str]:
    """Expand ``"LON,BHX"`` into airport codes, following nested groups, keeping order."""
    out: dict[str, None] = {}

    def expand(code: str, seen: tuple[str, ...]) -> None:
        code = code.strip().upper()
        if not code:
            return
        if code in _groups():
            if code in seen:
                raise ValueError(f"airport group cycle: {' -> '.join((*seen, code))}")
            for member in _groups()[code]:
                expand(member, (*seen, code))
        else:
            out[get(code).iata] = None

    for part in spec.split(","):
        expand(part, ())
    if not out:
        raise ValueError("no airports given")
    return list(out)
