# Expected Points (xP) Strategy

## Superseded by docs/model-architecture.md
The original plan here was a single regression per position group predicting `total_points`
directly. That's been superseded by a layered approach (team goal model → player involvement →
minutes model → discrete events → bonus model → combine via the scoring formula), because
decomposing the problem the way FPL's own scoring rules decompose it gives lower variance and
actual interpretability, instead of one opaque number. Full reasoning and layer-by-layer design:
**see `docs/model-architecture.md`.**

## What stays true from here
- **Weights/parameters are learned from data, not assumed** — this still holds, just distributed
  across several smaller, better-fitted models instead of one big one
- **Walk-forward validation across the 5 seasons** — train on seasons 1..N-1, test on season N
- **Position-specific handling** — still true; scoring rules differ sharply by position
  (see `claude.md`), so the player-involvement and discrete-event layers are fit per position
- **football-data.co.uk for historical odds, The Odds API for live odds** — unchanged, see
  `docs/odds-sources.md`

## Immediate next steps (unchanged in spirit, updated in shape)
1. Build the FPL API collector, populate `fpl_cache.db` — still the first concrete task
2. Load football-data.co.uk historical odds into `match_odds`
3. Fit Layer 1 (Dixon-Coles-style team goal model, blended with odds) — see
   `docs/model-architecture.md` for the full layer breakdown
4. Fit Layers 2-5 (player involvement, minutes, discrete events, bonus)
5. Combine into xP via the scoring formula, validate walk-forward, log into `model_runs`
6. Feed xP into a MILP optimizer (Layer 6) for actual squad/transfer decisions — this is what
   makes it a tool, not just a forecast

## Open questions (carried over)
- Minutes-risk still needs its own model (now formally Layer 3)
- New signings / no-FPL-history players still need a fallback
- Team-name mapping across data sources still needed before joining odds + points data
- Whether player-level odds add value over the xG/xA-share-derived probability — test once
  enough live odds history accumulates
