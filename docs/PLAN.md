# Escape Engine — Plan (v1)

The engine finds **extreme day trips**: fly out early, fly back late, same day,
for around **£75 return per person**. It is a library with a CLI (`escape`) on
top. An HTTP API comes later. The app, affiliate links and UI are out of scope.

---

## 1. Decisions so far

| # | Topic | Decision |
|---|---|---|
| 1 | Earliest departure | Flag. Default `05:00` (catches the 06:00 low-cost waves). |
| 2 | Latest return | Flag. Default same day `23:59`; hard ceiling `02:30` next day. |
| 3 | Min time at destination | Flag. Default **6h end to end** (landing to return departure). |
| 4 | Buffers | Applied to compute "usable hours", used for **scoring, not rejection**. A tight trip is still shown, just flagged. |
| 5 | Time zones | Rules use **home-local time**, results show both local times. Everything is timezone-aware so non-UK homes need no refactor. |
| 6 | Overnight trips | `--overnight` flag, off by default. |
| 7 | Price | Return fare, minimum add-ons (free under-seat bag, no seat). Per person. |
| 8 | Airport transfers | Shown separately, never counted in the price. |
| 9 | Currency | Convert to the home currency (GBP) at a live rate, with a note on the conversion. |
| 10 | Price cap | `--max` flag, default `75`. |
| 11 | Passengers | `--pax` flag, default `1`. Price shown per person. |
| 12 | Home airports | All London airports + other UK airports. Data-driven, so any airport or country can be added later. |
| 13 | Open-jaw | Allowed: out of one home-group airport, back into another. |
| 14 | Connections | Direct only. `--allow-connections` is a last-resort flag. |
| 15 | Search modes | v1: **(c) date range, anywhere**. Then (a) fixed date and destination, then (b) fixed date, anywhere. (d) watch/alerts last. |
| 16 | Region | Europe. Flag EU entry rules (EES live; ETIAS pending). |
| 17 | Data | Pluggable providers, **several running at once**, legitimate sources only, user supplies their own API keys. |
| 18 | Use | Personal. The public will reach the *app*, never the engine directly. |
| 19 | Budget | Free tiers only for now. |
| 20 | Freshness | Any fare shown must be **≤ 3h old**. |
| 21 | Price history | No (a short-lived cache is not history). |
| 22–24 | Activities / fun score / visited list | Later versions. |
| 23 | Ranking | price → closest date → usable hours → other. Configurable with `--sort`. |
| 25–29 | Tech | Python, core + CLI + later API, table and `--json` output, macOS + Linux now and Windows later, config file. |
| 30 | v1 done | `escape search` returns real, valid, bookable day trips under £75. |
| 31 | Booking | Never. Return deep links to the airline's own site; the app adds affiliate links later. |
| 32 | Testing | Live, legal provider calls for integration tests. Pure logic is unit tested offline. |
| 33 | Name | CLI command is `escape`. Package is `escape_engine` until renamed. |

---

## 2. Flight data — the hard problem

