from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from escape_engine import update

PKG = b"fake installer bytes"


def release_json(tag: str = "v9.0.0", digest: str | None = None) -> dict[str, Any]:
    digest = digest or "sha256:" + hashlib.sha256(PKG).hexdigest()
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/{update.REPO}/releases/tag/{tag}",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example.test/notes.txt"},
            {
                "name": f"EscapeEngine-{tag.lstrip('v')}.pkg",
                "browser_download_url": "https://example.test/pkg",
                "digest": digest,
            },
        ],
    }


def client(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_versions() -> None:
    assert update.parse_version("v1.2.3") == (1, 2, 3)
    assert update.is_newer("0.2.0", "0.1.0")
    assert update.is_newer("v1.0", "0.9.9")
    assert not update.is_newer("0.1.0", "0.1.0")
    assert not update.is_newer("0.1", "0.1.0")
    with pytest.raises(ValueError):
        update.parse_version("latest")


def test_latest_release_parsing() -> None:
    c = client({update.LATEST_URL: httpx.Response(200, json=release_json())})
    rel = update.latest_release(c)
    assert rel is not None
    assert rel.version == "9.0.0"
    assert rel.pkg_name == "EscapeEngine-9.0.0.pkg"
    assert rel.sha256 == hashlib.sha256(PKG).hexdigest()


def test_no_releases_yet() -> None:
    assert update.latest_release(client({})) is None


def test_check_if_due_is_throttled(tmp_path: Path) -> None:
    state = tmp_path / "update.json"
    c = client({update.LATEST_URL: httpx.Response(200, json=release_json())})
    now = datetime(2026, 9, 29, tzinfo=UTC)
    first = update.check_if_due(now=now, path=state, client=c)
    assert first is not None and first.version == "9.0.0"
    assert update.check_if_due(now=now + timedelta(hours=1), path=state, client=c) is None
    assert update.check_if_due(now=now + timedelta(days=1, minutes=1), path=state, client=c)


def test_check_if_due_ignores_old_releases_and_offline(tmp_path: Path) -> None:
    old = client({update.LATEST_URL: httpx.Response(200, json=release_json("v0.0.1"))})
    assert update.check_if_due(path=tmp_path / "a.json", client=old) is None

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    down = httpx.Client(transport=httpx.MockTransport(offline))
    assert update.check_if_due(path=tmp_path / "b.json", client=down) is None


def test_download_verifies_checksum(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update, "user_cache_dir", lambda _name: str(tmp_path))
    c = client({"https://example.test/pkg": httpx.Response(200, content=PKG)})
    good = update.parse_release(release_json())
    path = update.download(good, c)
    assert path.read_bytes() == PKG

    bad = update.parse_release(release_json(digest="sha256:" + "0" * 64))
    with pytest.raises(update.UpdateError, match="checksum"):
        update.download(bad, c)
    assert not (tmp_path / "updates" / "EscapeEngine-9.0.0.pkg").exists()


def test_release_without_installer() -> None:
    rel = update.parse_release({"tag_name": "v9.0.0", "assets": []})
    with pytest.raises(update.UpdateError, match="no Mac installer"):
        update.download(rel, client({}))


def test_dev_checkout_is_not_installed_copy() -> None:
    assert update.installed_via_pkg() is False
