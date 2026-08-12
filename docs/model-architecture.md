# Model Architecture — Why & How

## The core design decision
Don't train one black-box regression to predict `total_points` directly. Decompose the problem
into the same components FPL's own scoring rules use, model each with the statistical method
that actually fits its distribution, then recombine using the scoring formula. This is standard
practice in serious football-prediction tools (see references below) and it beats a single
regression for three concrete reasons:

1. **Linearity of expectation reduces variance.** E[points] = sum of E[each scoring component] ×
   its point value. Estimating 6 well-behaved sub-quantities (goal prob, assist prob, clean
   sheet prob, card prob, minutes, bonus) and summing them is lower-variance than estimating one
   noisy, multi-modal target directly from ~150 minutes of raw match noise per gameweek.
2. **Each component has a different natural distribution.** Goals/assists are counts → Poisson.
   Clean sheet/card/start-or-not are binary → logistic. Bonus points are a competitive ranking
   (top 3 in a match) → not naturally either, best left to gradient boosting. Forcing all of this
   through one regression wastes information.
3. **Interpretability.** A transfer decision based on "this player has a 61% chance to start,
   34% chance to score, opponent has a 28% clean-sheet-against probability" is auditable. A
   single opaque number from an XGBoost regressor is not — and this project's whole point is to
   understand *why* weights come out the way they do (per your earlier request), not just get a number.

## What this is inspired by (real, existing approaches)
- **Dixon-Coles model (Dixon & Coles, 1997)** — the standard statistical approach for football
  score modeling: each team gets an attack strength and defence strength parameter, combined
  Poisson-style to get a full scoreline probability matrix per fixture, with a small correction
  term for the tendency of low-scoring draws to be underestimated by plain independent Poisson.
  This is still the backbone of most serious football models today, often refined but rarely
  replaced outright.
- **Blending model output with bookmaker odds** — well-established finding in sports-forecasting
  literature: bookmaker odds already price in information a stats-only model doesn't have
  (team news, injuries, market sentiment), and blending model + market-implied probability
  consistently beats either alone. We should treat our Dixon-Coles-style team model and the
  odds-implied probabilities as two inputs to blend, not pick one over the other.
- **open-fpl-solver / sertalpbilal-style FPL tools** — confirmed real-world pattern: projections
  (the xP model) and squad optimization (the decision layer) are built as two separate stages.
  The optimizer takes a projections table as input and solves a linear/mixed-integer program
  (via a solver like HiGHS) for the best squad/transfers under budget & rules constraints. We
  should follow this same split rather than trying to bake "what should I do" into the model.

## Proposed layered architecture

### Layer 1 — Team-level goal model (Dixon-Coles style, blended with odds)
- Fit attack/defence strength per team per season (updated as the season progresses) using a
  Poisson/Dixon-Coles model on historical goals for/against, home/away split
- Blend the model's implied match probabilities with the odds-implied probabilities from
  football-data.co.uk (historical) / The Odds API (live) — literature-supported to outperform
  either alone; the blend weight itself is something to fit empirically, not assume
- Output per fixture: expected goals for/against per team, clean sheet probability per team

### Layer 2 — Player involvement model (Poisson decomposition)
- Given a team's expected goals (Layer 1), split into individual player scoring/assisting
  probability using that player's share of the team's xG/xA (recent rolling window, shrunk
  toward position-average for small samples — empirical Bayes style shrinkage, not raw rates)
- This is still Poisson-flavoured: P(player scores ≥1) derived from their expected goals share

### Layer 3 — Minutes/rotation model (classification)
- Logistic regression or gradient-boosted classifier: P(starts), expected minutes if started
- Features: recent starts, injury/news flags (if available), fixture congestion, squad depth
- This gates everything else — a nailed-on starter's 0.4 xG per 90 means far more than a
  fringe player's, so this needs its own model, not a shared assumption

### Layer 4 — Discrete event models (cards, penalties, saves, own goals)
- Simple rate-based Poisson/logistic models per player, since these are low-frequency events
  where historical rate + opponent tendency is about as good as it gets
- Card probability can additionally use team/referee aggregate tendency if we add that data later

### Layer 5 — Bonus points model (gradient boosting)
- Bonus points depend on BPS ranking within a match — inherently competitive/relative, doesn't
  fit a clean distributional assumption
- Best modeled with gradient boosting (LightGBM) on BPS-driving inputs (goals, assists, clean
  sheets, tackles, etc.) predicting expected bonus directly — this is the one place a "black box"
  ML model is the right tool, precisely because bonus doesn't decompose cleanly

### Combine into expected points
`xP = P(60+ mins)×2pts + P(1-59 mins)×1pt + P(goal)×goal_value + P(assist)×3
     + P(clean sheet)×cs_value − P(2+ conceded)×1 (GK/DEF) − P(yellow)×1 − P(red)×3
     − P(pen miss)×2 + P(pen save)×5 (GK) + E[bonus] + E[save points] (GK) − P(own goal)×2`
Every term is a learned probability/expectation from Layers 1-5, and `goal_value`/`cs_value`
come straight from the scoring rules in `claude.md`, keyed by position.

## Validation
- Walk-forward across the 5 seasons (train on N-1, test on season N), as already decided in
  `strategy.md`
- Evaluate probability components with calibration curves + Brier score/log loss (are our "30%
  chance to score" predictions actually right ~30% of the time?), not just final-points MAE
- Compare final xP against FPL's own `ep_this` as a baseline — if we don't beat it, something's
  wrong, since we have strictly more information (odds + our own feature engineering)

## Layer 6 — Optimization (the actual decision-support tool)
Once xP exists per player per gameweek, feed it into a proper optimizer rather than eyeballing
a spreadsheet — this is what turns the model into a *tool*:
- Mixed-integer linear program (MILP), following the open-fpl-solver pattern: budget constraint,
  max-3-per-club, formation rules, transfer cost (-4/extra transfer), captain doubling, chip
  timing — all as constraints, xP as the objective to maximize
- Solver: HiGHS (via `highspy`, free/open-source) or PuLP with CBC — both free, well-documented
- This also naturally handles multi-week planning (e.g. holding a transfer for a better future
  fixture) if we optimize over a rolling horizon instead of one gameweek at a time

## What changes in the existing docs
- `strategy.md` — supersede the single-regression-per-position plan with this layered approach
- `data-storage.md` schema — will need small additions later (team strength parameters per
  season, minutes-model outputs) once we start building Layer 1-3, not urgent now
