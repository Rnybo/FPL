# Historical Player Data — Approach: Build Our Own, Inspired by vaastav

## Decision
We are **not** taking a runtime dependency on the vaastav/Fantasy-Premier-League GitHub repo.
We'll use it purely as a reference for *how* to structure the scrape and the data, then build
our own equivalent collector directly against the official FPL API as part of our webapp. This
avoids depending on someone else's repo update schedule/uptime for our own product.

Reference: https://github.com/vaastav/Fantasy-Premier-League

## What we're taking inspiration from
1. **Data shape**: one row per player per gameweek, columns for minutes, goals, assists, xG, xA,
   bonus, total points, ICT index, price, opponent, was_home, etc. — a clean long-format table
   that's easy to build rolling features on top of.
2. **Source of truth**: it's all pulled from the same official FPL API we already have documented
   in `api-reference.md` — `bootstrap-static` for player/team/gameweek metadata,
   `element-summary/{id}` for a player's match-by-match history, `event/{id}/live` for a
   gameweek's live stats. There's no secret data source — we can hit these ourselves.
3. **Per-season snapshotting**: keep one file/table per season, so historical seasons stay frozen
   and only the current season updates during the year.
4. **Known trap to avoid** (learned from their repo notes): the FPL API's own `ep_this` field
   (their "expected points" estimate) can get updated post-match and isn't safe to use as a
   training feature or label — it may leak information not available before the deadline.
   Our collector should store actual results only (`total_points`, minutes, goals, assists,
   xG, xA) and never store/rely on FPL's own xP field.

## Our own collector — plan
When we start building (see `scripts/` — currently empty):
- Poll `element-summary/{player_id}/` for every player at the end of each gameweek, store the
  `history` rows into our own per-season table (mirrors the shape above)
- Poll `bootstrap-static/` once per gameweek for team/player metadata and price changes
- Backfill past seasons once, using the same endpoints where FPL still exposes `history_past`
  and `history.csv`-equivalent data per player, OR (if FPL doesn't expose old seasons this way)
  do a one-time reference pull from vaastav's raw CSVs *only* to bootstrap our own historical
  table — after that one-time import we're self-contained and not dependent on the repo staying
  up.

## Storage
Land this in our own database/data files under `data/` (see `data/README.md`), not as a live
fetch-on-demand from GitHub — the webapp should work even if that repo disappears.
