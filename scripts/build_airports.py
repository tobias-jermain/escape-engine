"""Rebuild src/escape_engine/data/airports.csv from the mwgg/Airports dataset (MIT).

Usage: uv run python scripts/build_airports.py [path/to/airports.json]
Without a path, the dataset is downloaded from GitHub.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SOURCE_URL = "https://raw.githubusercontent.com/mwgg/Airports/master/airports.json"
OUT = Path(__file__).resolve().parents[1] / "src" / "escape_engine" / "data" / "airports.csv"
FIELDS = ["iata", "icao", "name", "city", "country", "lat", "lon", "tz"]


def load(argv: list[str]) -> dict[str, dict[str, object]]:
    if len(argv) > 1:
        return json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    with urllib.request.urlopen(SOURCE_URL) as resp:
        return json.loads(resp.read())


def valid_tz(name: object) -> bool:
    if not isinstance(name, str) or not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def main(argv: list[str]) -> None:
    rows = {}
    for entry in load(argv).values():
        iata = str(entry.get("iata") or "").strip().upper()
        if len(iata) != 3 or not iata.isalpha() or not valid_tz(entry.get("tz")):
            continue
        rows.setdefault(iata, entry)  # first wins on duplicate IATA codes
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        for iata in sorted(rows):
            e = rows[iata]
            writer.writerow(
                [
                    iata,
                    e.get("icao", ""),
                    e.get("name", ""),
                    e.get("city", ""),
                    e.get("country", ""),
                    round(float(e["lat"]), 5),  # type: ignore[arg-type]
                    round(float(e["lon"]), 5),  # type: ignore[arg-type]
                    e["tz"],
                ]
            )
    print(f"wrote {len(rows)} airports to {OUT}")


if __name__ == "__main__":
    main(sys.argv)
