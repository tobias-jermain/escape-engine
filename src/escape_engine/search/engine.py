"""Search orchestration: fetch legs from providers, pair them, apply the rules, rank."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from escape_engine.cache import Cache
from escape_engine.core import airports
from escape_engine.core.models import DayTrip, Flight, TripRules, Verdict
from escape_engine.core.ranking import DEFAULT_ORDER, SortKey, rank
from escape_engine.core.rules import evaluate
from escape_engine.providers.base import (
    MAX_AIRPORTS_PER_QUERY,
    OneWayQuery,
    Provider,
    ProviderError,
)

RatesFn = Callable[[str], Awaitable[dict[str, Decimal]]]


class BudgetError(RuntimeError):
    pass


@dataclass
class Budget:
    """Live provider calls this run may spend. Cache hits are free."""

    limit: int
    used: int = 0

    def take(self, n: int = 1) -> None:
        if self.used + n > self.limit:
            raise BudgetError(
                f"needs {self.used + n} live calls, budget is {self.limit} (raise --budget)"
            )
        self.used += n


@dataclass
class SearchResult:
    trips: list[DayTrip]
    just_over: list[DayTrip]
    rejected: list[DayTrip]
    calls_used: int
    errors: list[str] = field(default_factory=list)

    def top_reasons(self, n: int = 5) -> list[tuple[str, int]]:
        # Group by the reason's leading words so "only 5h10m on the ground" style counts together.
        counts = Counter(_reason_kind(r) for t in self.rejected for r in t.reasons)
        return counts.most_common(n)


_REASON_LABELS = (
    ("on the ground", "too little time there"),
    ("before outbound lands", "return leaves before arrival"),
    ("arrives before it departs", "bad flight times"),
    ("before", "departs too early"),
    ("lands home", "lands home too late"),
    ("old", "stale fare"),
    ("stop", "not direct"),
    ("is over", "over budget"),
    ("home airport", "not a home airport"),
    ("return departs", "different return airport"),
    ("returns to", "different home airport"),
)


def _reason_kind(reason: str) -> str:
    for marker, label in _REASON_LABELS:
        if marker in reason:
            return label
    return reason


class Engine:
    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        cache: Cache | None = None,
        rates: RatesFn | None = None,
        use_cache: bool = True,
    ) -> None:
        self.providers = [p for p in providers if p.configured() and p.live]
        self.cache = cache
        self.use_cache = use_cache
        self._rates = rates

    async def _fetch(self, query: OneWayQuery, budget: Budget, errors: list[str]) -> list[Flight]:
        async def one(provider: Provider) -> Sequence[Flight]:
            key = f"{provider.name}|{query.cache_key()}"
            if self.cache and self.use_cache:
                hit = self.cache.get(key)
                if hit is not None:
                    return hit
            budget.take()
            try:
                flights = await provider.one_way(query)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                return []
            if self.cache:
                self.cache.put(key, flights)
            return flights

        results = await asyncio.gather(*(one(p) for p in self.providers))
        return _merge(f for batch in results for f in batch)

    def _queries(
        self, origins: Sequence[str], destination: str, day: date, rules: TripRules, pax: int
    ) -> tuple[list[OneWayQuery], list[OneWayQuery]]:
        return_days = [day, day + timedelta(days=1)] if rules.overnight else [day]
        home = tuple(origins)
        chunks = [
            home[i : i + MAX_AIRPORTS_PER_QUERY]
            for i in range(0, len(home), MAX_AIRPORTS_PER_QUERY)
        ]
        dest = (destination,)
        nonstop = not rules.allow_connections
        out_qs = [OneWayQuery(c, dest, day, pax, rules.currency, nonstop) for c in chunks]
        back_qs = [
            OneWayQuery(dest, c, d, pax, rules.currency, nonstop)
            for d in return_days
            for c in chunks
        ]
        return out_qs, back_qs

    def calls_needed(self, origins: Sequence[str], rules: TripRules) -> int:
        """Most live calls one ``check`` can spend (cache hits make it cheaper)."""
        out_qs, back_qs = self._queries(origins, "XXX", date(2000, 1, 1), rules, 1)
        return len(self.providers) * (len(out_qs) + len(back_qs))

    async def check(
        self,
        *,
        origins: Sequence[str],
        destination: str,
        day: date,
        rules: TripRules,
        pax: int = 1,
        budget: int = 10,
        order: Sequence[SortKey] = DEFAULT_ORDER,
        now: datetime | None = None,
    ) -> SearchResult:
        """Mode (a): every valid day trip from ``origins`` to ``destination`` on ``day``."""
        if not self.providers:
            raise ProviderError("no live provider is configured (set SERPAPI_API_KEY)")
        now = now or datetime.now(UTC)
        spend = Budget(budget)
        out_qs, back_qs = self._queries(origins, destination, day, rules, pax)
        needed = self.calls_needed(origins, rules)
        if needed > budget:
            raise BudgetError(
                f"needs up to {needed} live calls, budget is {budget} (raise --budget)"
            )
        home = tuple(origins)

        errors: list[str] = []
        batches = await asyncio.gather(
            *(self._fetch(q, spend, errors) for q in [*out_qs, *back_qs])
        )
        outbound = _merge(f for b in batches[: len(out_qs)] for f in b)
        inbound = _merge(f for b in batches[len(out_qs) :] for f in b)

        rates: dict[str, Decimal] = {}
        foreign = {f.price.currency for f in (*outbound, *inbound)} - {rules.currency}
        if foreign:
            if self._rates is None:
                raise ProviderError(f"fares in {', '.join(sorted(foreign))} but no FX source")
            rates = await self._rates(rules.currency)

        home_set = set(home)
        evaluated = [
            evaluate(
                out,
                back,
                rules=rules,
                home_airports=home_set,
                home_tz=airports.timezone(out.origin),
                now=now,
                rates=rates,
            )
            for out in outbound
            for back in inbound
            if back.origin == out.destination
        ]
        today = now.astimezone(airports.timezone(home[0])).date()
        return SearchResult(
            trips=rank([t for t in evaluated if t.verdict is Verdict.OK], today=today, order=order),
            just_over=rank(
                [t for t in evaluated if t.verdict is Verdict.JUST_OVER], today=today, order=order
            ),
            rejected=[t for t in evaluated if t.verdict is Verdict.REJECTED],
            calls_used=spend.used,
            errors=errors,
        )


def _merge(flights: Iterable[Flight]) -> list[Flight]:
    """Dedupe the same flight seen by several providers, keeping the cheapest quote."""
    best: dict[tuple[str, datetime], Flight] = {}
    for f in flights:
        key = (f.carrier + f.flight_number, f.departs_at.astimezone(UTC))
        kept = best.get(key)
        if kept is None or (
            f.price.currency == kept.price.currency and f.price.amount < kept.price.amount
        ):
            best[key] = f
    return list(best.values())
