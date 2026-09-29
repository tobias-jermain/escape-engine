# Escape Engine

*Pending Name Change*

## Find cheap extreme day trip flight

This repo serves as the core engine for finding quick, cheap and perfect extreme day trips with the flight as core (extreme day trip) and other things as secondary. The engine would then be housed in an app for Multiplatform. it's the core, not the exterior. it actually finds flights.


## Status

Early development. See [`docs/PLAN.md`](docs/PLAN.md) for the design and milestones.

## Install on your Mac

1. Download **EscapeEngine-x.y.z.pkg** from the repo's **Releases** page (or from the
   latest "macOS package" run under **Actions** > Artifacts).
2. Double-click it and follow the installer. One installer works on Apple Silicon and Intel Macs.
3. **Escape Engine** opens with a large-text guide and a short **setup**: paste your
   [SerpApi](https://serpapi.com/) key (checked and saved privately on your Mac), then choose home
   airports, budget and times. Change them any time under **Settings and API key**.
4. Later, open it from Applications or Launchpad, or type `escape` in Terminal.

**Updates:** the app checks for a new version once a day (you can turn this off in setup).
Choose **Check for updates** in the menu to download it; the macOS installer then opens.

The installer isn't signed with an Apple Developer ID yet. If macOS says it "can't be opened",
go to **System Settings > Privacy & Security** and click **Open Anyway**. The first time the
app runs, macOS also asks to let it control Terminal: click **OK**.

## Publishing a release

No local copy of the repo is needed:

1. Make sure `version` in `pyproject.toml` (and `src/escape_engine/__init__.py`) is the new
   version and that change is merged into `main`.
2. On GitHub: **Actions > macOS package > Run workflow**, branch `main`, tick
   **Publish a release**, then **Run workflow**.
3. A few minutes later **Releases** has `vX.Y.Z` with the installer, and the app's
   **Check for updates** offers it.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+ (macOS or Linux).

```bash
uv sync
uv run escape --version
uv run escape airports UK        # expand an airport group
uv run escape providers          # which flight data sources are ready
uv run pytest                    # offline tests
uv run pytest -m live            # live provider tests (spend API quota)
uv run ruff check . && uv run mypy
```

## Finding day trips

Live prices come from [SerpApi](https://serpapi.com/)'s Google Flights API using your own key:

```bash
uv run escape setup              # save your key and defaults (or: export SERPAPI_API_KEY=...)
uv run escape explore                       # cheapest day trips ANYWHERE, next 3 weeks
uv run escape explore --from STN --max 50 --days 14
uv run escape check --to KRK --date 2026-11-14   # one destination, one date
```

`explore` spends 1 search per calendar month to find cheap destinations, then 2 per destination
it verifies (default budget 10: about 4 destinations).

Run `uv run escape check --help` for every slider (times, minimum ground time, price cap,
passengers, overnight, connections, live-call budget).

## Data

Airport data (`src/escape_engine/data/airports.csv`) is generated from
[mwgg/Airports](https://github.com/mwgg/Airports) (MIT licence) with
`uv run python scripts/build_airports.py`.
