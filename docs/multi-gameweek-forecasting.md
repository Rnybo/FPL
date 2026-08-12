# Predicting odds for ALL upcoming matches, not just the next one

## The problem
Bookmakers only price matches close to kickoff — in practice, odds are reliably available for
roughly the next 1-2 gameweeks, not the rest of the season. But FPL planning (transfers, chip
timing, "who has the easiest run of fixtures") needs probabilities for every upcoming fixture
in a multi-gameweek horizon, most of which no bookmaker has priced yet.

## The answer: we already built the piece that solves this — use it explicitly
**Layer 1 (Dixon-Coles) doesn't need market odds at all.** It computes expected goals for any
fixture directly from team attack/defence strength, which is fitted from past results with
recency-weighting (see `fit_dixon_coles.py`) and updates continuously as new matches are played.
This works identically whether the fixture is tomorrow or in gameweek 30 — there's no dependency
on a bookmaker having priced it.

**Market blending (Layer 1b) is an opportunistic enhancement, not a requirement.** When odds
exist for a fixture, blend them in (learned alpha ≈ 0.65, see `blend_odds_with_model.py`). When
they don't, fall back to model-only. `combine_xp.py`'s `add_team_lambdas` already does exactly
this (`if target is None: lh_final, la_final = lh_model, la_model`) — it was built for the
"market data for this fixture doesn't exist yet" case, which is precisely what a 5-gameweek-out
fixture looks like. **This is the design, not a fallback to apologize for.**

## Why this isn't a quality downgrade for distant fixtures
The model's statistical uncertainty doesn't meaningfully increase for gameweek+5 vs. gameweek+1
— team strength parameters are what drive the prediction either way, and they're already
recency-weighted to reflect current form regardless of how far ahead we're predicting. What
distant fixtures genuinely lack is the *market's* extra information (injury news, suspensions,
sharp money) — which is exactly the same limitation identified for live team news in the
combined-xP gap analysis (README). Both point at the same underlying fact: our disadvantage
vs. bookmakers/FPL's own predictor is about **live information**, not modeling horizon.

As we get closer to any given future gameweek, our own team-strength estimates naturally
improve (more recent match data feeds the recency-weighted fit) — no special mechanism needed,
this happens automatically by re-running `fit_dixon_coles.py` periodically.

## Practical gap this exposes — needs building
Right now `load_fixtures_to_cache.py` only loads **finished** fixtures (`fixtures[fixtures["finished"]
== True]`) — by design, since the project has been backtesting against history. To actually
forecast upcoming gameweeks, we need to also load **unplayed** fixtures for the current season
(no scores yet, `finished=0`) from the live FPL API's `fixtures/` endpoint, so Layers 1/1b/2/3
have something to predict onto instead of only something to backtest against.

**New script needed**: `fetch_upcoming_fixtures.py` — pulls the current season's full schedule
(including future fixtures) from the live API, loads them into the `fixtures` table with
`finished=0` and null scores, distinguishable from historical training rows. This is the
prerequisite for `combine_xp.py` (or a new `predict_upcoming.py`) to produce real forward-looking
xP rather than only historical backtest numbers.
