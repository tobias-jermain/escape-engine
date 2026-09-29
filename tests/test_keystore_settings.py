from __future__ import annotations

import stat
from decimal import Decimal
from pathlib import Path

import pytest

from escape_engine import keystore, settings


def test_key_saved_privately_and_env_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "cfg" / "credentials.json"
    assert keystore.get("K", creds) == ""
    assert keystore.source("K", creds) == ""

    keystore.put("K", "saved-value", creds)
    assert keystore.get("K", creds) == "saved-value"
    assert keystore.source("K", creds) == "saved"
    assert stat.S_IMODE(creds.stat().st_mode) == 0o600

    monkeypatch.setenv("K", "env-value")
    assert keystore.get("K", creds) == "env-value"
    assert keystore.source("K", creds) == "environment"

    monkeypatch.delenv("K")
    keystore.put("K", "", creds)
    assert keystore.get("K", creds) == ""


def test_corrupt_credentials_file_is_ignored(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.json"
    creds.write_text("not json")
    assert keystore.get("K", creds) == ""


def test_settings_round_trip_and_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert settings.load(path) == settings.Settings()
    s = settings.Settings(home="uk", max_price="60", return_by="02:30+1", setup_done=True)
    settings.save(s, path)
    loaded = settings.load(path)
    assert loaded.home == "UK"
    rules = loaded.rules()
    assert rules.max_price == Decimal("60")
    assert rules.return_by.total_seconds() == 26.5 * 3600
    assert loaded.rules(max_price=Decimal("40")).max_price == Decimal("40")


def test_bad_settings_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"home": "XXX"}')
    assert settings.load(path) == settings.Settings()
