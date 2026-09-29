"""The provider contract every flight data source implements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from escape_engine.core.models import Flight


class ProviderError(RuntimeError):
    """A provider call failed (network, quota, bad response)."""


class ProviderConfigError(ProviderError):
    """A provider cannot run as configured (e.g. missing API key)."""


@dataclass(frozen=True)
class OneWayQuery:
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    day: date
    pax: int = 1
    currency: str = "GBP"
    nonstop: bool = True

    def cache_key(self) -> str:
        return "|".join(
            [
                ",".join(sorted(self.origins)),
                ",".join(sorted(self.destinations)),
                self.day.isoformat(),
                str(self.pax),
                self.currency,
                "nonstop" if self.nonstop else "any",
            ]
        )


@runtime_checkable
class Provider(Protocol):
    name: str
    live: bool
    """True if results are bookable quotes, False if cached/indicative (discovery only)."""

    def configured(self) -> bool:
        """Whether the provider has what it needs (keys etc.) to make calls."""
        ...

    async def one_way(self, query: OneWayQuery) -> Sequence[Flight]:
        """One-way flights for ``query``. One call counts as one unit of quota."""
        ...