**Constraint:** the fares have to be real and obtained legally. Unofficial airline
endpoints (e.g. scraping ryanair.com's internal APIs) are **excluded**.

### Candidate providers

| Provider | Role | Live? | Free tier | Notes |
|---|---|---|---|---|
| **SerpApi – Google Flights** | Primary *verifier* | Yes | ~100 searches/month | Covers low-cost carriers through Google Flights. Supports multiple departure airports in one call (`STN,LTN,LGW,…`) and one-way (`type=2`). User supplies the key. |
| **SerpApi – Google Travel Explore** | Discovery ("anywhere") | Yes | Same quota | Finds cheap destinations from an origin; the candidates are then verified. |
| **Travelpayouts (Aviasales Data API)** | Free *discovery* | No — cached, up to ~48h old | Free, generous rate limit | Only used to **choose which routes to check**. Its prices are never shown as bookable. |
| **Duffel** | Possible second verifier | Yes | Free to search, charges per order | Ryanair coverage and personal-account live access **to verify** before building. |
| SearchApi.io / others with the same Google Flights shape | Backup verifier | Yes | Small free tiers | Easy to add once the provider interface exists. |
| ~~Amadeus Self-Service~~ | — | — | — | **Shut down 17 July 2026.** |
| ~~Kiwi Tequila~~ | — | — | — | Closed to new sign-ups. |

### Strategy: discover, then verify

```
            ┌──────────── discovery (cheap/free, may be stale) ─────────────┐
 query ───► │ Travelpayouts calendar · SerpApi Travel Explore · (cache)     │
            └───────────────┬───────────────────────────────────────────────┘
                            ▼  candidate (dest, date) pairs, ranked by likely price
            ┌──────────── verification (live, ≤ 3h, quota-budgeted) ────────┐
            │ SerpApi Google Flights ×2 one-way calls per candidate         │
            │ (+ any other live providers, run concurrently)                │
            └───────────────┬───────────────────────────────────────────────┘
                            ▼  merge + dedupe (carrier + flight no. + date)
                     day-trip rules → price filter → rank → output
```

- **Two one-way searches** (out and back) instead of one return search. This
  supports open-jaw, mixed carriers, and costs 2 calls per candidate.
- **Quota budget:** each run takes `--budget N` live calls (default is small) and
  spends them on the best-ranked candidates first. Remaining quota is shown.
- **Multiple providers at once:** providers run concurrently (`asyncio`). Results
  are merged and deduped; when two sources disagree on price, the lower *live*
  price is kept and both sources are recorded.
- **Freshness:** every fare has a `fetched_at` time. Nothing older than 3h is shown
  as bookable. The cache TTL is ≤ 3h.

> ⚠️ **Quota reality:** 100 free searches ≈ 50 destination-date pairs per month.
> Mode (c), "a month, anywhere, from all of London", only fits the free tier because
> discovery narrows it down first. If that turns out too tight, a paid SerpApi tier
> or a second free verifier is the fix. No redesign needed.

---

## 3. Architecture

```
escape_engine/
  core/
    models.py        # Airport, Flight, Fare, DayTrip, SearchQuery, Money (pydantic)
    rules.py         # day-trip validity + usable-hours maths (pure, tz-aware)
    ranking.py       # price → closest date → usable hours → other
    pricing.py       # FX conversion, per-pax normalisation
    entry.py         # EU/Schengen/EES/ETIAS flags (data-driven, with "as of" dates)
  data/
    airports.csv     # OurAirports (public domain): IATA, tz, country, lat/lon
    groups.toml      # airport groups, e.g. LON = LHR,LGW,STN,LTN,SEN,LCY
    entry_rules.toml # per-country entry notes
  providers/
    base.py          # Provider protocol: discover() / verify(), capabilities, quota
    registry.py      # enable/disable in config; third-party plugins via entry points
    serpapi.py
    travelpayouts.py
  search/
    planner.py       # turns a query into candidates, applies the live-call budget
    engine.py        # orchestrates discover → verify → rules → rank
  cache.py           # SQLite, TTL ≤ 3h
  config.py          # ~/.config/escape/config.toml + env vars for keys
  cli/               # Typer app: `escape search`, `escape providers`, `escape config`
  api/               # (later) FastAPI, same models = same JSON contract
```

**Tech:** Python 3.11+, `uv`, `httpx` (async), `pydantic` v2, `typer` + `rich`,
`zoneinfo`, SQLite. Runs on macOS/Linux; nothing in the stack blocks Windows.

**Worldwide-ready from day one:** home airports, home currency, home timezone and
region are all config and data, not code. "UK" is just the default profile.

---

## 4. CLI sketch (mode c)

```bash
escape search --from LON --between 2026-11-01 2026-11-30 \
  --max 75 --pax 1 --depart-after 05:00 --return-by 23:59 --min-ground 6h

escape search --from LON,BHX --between 2026-11-01 2026-11-30 --json
escape providers           # list providers, key status, remaining quota
escape config init         # write default config
```

`--json` output is versioned (`"schema": "escape.v1"`). It is the future API contract.

---

## 5. Milestones

| M | Deliverable |
|---|---|
| **M0** | Repo skeleton, `uv` project, lint/format/tests CI, `escape --version`. |
| **M1** | Core models, airport data, timezone-aware day-trip rules and usable hours, full offline unit tests. |
| **M2** | Provider interface + SerpApi Google Flights verifier + cache (≤3h) + FX. |
| **M3** | Discovery (Travelpayouts + SerpApi Explore) + planner/budget → **mode (c) end to end**. Ranking, table + JSON. **= v1.** |
| **M4** | EU entry flags, open-jaw polish, `--allow-connections`, `--overnight`. |
| **M5** | Modes (a) and (b). Second live provider (Duffel or equivalent) if it checks out. |
| **M6** | Mode (d) watch/alerts. |
| **M7** | HTTP API wrapper. |

---

## 6. Resolved follow-ups

| Topic | Decision |
|---|---|
| Discovery source | Travelpayouts is used **only** to choose which routes to check live. Its prices are never shown as bookable. |
| Near-misses | Show a separate **"just over"** section, up to `--stretch` (default +20%) above `--max`. |
| Live-call budget | `--budget` default **10** calls per run (about 5 destination-dates). |
| Bundled add-ons | Fares that include extras (e.g. a cabin bag) are **kept but carry a warning**. |
