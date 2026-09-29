from __future__ import annotations

import json

from typer.testing import CliRunner

from escape_engine import __version__
from escape_engine.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_airports_json() -> None:
    result = runner.invoke(app, ["airports", "LON", "--json"])
    assert result.exit_code == 0
    assert [a["iata"] for a in json.loads(result.output)][:2] == ["LHR", "LGW"]


def test_airports_unknown_exits_2() -> None:
    result = runner.invoke(app, ["airports", "XXX"])
    assert result.exit_code == 2


def test_check_without_key_fails_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    result = runner.invoke(app, ["check", "--to", "KRK", "--date", "2026-11-14"])
    assert result.exit_code == 2
    assert "SERPAPI_API_KEY" in result.output


def test_check_rejects_bad_input() -> None:
    for args in (
        ["--to", "KRK", "--date", "14/11/2026"],
        ["--to", "XXX", "--date", "2026-11-14"],
        ["--to", "KRK", "--date", "2026-11-14", "--return-by", "03:00+1"],
    ):
        result = runner.invoke(app, ["check", *args])
        assert result.exit_code == 2, args


def test_providers_lists_serpapi() -> None:
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert "serpapi" in result.output
