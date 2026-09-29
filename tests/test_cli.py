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
