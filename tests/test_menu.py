from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import escape_engine.cli as cli
from escape_engine.cli.menu import next_saturday, run_menu
from escape_engine.providers.serpapi import SerpApiFlights
from escape_engine.search.engine import SearchResult

TODAY = date(2026, 9, 29)  # a Tuesday


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it: Iterator[str] = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


def console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=100, force_terminal=False), buf


def test_first_run_shows_guide_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    state = tmp_path / "state.json"
    con, buf = console()
    feed(monkeypatch, ["", "4"])
    run_menu(console=con, state_file=state, today=TODAY)
    out = buf.getvalue()
    assert "Welcome to Escape Engine" in out
    assert "How to add your SerpApi key" in out
    assert state.exists()

    con, buf = console()
    feed(monkeypatch, ["4"])
    run_menu(console=con, state_file=state, today=TODAY)
    assert "Welcome to Escape Engine" not in buf.getvalue()


def test_search_without_key_explains_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    (tmp_path / "state.json").write_text('{"guide_seen": true}')
    con, buf = console()
    feed(monkeypatch, ["1", "4"])
    run_menu(console=con, state_file=tmp_path / "state.json", today=TODAY)
    assert "A SerpApi key is needed first" in buf.getvalue()


def test_find_trip_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text('{"guide_seen": true}')
    monkeypatch.setattr(SerpApiFlights, "configured", lambda self: True)
    calls: list[dict[str, Any]] = []

    def fake_search(**kw: Any) -> SearchResult:
        calls.append(kw)
        return SearchResult(trips=[], just_over=[], rejected=[], calls_used=2)

    monkeypatch.setattr(cli, "run_search", fake_search)
    con, buf = console()
    feed(monkeypatch, ["1", "LON", "Kraków", "", "60", "y", "4"])
    run_menu(console=con, state_file=tmp_path / "state.json", today=TODAY)
    assert len(calls) == 1
    assert calls[0]["destination"] == "KRK"
    assert calls[0]["day"] == date(2026, 10, 3)  # next Saturday
    assert str(calls[0]["rules"].max_price) == "60"
    assert calls[0]["budget"] == 2
    assert "Live calls used: 2" in buf.getvalue()


def test_next_saturday() -> None:
    assert next_saturday(date(2026, 9, 29)) == date(2026, 10, 3)
    assert next_saturday(date(2026, 10, 3)) == date(2026, 10, 10)
