"""Self-update from this project's GitHub Releases (public, no token needed).

Flow: ask GitHub for the latest release, compare versions, download the ``.pkg``,
check its SHA-256 against the digest GitHub publishes, then open it in macOS Installer.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from platformdirs import user_cache_dir, user_config_dir

from escape_engine import __version__

REPO = "tobias-jermain/escape-engine"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = timedelta(days=1)
INSTALL_ROOT = "/usr/local/lib/escape-engine"


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    """The release page, for humans."""
    pkg_name: str | None
    pkg_url: str | None
    sha256: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """``"v1.2.3"`` -> ``(1, 2, 3)``. Anything after the numbers (e.g. ``-beta``) is ignored."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)", text.strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def parse_release(data: dict[str, Any]) -> Release:
    tag = str(data.get("tag_name", ""))
    parse_version(tag)  # validate
    pkg = next((a for a in data.get("assets", []) if str(a.get("name", "")).endswith(".pkg")), None)
    digest = str(pkg.get("digest") or "") if pkg else ""
    return Release(
        version=tag.lstrip("v"),
        url=str(data.get("html_url", "")),
        pkg_name=str(pkg["name"]) if pkg else None,
        pkg_url=str(pkg["browser_download_url"]) if pkg else None,
        sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
    )


def latest_release(client: httpx.Client | None = None) -> Release | None:
    """The newest published release, or ``None`` if there are none yet."""
    own = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True)
    try:
        resp = client.get(LATEST_URL, headers={"Accept": "application/vnd.github+json"})
    except httpx.HTTPError:
        raise UpdateError("could not reach GitHub to check for updates") from None
    finally:
        if own:
            client.close()
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise UpdateError(f"GitHub returned HTTP {resp.status_code}")
    return parse_release(resp.json())


# --- Throttled background check ----------------------------------------------------------


def _state_path() -> Path:
    return Path(user_config_dir("escape-engine")) / "update.json"


def check_if_due(
    *, now: datetime | None = None, path: Path | None = None, client: httpx.Client | None = None
) -> Release | None:
    """At most once a day: return the latest release if it is newer than this version.

    Never raises: an offline Mac just skips the check.
    """
    now = now or datetime.now(UTC)
    path = path or _state_path()
    try:
        state = json.loads(path.read_text("utf-8"))
        last = datetime.fromisoformat(state["checked_at"])
        if now - last < CHECK_EVERY:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        release = latest_release(client)
    except (UpdateError, ValueError):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": now.isoformat()}), "utf-8")
    return release if release and is_newer(release.version) else None


# --- Installing -------------------------------------------------------------------------


def installed_via_pkg() -> bool:
    """True when running the app installed by the Mac installer (not a dev checkout)."""
    return bool(getattr(sys, "frozen", False)) and sys.executable.startswith(INSTALL_ROOT)


def download(release: Release, client: httpx.Client | None = None) -> Path:
    """Download the release's installer and verify its SHA-256. Returns the file path."""
    if not release.pkg_url or not release.pkg_name:
        raise UpdateError(f"release {release.version} has no Mac installer attached")
    dest_dir = Path(user_cache_dir("escape-engine")) / "updates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(release.pkg_name).name
    own = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    digest = hashlib.sha256()
    try:
        with client.stream("GET", release.pkg_url) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"download failed: HTTP {resp.status_code}")
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    digest.update(chunk)
                    fh.write(chunk)
    except httpx.HTTPError:
        raise UpdateError("download failed: network error") from None
    finally:
        if own:
            client.close()
    if release.sha256 and digest.hexdigest() != release.sha256:
        dest.unlink(missing_ok=True)
        raise UpdateError("downloaded installer failed its checksum; nothing was installed")
    return dest


def open_installer(pkg: Path) -> None:
    """Hand the installer to macOS Installer; the user confirms and enters their password."""
    if sys.platform != "darwin":
        raise UpdateError("installing updates is only supported on macOS")
    subprocess.run(["/usr/bin/open", str(pkg)], check=True)  # noqa: S603 - fixed binary
