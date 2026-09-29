"""Short-lived SQLite cache for provider results. Never older than the freshness limit."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir

from escape_engine.core.models import Flight

MAX_TTL = timedelta(hours=3)


def default_path() -> Path:
    return Path(user_cache_dir("escape-engine")) / "cache.sqlite3"


class Cache:
    def __init__(self, path: Path | None = None, ttl: timedelta = MAX_TTL) -> None:
        self.ttl = min(ttl, MAX_TTL)
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS results ("
            " key TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )

    def get_payload(self, key: str, *, now: datetime | None = None) -> list[Any] | None:
        """Raw cached JSON for ``key``, or ``None`` if missing or older than the TTL."""
        row = self._db.execute(
            "SELECT fetched_at, payload FROM results WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        now = now or datetime.now(UTC)
        if now - datetime.fromisoformat(row[0]) > self.ttl:
            return None
        data = json.loads(row[1])
        return data if isinstance(data, list) else None

    def put_payload(self, key: str, payload: list[Any], *, now: datetime | None = None) -> None:
        stamp = (now or datetime.now(UTC)).isoformat()
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO results (key, fetched_at, payload) VALUES (?, ?, ?)",
                (key, stamp, json.dumps(payload)),
            )

    def get(self, key: str, *, now: datetime | None = None) -> list[Flight] | None:
        data = self.get_payload(key, now=now)
        return None if data is None else [Flight.model_validate(f) for f in data]

    def put(self, key: str, flights: Sequence[Flight], *, now: datetime | None = None) -> None:
        # Stored at the time of the call; each Flight keeps its own fetched_at for freshness rules.
        self.put_payload(key, [f.model_dump(mode="json") for f in flights], now=now)

    def purge(self, *, now: datetime | None = None) -> None:
        cutoff = ((now or datetime.now(UTC)) - self.ttl).isoformat()
        with self._db:
            self._db.execute("DELETE FROM results WHERE fetched_at < ?", (cutoff,))

    def close(self) -> None:
        self._db.close()
