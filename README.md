# FPL — Expected Points & Odds Project

## Goal
Fetch FPL player data via the public API and combine it with historical + in-form performance
to estimate **expected points (xP)** per player per gameweek, then optimize squad/transfer
decisions from that. Weights/parameters are **learned from historical data**, not assumed.
See `docs/model-architecture.md` for the full modeling design and why it's shaped this way.

## Scope
- 5 historical seasons (2021-22 → 2025-26) for training; 2026-27 loaded live and evolving
- 138,702 real player-gameweek rows historically; 380 fixtures + rosters loaded for 2026-27

## Structure
```
FPL/
├── claude.md, README.md
├── docs/     (api-reference, historical-data-source, odds-sources, features-spec,
│              data-storage, model-architecture, strategy, GOTCHAS, build-spec-inspiration,
│              multi-gameweek-forecasting, live-refresh-runbook)
├── data/     fpl_cache.db (all layers fitted + live 2026-27 data), schema.sql, raw/
├── scripts/  one script per pipeline step, model layer, or live-data fetcher
├── backend/  FastAPI API layer over scripts/ + fpl_cache.db (see below)
└── frontend/ React + Vite webapp (see below)
```

## Webapp — backend + frontend, both with test suites
`backend/` is a thin FastAPI layer over the existing pipeline (imports `scripts/` directly,
never duplicates modeling logic) — endpoints for the player scout table, the ILP squad
optimizer (with gameweek-range + player-lock support), live league/team lookups, fixtures,
and model-run transparency. `frontend/` is React + Vite + TypeScript + Tailwind, with Player
Scout and Squad Builder fully wired to real data; League Hub/My Team/Fixtures/Model
Transparency are still stubs.

**Test suites** (37 tests, all passing):
```
cd backend  && python -m pytest -v      # 27 tests: ILP logic, math helpers, API integration
cd frontend && npm test                  # 10 tests: search/filter/sort, lock add/remove
```
Backend tests use synthetic fixtures for pure logic (`tests/conftest.py`) and the REAL cache
DB for API integration tests (read-only, safe). Frontend tests mock the API hooks directly and
exercise the actual interactive logic (typing, clicking, state updates), not just rendering.
One genuine bug was caught by writing these: a synthetic test fixture with only 3 clubs made
max-3-per-club mathematically impossible to satisfy for a 15-player squad — caught immediately
by `test_respects_squad_limits` failing, not left to be discovered in production.

## Status — full pipeline built, live, fast, and now beating FPL's own predictor

| Layer | Script | Result | Run id |
|---|---|---|---|
| 1: Team goals (Dixon-Coles) | `fit_dixon_coles.py` | Sanity-checked rankings | 1 |
| 1b: Odds blending | `blend_odds_with_model.py` | Beats model/market alone on average | 3 |
| 3: Minutes (hurdle model) | `fit_minutes_model.py` | Beats naive, all 5 folds | 10 |
| 2: Player involvement | `fit_player_involvement.py` | Uses real Layer 3 minutes, 2.25x faster | 28 |
| 4a: Defensive contribution | `fit_defensive_contribution.py` | Negative Binomial beats naive, all positions | 18 |
| 4b: Discrete events | `fit_discrete_events.py` | Clean across all event types | 7 |
| 5: Bonus points (LightGBM) | `fit_bonus_points.py` | Beats naive, all 5 folds | 9 |
| **Combined xP** | `combine_xp.py` | **MAE 0.988, beats FPL's own 1.022** — see below | 29 |
| Live team news | `fetch_live_team_news.py` | Verified against real injuries | — |
| Live minutes override | `apply_live_status_override.py` | Verified: 51/1934 players affected | — |
| Upcoming fixtures | `fetch_upcoming_fixtures.py` | 380 fixtures, 2026-27, verified | — |
| Current roster | `fetch_current_roster.py` | Verified against real transfers | — |
| Full live prediction | `predict_upcoming.py` | 577 real GW1 predictions | 30 |
| Optimizer | `optimise.py` | Real ILP squad, £100.0m/£100m, double-GW safe | — |

## Accuracy fix — RULE-BASED, not model tuning (the big one this session)
Re-audited the model against `claude.md`'s scoring rules with fresh eyes and found a real bug:
**clean sheet points and the goals-conceded penalty require the PLAYER to have played 60+
minutes**, not just that the team kept a clean sheet. The model was giving a substitute who
plays 5 minutes the same clean-sheet credit as a 90-minute starter. Fixed by multiplying both
terms by `P(60+ minutes)` (a quantity we already computed for appearance points, just not
reused here). Result:

- **MAE: 1.208 → 0.988** (18% reduction)
- **Correlation: 0.528 → 0.557**
- **We now beat FPL's own historical xP** (0.987 vs 1.022) — first time this has happened

This walks back an earlier claim in this file (now removed): I'd said the gap to FPL's own
predictor was an "inherent, structural disadvantage" from lacking live team news. That was
wrong, or at least overstated — a real chunk of it was a fixable correctness bug, not missing
information. Worth remembering: before concluding a gap is structural, check every scoring
rule's implementation against the actual ruleset first.

## Second rule-based fix — double gameweek safety in the optimizer
`optimise.py`'s player pool joined `model_predictions` directly with no aggregation. A double
gameweek (2 fixtures, 1 player, 1 gameweek — a real and strategically important FPL mechanic)
would have produced 2 rows for that player, and the ILP had no constraint stopping it from
"buying" the same player twice. Fixed by aggregating to one row per player (summing xP across
any fixtures in the gameweek) before optimizing — matches how FPL actually scores a double:
both fixtures count toward the one owned copy. GW1 has no doubles, so this couldn't be tested
against a real double yet, but the aggregation is a no-op (verified) when there's nothing to
aggregate, so it's safe either way.

## Performance optimization (measured before/after, not guessed)
`combine_xp.py::add_clean_sheet_prob` was silently costing 77s of a 217s total run via
`.apply(axis=1)` over 138k rows calling scipy functions one row at a time. Rewrote as pure
vectorized array math (verified numerically identical across 10,000 random cases first).
**217s → 35s (6.2x)**. Same fix applied to `add_team_lambdas` and
`fit_player_involvement.py::add_fixture_adjustment` (23.6s → 10.5s, 2.25x). Full writeup in
`docs/GOTCHAS.md`.

## Network note
`the-odds-api.com`/`football-data.co.uk` connection-reset on this machine (ISP-level gambling-
domain block) — worked around via `fetch_odds.py` run on an unrestricted network. 2026-27
odds not yet fetched this way.

## What's live and evolving (not frozen at season start)
`fetch_live_team_news.py`, `fetch_current_roster.py`, `fetch_upcoming_fixtures.py`,
`fetch_live_gameweek_stats.py` — full cadence and order in `docs/live-refresh-runbook.md`.
`fetch_live_gameweek_stats.py`'s per-fixture parsing is unverified against real data (the live
API returns empty pre-season) — check carefully after GW1 actually finishes (~24 Aug).

## Next Steps
1. **Verify `fetch_live_gameweek_stats.py` once GW1 finishes** (~24 Aug) — biggest open risk
2. Test the double-gameweek aggregation fix against a REAL double once one occurs in-season
3. Fetch 2026-27 odds once available (unrestricted network), wire into `predict_upcoming.py`
4. Build actual scheduling for the refresh runbook (currently manual)
5. Demo `suggest_transfers()` once there's a "current squad" concept to transfer from
6. Keep re-auditing scoring-rule implementation against `claude.md` — the 60-min clean-sheet
   fix suggests there may be other rule-conditionality gaps worth finding the same way
