from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import escape_engine.cli as cli
from escape_engine import keystore, settings
from escape_engine.cli.menu import MenuDeps, next_saturday, run_menu
from escape_engine.providers.base import ProviderError
from escape_engine.search.engine import SearchResult
from escape_engine.update import Release

TODAY = date(2026, 9, 29)  # a Tuesday
NEWER = Release("9.0.0", "https://example.test", "E.pkg", "https://example.test/E.pkg", None)


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Answer prompts in order, including hidden (password) ones."""
    it: Iterator[str] = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: next(it))


def console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=100, force_terminal=False), buf


def deps(tmp_path: Path, **kw: Any) -> MenuDeps:
    base: dict[str, Any] = {
        "settings_file": tmp_path / "settings.json",
        "credentials_file": tmp_path / "credentials.json",
        "check_key": lambda key: {"plan_name": "Free Plan", "plan_searches_left": 247},
        "latest_release": lambda: None,
        "update_if_due": lambda: None,
        "installed_via_pkg": lambda: True,
    }
    base.update(kw)
    return MenuDeps(**base)


def done(d: MenuDeps, **kw: Any) -> None:
    settings.save(settings.Settings(setup_done=True, **kw), d.settings_file)


def test_first_run_guide_then_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = deps(tmp_path)
    con, buf = console()
    # enter, key (hidden), home, price, depart, return, min time, updates, then quit
    feed(monkeypatch, ["", "my-key", "UK", "60", "", "02:30+1", "", "n", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    out = buf.getvalue()
    assert "Welcome to Escape Engine" in out
    assert "Key saved." in out and "247 searches left" in out
    assert "my-key" not in out  # never echoed
    assert keystore.get("SERPAPI_API_KEY", d.credentials_file) == "my-key"
    s = settings.load(d.settings_file)
    assert (s.setup_done, s.home, s.max_price, s.return_by, s.auto_update_check) == (
        True,
        "UK",
        "60",
        "02:30+1",
        False,
    )

    con, buf = console()
    feed(monkeypatch, ["6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "Welcome to Escape Engine" not in buf.getvalue()


def test_setup_rejects_bad_answers_and_bad_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def bad_key(key: str) -> dict[str, Any]:
        raise ProviderError("SerpApi says this key is not valid")

    d = deps(tmp_path, check_key=bad_key)
    con, buf = console()
    feed(
        monkeypatch,
        ["", "wrong", "n", "", "XXX", "LON", "-5", "75", "5am", "05:30", "", "", "", "6"],
    )
    run_menu(console=con, deps=d, today=TODAY)
    out = buf.getvalue()
    assert "not valid" in out
    assert keystore.get("SERPAPI_API_KEY", d.credentials_file) == ""
    assert out.count("Please try again") == 3
    assert settings.load(d.settings_file).depart_after == "05:30"


def test_env_key_is_used_without_asking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "from-env")
    d = deps(tmp_path)
    con, buf = console()
    feed(monkeypatch, ["", "", "", "", "", "", "", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "from the SERPAPI_API_KEY environment variable" in buf.getvalue()


def test_find_trip_uses_saved_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = deps(tmp_path)
    done(d, home="STN", max_price="50", min_ground="7h")
    keystore.put("SERPAPI_API_KEY", "k", d.credentials_file)
    calls: list[dict[str, Any]] = []

    def fake_search(**kw: Any) -> SearchResult:
        calls.append(kw)
        return SearchResult(trips=[], just_over=[], rejected=[], calls_used=2)

    monkeypatch.setattr(cli, "run_search", fake_search)
    con, buf = console()
    feed(monkeypatch, ["2", "", "Kraków", "", "", "y", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert len(calls) == 1
    call = calls[0]
    assert (call["origins"], call["destination"], call["day"]) == (
        ["STN"],
        "KRK",
        date(2026, 10, 3),
    )
    assert str(call["rules"].max_price) == "50"
    assert call["rules"].min_ground.total_seconds() == 7 * 3600
    assert "Live calls used: 2" in buf.getvalue()


def test_find_trip_without_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = deps(tmp_path)
    done(d)
    con, buf = console()
    feed(monkeypatch, ["2", "1", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "An API key is needed first" in buf.getvalue()


def test_update_downloads_and_opens_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[Path] = []
    d = deps(
        tmp_path,
        latest_release=lambda: NEWER,
        download=lambda rel: tmp_path / "E.pkg",
        open_installer=opened.append,
    )
    done(d)
    con, buf = console()
    feed(monkeypatch, ["4", ""])  # menu closes itself after opening the installer
    run_menu(console=con, deps=d, today=TODAY)
    assert opened == [tmp_path / "E.pkg"]
    assert "The installer is open" in buf.getvalue()


def test_update_up_to_date_and_dev_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = deps(tmp_path, latest_release=lambda: None)
    done(d)
    con, buf = console()
    feed(monkeypatch, ["4", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "No releases have been published yet" in buf.getvalue()

    d = deps(tmp_path, latest_release=lambda: NEWER, installed_via_pkg=lambda: False)
    con, buf = console()
    feed(monkeypatch, ["4", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "git pull" in buf.getvalue()


def test_daily_update_notice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = deps(tmp_path, update_if_due=lambda: NEWER)
    done(d)
    con, buf = console()
    feed(monkeypatch, ["6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "Version 9.0.0 is available" in buf.getvalue()

    done(d, auto_update_check=False)
    con, buf = console()
    feed(monkeypatch, ["6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert "is available" not in buf.getvalue()


def test_next_saturday() -> None:
    assert next_saturday(date(2026, 9, 29)) == date(2026, 10, 3)
    assert next_saturday(date(2026, 10, 3)) == date(2026, 10, 10)


def test_find_anywhere_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from escape_engine.search.explore import ExploreResult

    d = deps(tmp_path)
    done(d, home="LON", max_price="75")
    keystore.put("SERPAPI_API_KEY", "k", d.credentials_file)
    calls: list[dict[str, Any]] = []

    def fake_explore(**kw: Any) -> ExploreResult:
        calls.append(kw)
        return ExploreResult(trips=[], just_over=[], rejected=[], calls_used=9, shortlist_size=15)

    monkeypatch.setattr(cli, "run_explore", fake_explore)
    con, buf = console()
    feed(monkeypatch, ["1", "", "50", "400", "14", "y", "6"])
    run_menu(console=con, deps=d, today=TODAY)
    assert len(calls) == 1
    assert calls[0]["origins"][:2] == ["LHR", "LGW"]
    assert str(calls[0]["rules"].max_price) == "50"
    assert (calls[0]["days"], calls[0]["budget"]) == (14, 10)
    out = buf.getvalue()
    assert "choose between 2 and 90 days" in out
    assert "Checked 0 of 15 cheap destinations" in out
