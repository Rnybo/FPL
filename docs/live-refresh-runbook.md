# Live Refresh Runbook — keeping data fresh through the season

## The pieces (all built)
| Script | What it does | Cadence |
|---|---|---|
| `fetch_live_team_news.py` | Injury/suspension/doubt status, chance-of-playing % | **Daily**, more often near deadlines (news breaks Fri/Sat) |
| `fetch_current_roster.py` | Who's on which team (catches mid-season transfers) | Weekly, or after transfer windows |
| `fetch_upcoming_fixtures.py` | Fixture list + results for finished matches | Weekly (or after any postponement/reschedule) |
| `fetch_live_gameweek_stats.py` | Actual per-player results once a gameweek finishes | **After each gameweek finishes** — this is what makes the training set grow |
| `predict_upcoming.py` | Full pipeline → xP for the next gameweek | Run fresh each time any of the above changes, before making decisions |

## Order matters
1. `fetch_upcoming_fixtures.py` first — updates which fixtures are now finished vs still upcoming
2. `fetch_live_gameweek_stats.py` — pulls real results for any newly-finished gameweek into
   `player_gameweek_stats` (idempotent: safe to re-run, only picks up genuinely new gameweeks)
3. `fetch_current_roster.py` — catches any mid-season transfers
4. `fetch_live_team_news.py` — freshest injury/doubt picture, run again right before a deadline
5. `predict_upcoming.py` — recomputes xP using everything above, live-status override included

## When to re-fit the statistical models (not just re-run predictions)
`predict_upcoming.py` trains Layer 3 and Layer 5 fresh every time it runs (cheap enough — a few
seconds each), so those two are always current automatically. The heavier models are NOT
re-fit automatically and should be re-run periodically as the season's own data accumulates:

- **`fit_dixon_coles.py`** — re-run every few gameweeks. Team strength should absorb the new
  season's actual results, not stay frozen at a fit that only knows the 5 historical seasons.
  Once re-run, the 2026-27 season's results start counting toward "current form" via the
  existing recency-weighting — no code change needed, just re-running the fit.
- **`blend_odds_with_model.py`** — re-run whenever odds are refreshed for the new season
  (needs `fetch_odds.py` run again on an unrestricted network — see `docs/odds-sources.md`).
- **`fit_defensive_contribution.py`** — re-run periodically; every finished 2026-27 gameweek adds
  real DEFCON data, which matters a lot given we only had one season of it before.

## What's still frozen / needs building
- **No automatic re-fit trigger** — the above are still "run this script by hand," not a
  scheduled job. Building actual scheduling (cron/Task Scheduler) is a reasonable next step
  once the manual flow above is confirmed working through a real gameweek.
- **`fetch_live_gameweek_stats.py`'s per-fixture parsing is unverified against real data**
  (see `docs/GOTCHAS.md`) — check it carefully after GW1 actually finishes.
- Odds for 2026-27 haven't been fetched yet — `predict_upcoming.py` is currently model-only for
  every fixture (correctly falls back, per `docs/multi-gameweek-forecasting.md`, but blending
  would help once available).
