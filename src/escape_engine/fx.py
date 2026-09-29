"""Exchange rates from the European Central Bank's free daily reference feed."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

import httpx

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class FxError(RuntimeError):
    pass


def parse_ecb(xml_text: str) -> dict[str, Decimal]:
    """ECB XML -> ``{currency: units per 1 EUR}`` (EUR itself included as 1)."""
    rates = {"EUR": Decimal(1)}
    for cube in ET.fromstring(xml_text).iter():  # noqa: S314 - fixed, trusted ECB source
        if cube.get("currency") and cube.get("rate"):
            rates[cube.get("currency", "")] = Decimal(cube.get("rate", ""))
    if len(rates) == 1:
        raise FxError("no rates in ECB feed")
    return rates


def rates_to(target: str, per_eur: dict[str, Decimal]) -> dict[str, Decimal]:
    """Re-base EUR rates so ``result[code]`` is the value of 1 ``code`` in ``target``."""
    if target not in per_eur:
        raise FxError(f"ECB has no rate for {target}")
    return {code: per_eur[target] / rate for code, rate in per_eur.items()}


async def fetch_rates(target: str, client: httpx.AsyncClient | None = None) -> dict[str, Decimal]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        resp = await client.get(ECB_DAILY)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise FxError(f"could not fetch ECB rates: {type(exc).__name__}") from None
    finally:
        if own:
            await client.aclose()
    return rates_to(target, parse_ecb(resp.text))
