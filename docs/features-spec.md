# Model Feature Spec — Odds & Player Stats

## Season scope
5 most recently completed seasons: **2021-22, 2022-23, 2023-24, 2024-25, 2025-26**.
Model trains on these, predicts for the upcoming season (2026-27) once it starts.

## Why each feature is here
Every feature below ties to something that actually earns/loses FPL points (see `claude.md`).
Nothing is included "just in case" — each one maps to a scoring rule.

## A. Odds-derived features (per fixture, per team/player)
| Feature | Market source | FPL scoring link |
|---|---|---|
| Home win / draw / away win probability | h2h odds | Base for clean sheet & goal expectation |
| Clean sheet probability (per team) | Derived via Poisson from h2h + totals odds, or direct clean-sheet market if offered | Clean sheet: GK/DEF 4, MID 1 |
| Goals-for expectation (team) | Totals/over-under odds, split home/away | Feeds anytime-scorer probability per player |
| Anytime goalscorer probability (player) | Player goalscorer odds (live: Odds API; historical: derived from team goal expectation × player goal share) | Goal: GK/DEF 6, MID 5, FWD 4 |
| Anytime assist probability (player) | Player assist odds where available, else derived from xA share | Assist: 3 pts |
| Card probability (player/team) | Card/booking odds where available, else historical rate per player/referee tendency | Yellow -1, Red -3 |
| Penalty award/miss probability | Penalty-related odds/market where available, else historical penalty-taker rate | Penalty miss -2, penalty save +5 (GK) |

## B. Player historical stats (per player, per gameweek)
| Feature | Source | FPL scoring link |
|---|---|---|
| Minutes played | FPL API | Gates all points (60+ = 2pts, 1-59 = 1pt) |
| Goals, assists | FPL API | Direct points |
| xG, xA (expected goals/assists) | FPL API `expected_goals`/`expected_assists` | Underlying quality signal, more stable than raw goals/assists |
| Goal involvement (goals+assists, and xG+xA) | Derived | Combined attacking threat signal |
| Clean sheets, goals conceded | FPL API | Clean sheet pts; -1 per 2 conceded (GK/DEF) |
| Saves (GK) | FPL API | 1 pt per 3 saves |
| Penalty saves/misses | FPL API | +5 / -2 |
| Yellow/red cards | FPL API | -1 / -3 |
| Own goals | FPL API | -2 |
| Bonus points, BPS | FPL API | Direct points / bonus allocation signal |
| Form (rolling avg points, last 3/5/10 GWs) | Derived from FPL API history | Recency-weighted performance |
| ICT index, influence, creativity, threat | FPL API | FPL's own composite signals, used as secondary features |
| Price / value | FPL API | Not a scoring factor, but useful for ownership/differential later |
| Selected by % | FPL API | Not scoring, but useful for captaincy/differential ranking later |

## C. Fixture/team context features
| Feature | Source | Why |
|---|---|---|
| Fixture Difficulty Rating (FDR), home/away split | FPL API `fixtures` | FPL's own difficulty signal |
| Team attack/defence strength (home/away) | FPL API `teams` | Underlying strength behind FDR |
| Was home/away | FPL API | Home advantage effect |
| Days since last match / fixture congestion | Derived from `fixtures` | Rotation/fatigue risk proxy |

## D. Derived/engineered features (built during processing, not raw)
- Rolling averages (3/5/10 GW) for every per-gameweek stat above, computed with NO lookahead
- Season-to-date average blended with prior-season average (weight learned, not fixed)
- Position-relative normalization (a MID's 5 xG is different from a FWD's 5 xG)
- Minutes-risk flag (starts vs. rotation risk) as its own sub-feature/sub-model input

## Not included (for now, revisit later if evidence supports it)
- Weather, referee identity — plausible but no data source lined up yet, would add complexity
  without a way to validate whether it earns its keep

## Cross-reference
Full odds source details: `docs/odds-sources.md`. Full FPL API details: `docs/api-reference.md`.
Storage of all of the above: `docs/data-storage.md`.
