from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from escape_engine.cache import Cache
from escape_engine.core.models import Flight
from escape_engine.fx import FxError, parse_ecb, rates_to

from .conftest import NOW

ECB = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
 <Cube><Cube time='2026-09-28'>
  <Cube currency='GBP' rate='0.85'/><Cube currency='PLN' rate='4.25'/>
 </Cube></Cube></gesmes:Envelope>"""


def test_cache_round_trip_and_expiry(tmp_path: Path, out_leg: Flight) -> None:
    cache = Cache(tmp_path / "c.sqlite3", ttl=timedelta(hours=10))
    assert cache.ttl == timedelta(hours=3)  # never above the freshness limit
    cache.put("k", [out_leg], now=NOW)
    assert cache.get("k", now=NOW + timedelta(hours=2)) == [out_leg]
    assert cache.get("k", now=NOW + timedelta(hours=3, minutes=1)) is None
    assert cache.get("missing", now=NOW) is None
    cache.close()


def test_ecb_rates_rebased_to_gbp() -> None:
    gbp = rates_to("GBP", parse_ecb(ECB))
    assert gbp["GBP"] == 1
    assert gbp["EUR"] == Decimal("0.85")
    assert gbp["PLN"] == Decimal("0.2")


def test_fx_errors() -> None:
    with pytest.raises(FxError):
        rates_to("XYZ", parse_ecb(ECB))
    with pytest.raises(FxError):
        parse_ecb("<root/>")
