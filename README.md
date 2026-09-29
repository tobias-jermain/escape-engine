# Escape Engine

*Pending Name Change*

## Find cheap extreme day trip flight

This repo serves as the core engine for finding quick, cheap and perfect extreme day trips with the flight as core (extreme day trip) and other things as secondary. The engine would then be housed in an app for Multiplatform. it's the core, not the exterior. it actually finds flights.


## Status

Early development. See [`docs/PLAN.md`](docs/PLAN.md) for the design and milestones.

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
export SERPAPI_API_KEY="..."     # e.g. in ~/.zshrc
uv run escape check --from LON --to KRK --date 2026-11-14
uv run escape check --from LON --to KRK --date 2026-11-14 --return-by 02:30+1 --json
```

Run `uv run escape check --help` for every slider (times, minimum ground time, price cap,
passengers, overnight, connections, live-call budget).

## Data

Airport data (`src/escape_engine/data/airports.csv`) is generated from
[mwgg/Airports](https://github.com/mwgg/Airports) (MIT licence) with
`uv run python scripts/build_airports.py`.
