"""API keys: the environment variable wins, otherwise a private per-user credentials file.

The file lives in the app's config folder with owner-only permissions (0600), like
``~/.aws/credentials``. Keys are never written to the repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir


def credentials_path() -> Path:
    return Path(user_config_dir("escape-engine")) / "credentials.json"


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def get(name: str, path: Path | None = None) -> str:
    """The key from ``$name``, else from the credentials file, else ``""``."""
    return os.environ.get(name) or _read(path or credentials_path()).get(name, "")


def put(name: str, value: str, path: Path | None = None) -> None:
    """Save (or with an empty value, remove) a key in the owner-only credentials file."""
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(path)
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def source(name: str, path: Path | None = None) -> str:
    """Where the key comes from: ``"environment"``, ``"saved"`` or ``""`` (missing)."""
    if os.environ.get(name):
        return "environment"
    return "saved" if _read(path or credentials_path()).get(name) else ""
