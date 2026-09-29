"""Currency conversion and price-band classification."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from escape_engine.core.models import Money, TripRules, Verdict

_PENNY = Decimal("0.01")


class MissingRateError(LookupError):
    pass


def convert(money: Money, target: str, rates: Mapping[str, Decimal]) -> Money:
    """Convert ``money`` into ``target``.

    ``rates[code]`` is the value of one unit of ``code`` expressed in ``target``
    (e.g. with target GBP, ``rates["EUR"] == Decimal("0.85")``).
    """
    if money.currency == target:
        return money
    try:
        rate = rates[money.currency]
    except KeyError:
        raise MissingRateError(f"no {money.currency}->{target} rate") from None
    amount = (money.amount * rate).quantize(_PENNY, rounding=ROUND_HALF_UP)
    return Money(amount=amount, currency=target)


def classify(price: Money, rules: TripRules) -> Verdict:
    """Place a per-person return price into the main list, "just over", or out."""
    if price.currency != rules.currency:
        raise ValueError(f"price in {price.currency}, rules in {rules.currency}")
    if price.amount <= rules.max_price:
        return Verdict.OK
    if price.amount <= rules.max_price * (1 + rules.stretch):
        return Verdict.JUST_OVER
    return Verdict.REJECTED
