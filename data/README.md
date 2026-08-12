# data/

Local cache for this project. Nothing here talks to the internet at read-time — scripts
populate this once, then everything else reads from it.

## Contents
- `fpl_cache.db` — SQLite cache, the main thing to read/write from. Schema in `schema.sql`.
  See `../docs/data-storage.md` for the full table-by-table description.
- `schema.sql` — the DDL used to build `fpl_cache.db`. Re-run against a fresh file if the
  db ever needs rebuilding (tables use `CREATE TABLE IF NOT EXISTS`, so it's safe to re-run).
- `raw/` — untouched downloaded files, kept so we don't have to re-hit APIs/sites during
  development:
  - `raw/fpl_api/` — raw JSON dumps from the official FPL API
  - `raw/football_data_co_uk/` — raw historical odds CSVs
  - `raw/odds_api/` — raw live odds JSON snapshots (The Odds API, going forward only)

## Status
`fpl_cache.db` is initialized (empty tables, schema in place). No data loaded yet — that's the
next step once the collector scripts exist (see `scripts/README.md`).
