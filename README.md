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
uv run pytest                    # tests
uv run ruff check . && uv run mypy
```

## Data

Airport data (`src/escape_engine/data/airports.csv`) is generated from
[mwgg/Airports](https://github.com/mwgg/Airports) (MIT licence) with
`uv run python scripts/build_airports.py`.
