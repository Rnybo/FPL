# Gotchas & Lessons Learned

Style borrowed from a CLAUDE.md pattern seen elsewhere: not "what the code does" but
"this broke, here's why, here's the fix — don't undo it." Read before touching the
related file.

## `players` table has fake players — filter position IN ('GK','DEF','MID','FWD')
FPL added a "pick a Manager" novelty pick; it leaks into player data with `position='AM'`.
One such row was literally Fabian Hürzeler, Brighton's actual head coach. Every script that
queries `player_gameweek_stats` joined to `players` filters this explicitly. If you add a new
script and forget the filter, you WILL get NaN/garbage rates for the ~322 affected rows (found
via a genuine `NaN` in `fit_discrete_events.py`'s output — that's the tell if it recurs).

## Points need expected COUNT (lambda), not "probability of ≥1"
`p_score`/`p_assist` (used in `fit_player_involvement.py`'s own validation) answer "will he
score" — fine for that question, WRONG for points math. A brace earns double goal points;
E[count] × points-per-event is exact regardless of multiplicity, P(≥1) × points-per-event is
not. `combine_xp.py` uses `lambda_goal`/`lambda_assist` directly for this reason. Don't swap
in `p_score` there even though it looks similar.

## Appearance points are a step function — E[minutes] alone can't give them
2 pts for 60+, 1 pt for 1-59, 0 otherwise. You need P(plays)×P(60+|plays) split out, not just
expected minutes. This is why `fit_minutes_model.py` has a third classifier (`clf60`) beyond
the original hurdle model — added specifically for `combine_xp.py`'s appearance_pts term.

## Dixon-Coles tau correction is defined on (home_goals, away_goals), not (team, opponent)
Clean sheet probability for a team needs different correction cells depending on whether that
team is home or away in the fixture. Got this wrong on the first pass in `combine_xp.py`
(`add_clean_sheet_prob`) — used the home-team correction cells unconditionally. Fixed by
branching on `was_home` explicitly. If you refactor this function, re-derive which cells apply
for each side rather than assuming symmetry.

## `filesystem:write_file` overwrites, it doesn't append — no `mode` param exists
Used `mode="append"` on it once building `schema.sql` incrementally; it silently ignored the
param and overwrote the earlier content. Caught by reading the file back before running it.
Use `desktop-commander:write_file` (has a real `mode: "append"`) for incremental file building.

## Sub-model outputs computed inside a helper function can silently overwrite upstream inputs
`fit_defensive_contribution.py`'s `add_rate_features()` computes its own `expected_minutes`
column using a weaker EWMA — when reused inside `combine_xp.py` on a dataframe that ALREADY
had the proper Layer 3 `expected_minutes` merged in, the helper silently clobbered it. Fixed by
re-assigning the Layer 3 value immediately after calling the helper. Any time you reuse another
layer's function on a dataframe with pre-existing columns, check what it writes, not just what
it reads.

## DEFCON only exists in the data from 2025-26 — verified empirically, not assumed
Checked the raw `stats` identifiers per season directly (`fixtures.csv`'s `stats` JSON column)
before concluding this — 2021-22 through 2024-25 genuinely don't have tackles/CBI/recoveries
per player anywhere in FPL's own data. Don't try to backfill this later without re-verifying;
external sources (FBref, Understat, WhoScored) are all bot-blocked from this network too.

## Gambling-domain network block vs. bot-protection block are different problems
`the-odds-api.com`/`football-data.co.uk`/`oddsportal.com`/`betexplorer.com` fail with a TLS
connection reset (ISP-level block, fixed by running on a different network — see
`fetch_odds.py`). `fbref.com`/`whoscored.com` fail with HTTP 403 (Cloudflare bot detection) —
switching networks will NOT fix this, it needs a real browser session or a different provider
entirely. Don't waste time re-trying a network switch on a 403.

## FPL's own gameweek numbering isn't 1:1 with matches played
A player's per-season match count can exceed 38 (a real GW label can cover more than one
fixture in double-gameweek weeks). Caused a `COUNT(*)` sanity check to look wrong at first
when validating Salah's loaded data — the underlying goals/assists totals were still correct,
only the naive "count of gameweeks" query was misleading. Also inflates row counts slightly
when joining on `(name, GW, season)` — seen in `combine_xp.py`'s FPL-benchmark comparison
(149,916 rows vs. our base 138,702).


## `fetch_live_gameweek_stats.py`'s per-fixture parsing is UNTESTED against real data
Written against the documented `explain` array structure (matches what vaastav's historical
scraper relies on), but `event/{id}/live/` returns an EMPTY `elements` list until a gameweek
actually kicks off — confirmed by calling it directly pre-season. So the harder logic here
(splitting stats by fixture for double-gameweeks) has only been verified structurally, not
against a real response. **Re-verify the output carefully after GW1 actually finishes**
(expect ~24 Aug 2026) before trusting it blindly — check a few players' loaded rows against
the official FPL site by hand.


## Layer 4a's overconfidence problem is deeper than shrinkage strength
Added credibility-weighted shrinkage (weight = n/(n+K), K learned via within-season split,
K=3) to fix the diagnosed overconfidence issue. Result: DEF improved slightly (LogLoss 0.3164→
0.3150), but MID/FWD got marginally WORSE (0.1768→0.1789, 0.0244→0.0251), and naive (flat
position rate) STILL beats the model on LogLoss for all three positions even after the fix.
This means the root cause isn't (just) insufficient shrinkage on thin samples — it's more
likely that a plain Poisson assumption (variance = mean) doesn't hold for defensive-contribution
counts, which are probably over-dispersed (some matches see unusually high tackle/CBI counts,
e.g. a team under heavy pressure). A Negative Binomial model (extra variance parameter) is the
next concrete thing to try, not more shrinkage tuning. Don't re-grid-search K expecting it to
close this gap — the loss curve already showed K=3 as the actual minimum on held-out data.


## RESOLVED: Layer 4a's over-dispersion diagnosis was correct
Negative Binomial (dispersion alpha=0.4427, confirmed >0 via method-of-moments on train split)
fully resolves the earlier LogLoss regression. Now beats naive on EVERY position for BOTH
Brier and LogLoss (DEF: 0.2415 vs naive 0.2859; MID: 0.1301 vs 0.1746; FWD: 0.0229 vs 0.0320)
-- a ~15-25% improvement, not marginal. The earlier shrinkage-only fix was solving the wrong
problem (K tuning helped DEF slightly, hurt MID/FWD) because the real issue was distributional
(Poisson's variance=mean assumption failing), not insufficient shrinkage. Lesson: when a fix
partially works in one segment and not others, check the distributional assumption before
tuning the same knob harder. model_run_id=18.


## Performance optimization pass (measured, not guessed)
Profiled before touching anything. Found the anti-pattern: `.apply(axis=1)` calling scipy
functions row-by-row over 138k rows is dramatically slower than vectorizing the same math
across whole arrays. Fixed two instances:

1. `combine_xp.py::add_clean_sheet_prob` -- was 77s of a 217s total run. Rewrote as pure
   array math (the Dixon-Coles tau correction only touches 2 of ~12 score cells, so the
   "sum everything else" step collapses to a single `poisson.cdf` call). Verified numerically
   identical across 10,000 random test cases before trusting it. Result: 217s -> 35s (6.2x).
2. `combine_xp.py::add_team_lambdas` and `fit_player_involvement.py::add_fixture_adjustment` --
   same `.apply(axis=1)` pattern for dict lookups, fixed with vectorized `.map()`/`np.where()`.
   `fit_player_involvement.py`: 23.6s -> 10.5s (2.25x), same output values confirmed.

Lesson: `.apply(axis=1)` is a red flag any time it appears on a dataframe with 100k+ rows --
check whether the per-row logic can be expressed as array operations before accepting the
runtime. Always verify old vs new numerically before trusting a "faster" rewrite -- a
performance fix that silently changes results is worse than no fix.


## RESOLVED (partially): season-boundary minutes-prediction bug, found via user question
User asked "why is Haaland's xP so low" -- traced it fully rather than guessing. Root cause:
Layer 3's classifier trusted `last_match_minutes==0` as strongly at a season boundary (his
last recorded match was a meaningless end-of-season rest) as it does mid-season (where 0
minutes usually means injury/dropped -- a genuinely strong signal there). Result: p_played
collapsed to 0.52 for an undoubted starter (ewm_play_rate=0.765), crushing expected_minutes
to 40/90 and every downstream component with it. Confirmed NOT isolated to Haaland: 54 other
otherwise-reliable players (Declan Rice, David Raya, Emiliano Martinez, Marc Guehi, etc.) had
the identical `last_match_minutes==0` pattern from a season-ending rest.

**Investigated and ruled out first** (don't skip this step next time either): fixture
difficulty (Man City has the #1 attack rating in the league), his underlying scoring rate
(0.65 goals-signal/90, a fair read of a real 0.82/90 season), live status override (no
injury flag). Also checked whether external "predicted lineup" data could help instead of
fixing our own model -- no: legitimate free/structured sources for MULTI-DAY-ahead starting
predictions don't really exist (the closest real data, confirmed lineups, only firms up near
kickoff, same limitation FPL's own API already has). This had to be a model fix, not a new
data source.

**Fix**: added `days_since_last_match` to Layer 3's feature set (fit_minutes_model.py) --
consistent with the project's "learned from data, not assumed" principle: rather than
hardcoding a rule at inference time (which would create a train/inference mismatch), this
lets the model LEARN the season-boundary pattern from the 4 real historical season
transitions in the training data. Confirmed it's the 2nd-most-important feature post-fix
(433, just behind ewm_play_rate's 469, ahead of raw last_match_minutes at 251).

**Honest result -- real but partial**: Haaland's p_played 0.524->0.575, expected_minutes
40->45.5, GW1-5 xP 13.77->15.24 (+10.7%). Checked calibration on the actual historical
season-boundary subset (1001 real rows matching his pattern): mean predicted p_played
(~0.79) tracks the actual observed rate (~0.78) well -- the fix is genuinely working in
aggregate. Haaland individually sits toward the lower tail of that reasonably-calibrated
distribution (his own ewm_play_rate, 0.765, isn't as unambiguous as the safest picks) --
this may be a legitimate, if slightly conservative, read rather than a remaining bug.
Tried increasing tree max_depth (4->8) to let the model learn a richer interaction -- gave
negligible further improvement (LogLoss 0.5284->0.5256 on the affected subset) -- diminishing
returns, left at max_depth=4. model_run_id=33 (Layer 3), 34 (predict_upcoming).


## RESOLVED (properly this time): season-boundary bug -- follow-up to the Haaland fix
User pushed back correctly: the days_since_last_match fix "resolved" via the earlier calibration
check was too coarse -- it averaged rested-starters and normal-starters together, hiding a real
problem. Checked the EXACT pattern directly this time (last_match_minutes==0 specifically, n=112
historically) and found it was NOT fixed: predicted p_played ~0.52 vs actual 60-87% in 3 of 4
holdouts. Also found the mirror-image bug: rare backups getting a meaningless late-season
runout (n=22) had predicted p_played ~0.41-0.51 vs actual 0.00-0.31 -- systematically OVER-predicted.
Concrete user example that exposed it: Arsenal's Raya (clear #1) vs Kepa (clear backup) were
coming out too close together (0.564 vs 0.326 p_played) when they should be starkly separated.

**Two further fixes, both validated against the specific failing patterns, not just aggregate
metrics** (lesson: always check the SPECIFIC subgroup a bug was found in, not just an average
that can hide it):
1. `decayed_last_match_signal` feature (last_match_minutes * exp(-days_since_last_match/30)) --
   engineers the interaction directly rather than hoping trees learn it from ~20-100 historical
   examples, which turned out to be too few.
2. Sample weighting (15x) for season-boundary rows in the P(plays) classifier's training loss --
   these rows are only 3.37% of all data, too rare for the loss function to prioritize even with
   the right feature. Costs ~0.001-0.002 LogLoss on the other 96.6% of rows (checked directly),
   worth it given how much the season-opener prediction matters right now.

**Result, checked directly on real players, not just backtest averages**: Haaland's p_played
0.575->0.700+ (jumped from outside the top-20 total-xP list to #4). Raya's p_played 0.564->0.700,
expected_minutes 51->63. Kepa's p_played 0.326->0.265 (correctly moved DOWN), expected_minutes
28.5->23.6. Raya's total GW1-5 xP (13.71) now clearly separated from Kepa's (4.79), ~2.9:1 --
matches the real pecking order instead of both being muddled toward the middle.

**Still not perfect**: the backup-runout side barely moved with weighting alone (too few
examples, ~18-22, for any single technique to fully resolve) -- if a similar case surfaces
again for a different position/club, the next lever to pull is probably combining BOTH fixes'
logic with an even larger weight multiplier specifically for the rare-backup sub-pattern, not
assuming this is fully closed. model_run_id=36 (Layer 3), 37 (predict_upcoming).


## MAJOR FINDING: duplicate player_id records from accent-encoding mismatch (found via user pushback on Raya)
User provided concrete real-world stats (Raya: 37/38/32/38 starts across 4 seasons, minutes
exact multiples of 90 in 3 of them) that didn't match our model's prediction. Investigating
this properly (not just re-tuning hyperparameters again) found the REAL cause: Raya's history
was split across TWO player_id records due to an accent-encoding mismatch between the
historical bootstrap import and the newer live-fetch pipeline -- "David Raya Martin" (id=429,
2021-22..2024-25, plain encoding) and "David Raya Martin with proper accents" (id=1793,
2025-26 only, UTF-8). Our current-state features for the ACTIVE id (1793, the one predict_
upcoming.py's roster query uses) were computed from only his single most recent season --
completely blind to 3+ years of even stronger evidence sitting in the orphaned record.

**Confirmed this is systemic, not a one-off**: found 28 real players affected via a
strip-accents name-matching query with a non-overlapping-seasons confirmation check (ruling
out coincidental name collisions). Includes several important players: Gundogan, Kovacic,
Kelleher, Edouard, Lavia, Dragusin.

**Fix**: `scripts/merge_duplicate_players.py` -- dry-run by default, `--apply` to commit.
Picks the canonical id as whichever has a player_season row for the CURRENT season (the one
the live pipeline actually queries), re-points all 6 tables referencing player_id, deletes the
orphaned record. Applied cleanly, no conflicts (season sets were confirmed non-overlapping
before merging).

**Result on Raya specifically**: p_played 0.700 -> 0.749 after the merge + retrain. Smaller
than hoped, and diagnosed exactly why: `ewm_play_rate` (the dominant feature) barely moved
(0.8895->0.8909) because its halflife=6 window was already saturated by his most recent
~10-15 matches even before the merge -- the merge's real benefit is more structural
(games_since_last, last_match_minutes no longer artificially "start fresh"), not a big lift
to the single most-important feature.

**Tried a longer-halflife (25-match) play-rate feature to use the newly-available multi-season
history directly** -- aggregate backtest showed a small improvement (0.819->0.823 vs actual
0.826 on the >=0.85 band), but Raya's OWN individual prediction went the WRONG way with it
(0.749->0.622). Did NOT ship this -- a feature that helps in aggregate but regresses on the
exact case it's meant to fix needs more careful investigation before trusting it, not a quick
ship. Left as a documented open lead for a future, more careful session, not assumed safe.

**Overall lesson, worth internalizing**: three different investigation rounds (Haaland, then
Raya/Kepa, then this) each initially looked "fixed" by an aggregate calibration check that
turned out to be too coarse or, in this final case, the deeper issue was a DATA bug, not a
modeling one at all. When a user's concrete real-world numbers disagree with the model, check
the actual underlying data referenced for that specific entity before assuming it's a
hyperparameter or feature-engineering problem -- the data bug here was more consequential and
more fixable than any amount of further model tuning would have been.


## NEW PRACTICE: backtest_report.py -- repeatable end-to-end backtesting (user request: "train on old games, iterate, get smarter")
combine_xp.py already validated leave-one-season-out (MAE 0.988, pooled across all 5
seasons) but that ONE number can hide systematic bias -- errors in opposite directions
cancel out in a pooled average. Built `scripts/backtest_report.py` on top of it (reuses
combine_xp's pipeline via a new `build_combined_xp_dataframe()` function, extracted from
combine_xp's __main__ without changing its behavior -- verified MAE=0.988 unchanged after
the refactor) to slice the SAME predictions by season, position, player tier, season-stage,
and scoring component. Meant to be re-run after every model change -- this IS the
"iterate and get smarter" loop the user asked for, made concrete and repeatable rather
than a one-off check.

**Honest methodology caveat**: "leave-one-season-out" trains on the other 4 seasons
regardless of chronological order -- for 4 of the 5 seasons, the model can see FUTURE
seasons during training. Only the 2025-26 holdout (nothing chronologically after it in
our data) is genuinely walk-forward in the strict sense. The other 4 rows are legitimate
cross-validation, just not "what we'd have known before it happened" in the strictest
sense -- don't overstate this as full walk-forward for all 5 seasons.

**First run's findings** (before any fix):
- By season: MAE ranged 0.921 (2023-24) to 1.110 (2021-22).
- By position: FWD bias -0.113 (systematic under-prediction), GK MAE excellent (0.678,
  low variance in GK scoring by nature).
- By player tier (season-total-points quartile): Q4 "stars" MAE=2.251, bias=-0.445 --
  BY FAR the worst-calibrated group, and the one that matters most for actual squad
  decisions (captaincy, big transfers). Q1 "fringe" trivially accurate (mostly predicting
  near-zero for players who mostly score near-zero).
- By season stage: early-season MAE=1.094 vs late-season MAE=0.904 -- confirms accuracy
  genuinely improves as in-season data accumulates (expected, not a bug) -- and flags that
  our CURRENT real situation (predicting 2026-27 with zero in-season data) is the
  structurally hardest case.
- **Component calibration -- the actionable one**: goals -9.7% under-predicted, assists
  -29.8% under-predicted (three times worse than goals).

## RESOLVED (partially -- see remaining Q4 bias below): xG/xA systematically undershoot real output
Root cause: `xg.fillna(goals)` used pure xG/xA as the training signal. Since xg/xa have
~100% coverage from 2022-23 onward, the fillna fallback to raw actual counts almost never
triggered. Checked directly against real match data: xG undershoots actual goals by -23.5%
in aggregate, xA undershoots actual assists by -46.6% -- a real, well-documented property
of these metrics (good finishers/passers consistently outperform the pre-shot/pre-pass
"quality" estimate), not a data bug. This propagated straight through to final xP,
concentrated hardest on exactly the players who most outperform their underlying chance
quality -- i.e. the stars.

**Two-stage fix, backtested rather than assumed** (see fit_player_involvement.py's
add_player_rate_features docstring): swept blend weights [0.0-1.0] between xG/xA and raw
actual counts. Brier/LogLoss (per-match discrimination) is minimized around blend=0.6 for
BOTH goals and assists -- not either pure extreme. But the aggregate calibration gap keeps
shrinking toward blend=0.0. Rather than compromise both with one knob: kept blend=0.6 for
the per-match rate (best discrimination) and added a SEPARATE calibration multiplier
(also backtested: actual_total/predicted_total AT blend=0.6) that corrects the aggregate
level without touching the relative ranking the blend already gets right.

**Found and fixed a duplication that would have silently limited this fix to the backtest
only**: predict_upcoming.py builds `quality_goal_signal`/`quality_assist_signal`
independently from fit_player_involvement.py (its own copy of the old `xg.fillna(goals)`
line), used for the LIVE 2026-27 predictions actually served via the API. Fixing only
fit_player_involvement.py would have improved backtest_report.py's numbers while leaving
the real served predictions completely unfixed. Applied the identical blend + calibration
multiplier there too, verified via the running API afterward.

**Results, re-run through backtest_report.py after the fix**:
- Component calibration: goals -9.7% -> +1.7%, assists -29.8% -> +1.6% -- both now close
  to perfectly calibrated in aggregate.
- Overall bias: -0.056 -> -0.003 (systematic under-prediction essentially eliminated).
- By position: FWD bias -0.113 -> +0.004, MID -0.080 -> -0.008, DEF -0.021 -> +0.003.
- **Honest trade-off**: pooled MAE went 0.988 -> 1.006 (slightly WORSE) -- blending in
  actual counts adds per-match noise even as it fixes the systematic direction. Still
  clearly beats FPL's own predictor (1.003 vs 1.018), just by a smaller margin than
  before (was 0.984 vs 1.018). Judged this trade-off worth it: a systematically-biased-low
  estimate concentrated on your best assets is worse for real squad decisions than a
  slightly-higher-variance but unbiased one.
- **NOT fully resolved -- flagged for the next iteration, not force-fixed now**: Q4 (star)
  bias improved from -0.445 to -0.312 (~30% better) but a real, meaningful under-prediction
  remains specifically for star players. Something beyond goal/assist calibration is still
  at play for this group -- worth investigating next (bonus points for high-BPS players?
  something about how minutes-certainty compounds for players who are both high-minutes AND
  high-output? not yet diagnosed).

Concrete, checkable trail for Haaland's own expected-goals-over-5-games number across this
whole session's iterations: 2.05 (original) -> 2.30 (halflife fix alone) -> 2.71 (this
blend+calibration fix, current live value). Re-run backtest_report.py after any future
model change to keep building this trail, not just trust that a change "should" help.


## NEXT ITERATION (precisely diagnosed, NOT fixed -- deliberately deferred, see reasoning below)
Continuing the Q4 star-player bias investigation from backtest_report.py's first run
(bias -0.445, improved to -0.312 by the goal/assist blend fix above). Broke Q4's
remaining xP gap down by COMPONENT: cs_pts (clean sheet points) is the single largest
driver, -5984 aggregate points, more than double the goal_pts gap (-2612).

Isolated the mechanism precisely: cs_pts = p_clean_sheet * CLEAN_SHEET_POINTS * p_60plus.
- p_clean_sheet itself: essentially perfectly calibrated for Q4's teams (predicted 0.2749
  vs actual 0.2730) -- NOT the source, team-strength/Dixon-Coles modeling is fine.
- p_60plus (= layer3_p_played * layer3_p_60plus_given_played): predicted 0.6672 vs actual
  0.7165 for Q4 specifically -- a real, meaningful under-estimate. THIS is the driver.

Checked whether this is just the ALREADY-KNOWN season-boundary issue (rested reliable
starters, addressed earlier this session via BOUNDARY_SAMPLE_WEIGHT+decayed_last_match_signal):
partially, but not fully. Season-boundary rows are only 1.8% of Q4's data, show a much
bigger gap when isolated (-0.144) confirming that fix still leaves SOME residual boundary
under-confidence -- but the other 98.2% of Q4's rows (completely ordinary, mid-season,
non-boundary matches) STILL show a real -0.048 gap on their own.

This is a genuinely subtle finding: checked Layer 3's classifiers' calibration curves by
PREDICTED-probability decile, pooled across the whole player population -- both clf
(P played) and clf60 (P 60+ | played) are essentially perfectly calibrated at every
decile, including the top one. Yet Q4 stars specifically are under-confident even outside
the season-boundary case. This means population-level decile calibration passing does NOT
guarantee subgroup calibration -- some feature combination correlated with "elite,
highly-reliable player" is getting mild under-confidence that a DIFFERENT subgroup landing
in the same overall probability decile (via different features) apparently over-corrects
for, canceling out in the pooled check while remaining real for this specific subgroup.

**Deliberately NOT fixed this session** -- flagging why, not just running out of turns:
the one prior attempt at a similar-shaped fix (a longer-halflife reliability feature,
tried for the Raya investigation) improved the aggregate backtest metric but made HIS
specific case WORSE when checked directly -- a direct, concrete precedent for why a
rushed fix here, without equally careful before/after validation on real individual
cases (not just the aggregate Q4 number), risks the same outcome. This needs its own
dedicated pass: likely a per-feature calibration breakdown (is it games_since_last?
price_shifted, as a proxy for "known star"? something else?) before trying a specific
fix, then validating both the aggregate Q4 metric AND a few individual real players'
numbers before calling it resolved -- exactly the discipline that caught the Raya
regression the first time.

Concretely: re-run backtest_report.py's per-tier breakdown as the check for whether a
future Layer 3 change actually closes this gap, and pull up a couple of real Q4 players'
individual p_60plus values (not just the pooled Q4 average) the way the Raya check did,
before trusting any fix.


## CORRECTION to the Q4 star-player bias finding above: it was substantially a methodology artifact
Continuing the "next iteration" flagged above (Q4 bias -0.312, traced to P(60+ minutes)).
Before touching Layer 3, verified the mechanism first, following the same discipline that
caught the Raya regression earlier: checked calibration against a feature knowable IN
ADVANCE (ewm_play_rate > 0.85) instead of Q4's own definition. Gap vanished almost entirely
(-0.0005 to -0.0004 across tree depths 4/6/8) -- no real, feature-identifiable "elite
player" blind spot in Layer 3's classifiers.

**Ran a controlled test to confirm why**: simulated a PROVABLY unbiased predictor (predicts
true ability exactly; actual = ability + pure random noise, overall bias ~0 by
construction), then grouped by the predictor's own OUTCOME quartile the same way Q4 was
defined. Result: bias +4.0 for the bottom outcome-quartile, -4.1 for the top -- despite the
predictor being mathematically unbiased. This is regression-to-the-mean under outcome-based
selection: ANY imperfect predictor will show this shape when grouped by realized outcome,
because the top-outcome group mechanically includes players whose ACTUAL results exceeded
prediction (that's how they got to the top), independent of whether the predictor itself
has any real, fixable flaw.

**The real fix wasn't a model change -- it was the backtest's own tiering methodology.**
`report_by_tier` in backtest_report.py tiered by realized SEASON-TOTAL points (an outcome).
Added `report_by_price_tier`, tiering by `price_at_time` instead -- known before the match
is played, set by FPL based on expected quality, can't manufacture the artifact above since
it doesn't condition on the outcome being evaluated. Added `price_at_time` to
combine_xp.py's load_master_data to support this (confirmed via re-run: headline MAE
unchanged at 1.006, a pure addition with no side effects).

**Result**: under the trustworthy, ex-ante tier, Q4 (priciest players) shows bias=-0.053 --
an order of magnitude smaller than the outcome-based -0.312. A small, real, honest residual
under-prediction for expensive players still exists and is worth keeping an eye on in future
iterations, but it does NOT justify the kind of targeted intervention that would have been
tempting to build against the original -0.312 number. Kept BOTH tier functions in
backtest_report.py (not just quietly swapped) specifically so this artifact stays visible
for anyone reading the report, rather than the fix silently making the original caveat
invisible.

**The actual lesson for this project's whole "iterate and get smarter" practice**: when a
backtest slices by something that's itself a noisy function of the very outcome being
evaluated, a real-looking bias can appear even in a genuinely correct model. Always check a
suspicious subgroup finding against at least one feature/grouping that's knowable in
advance before trusting it enough to act on -- exactly the check that separated the real
xG/xA fix (verified independently, against real match data, not outcome-conditioned) from
this one (which dissolved under the same scrutiny).


## RESOLVED: DefCon under-prediction (-8.3%), traced to a real, verified seasonal trend
Continuing the model-improvement loop, picked the next unaddressed component gap from
backtest_report.py: "Def. contribution hit" at -8.3%, the largest remaining miscalibration
after the goal/assist fix above.

Diagnosed properly before touching anything (same discipline as the Q4 investigation):
broke the gap down by games_played_before this season. Found it WORSENS for well-established
players (16+ games: -11.3%), the OPPOSITE of what a "not enough history yet" story would
predict. Checked directly against real per-gameweek data: defensive_contribution rates rose
substantially over 2025-26 (DEF +12.0%, MID +9.4%, FWD +22.4%, early vs late season) -- a
real trend, not model noise. Plausible cause: 2025-26 is DefCon's first season as a scoring
category, so players/teams likely adapted tactics once its fantasy relevance became clear.
A backward-looking EWM (halflife=6) necessarily lags a rising trend, and the lag compounds
for players whose shrinkage weight relies almost entirely on their own historical rate (i.e.
exactly the well-established players).

**Fix**: tested halflife values [2,3,4,6,8,12] -- same trade-off shape as the goal/assist
fix (shorter halflife improves aggregate calibration but costs LogLoss slightly). Rather
than compromise, kept halflife=6 (near-best for discrimination) and learned a separate
calibration multiplier -- but on the underlying RATE (mu), not the probability directly,
since probability is bounded [0,1] while the rate isn't and the NB survival function is
nonlinear: inverted it via root-finding to find the exact multiplier (1.0438) that
reproduces the real total actual hits (1426) from the real total predicted. Applied in both
combine_xp.py and predict_upcoming.py's independent DefCon computation (checked for and
found the same kind of duplication as the earlier goal/assist fix -- would have silently
left live 2026-27 predictions unfixed otherwise).

**Deliberately a FLAT correction, not trend-shaped**: only one season of DefCon data
exists. Assuming the exact trend SHAPE observed in 2025-26 (a smooth rise) repeats
identically in 2026-27 would be overfitting to what might be a one-time adaptation
transient specific to the rule's introduction season, not a permanent seasonal pattern.
A flat multiplier corrects the verified aggregate bias without assuming more than the data
supports.

**Result**: Def. contribution hit calibration -8.3% -> -0.0% (exact, by construction of
the root-finding). Overall MAE 1.006 -> 1.007 (unchanged within rounding), overall bias
-0.003 -> -0.001 (even closer to zero). Price-tier Q4 bias improved marginally (-0.053 ->
-0.050) -- DefCon is a smaller contributor to total xP than goals/assists, so a modest
effect on the broader star-player picture is expected, not the primary driver (clean
sheets, still +4.7% over-predicted, remains a bigger piece of that puzzle for next time).


## CONFIRMED (no fix needed): price-tier already correctly tracks in-season breakouts
User asked to "keep Q4 updated along the way, even lower priced players can during the
season become Q4 players" -- checked directly with a real example before assuming a fix
was needed. report_by_price_tier already tiers PER ROW (per gameweek) using price_at_time,
which genuinely updates in-season -- verified with real data: Bruno Fernandes rose
GBP8.9m->GBP10.4m within 2025-26, Igor Thiago GBP6.0m->GBP7.4m, and specifically checked
Cole Palmer's actual 2023-24 breakout gameweek-by-gameweek: starts Q3 at GBP5.0m (GW1),
correctly transitions to Q4 by GW14 as his price rises to GBP5.3m, and stays there for
the rest of the season. The mechanism already does exactly what was asked -- confirmed,
not assumed, before reporting back.

Side note while checking this: found several rows in 2024-25 with price<GBP2.0m that
turned out to be managers (Guardiola, Arteta, van Nistelrooy), not players -- this is the
SAME "pick a Manager" leak documented earlier in this file. Confirmed it's harmless here:
my ad hoc diagnostic query simply skipped the position filter that every real
model-fitting script already applies; not a new bug, just a reminder the filter matters
whenever writing throwaway diagnostics too.

## RESULT: variance reduction attempt on Layer 5 (bonus) -- bagging failed, shrinkage helped (small but real)
User asked to try a genuinely different kind of improvement (variance, not bias).
Bonus points (Layer 5, LightGBM regressor) is the noisiest, hardest-to-predict layer --
a natural candidate.

**Tested bagging first (classic variance-reduction technique)**: averaging multiple
LightGBM models across random seeds. First pass showed IDENTICAL MAE regardless of
n_models -- a real gotcha: setting random_state alone has no effect unless
bagging_fraction/feature_fraction are also enabled (LightGBM does no row/column
subsampling by default, so there's no actual randomness to seed). Re-tested with genuine
stochasticity enabled (bagging_fraction/feature_fraction 0.8-0.9): honest negative result
across every configuration tested -- the best case (even after averaging 20 models) was
still slightly WORSE than the plain, un-bagged single model (0.15467). Concluded bagging
isn't a useful lever here -- the bottleneck is likely irreducible data noise (in-match BPS
competition dynamics), not model variance averaging could reduce.

**Pivoted to shrinkage** (blending the LightGBM prediction with a simple recency-weighted
average of the player's own past bonus): backtested across the full [0,1] blend-weight
range, found a real, monotonic improvement bottoming out around blend_weight 0.3-0.5
(0.15467 -> ~0.15455, ~0.08% relative). Small, but genuine -- validated the same way as
every other fix this session, not assumed. Notable secondary finding: the optimal blend is
surprisingly low, meaning the simple recency-weighted baseline captures nearly as much
signal as LightGBM's full feature set (xG, xA, threat, creativity, influence, etc.) --
worth remembering if Layer 5's feature set gets revisited later.

Implemented BLEND_WEIGHT_BONUS=0.4 in fit_bonus_points.py, applied inside train_and_eval
(used by combine_xp.py directly, no separate fix needed there). Found and fixed the SAME
live/backtest duplication pattern hit twice already this session: predict_upcoming.py
calls l5_model.predict() directly on live data, which would have bypassed the blend
entirely (the blend lives inside train_and_eval, not the model object) -- fixed to apply
the identical blend there too, verified the exact expected MAE (0.15455) reproduces when
checked directly against the real pipeline, not just the isolated test.

**Honest scale of this fix**: it's real and validated, but small -- doesn't move the
overall xP MAE at 3 decimal places (still 1.007). Documented here anyway because the
project's own practice is to validate and record every real, checked improvement, not
just the dramatic ones, and because the negative bagging result is itself a useful,
recorded lesson for anyone tempted to reach for ensembling as a default variance-reduction
move without checking whether the LightGBM config is actually introducing any diversity
to average over.


## RESOLVED: second, larger wave of duplicate-player fragmentation (37 groups) -- found via external comparison
User shared screenshots of a third-party FPL prediction tool and asked how our numbers differ.
Investigating this properly (pulling our own exact numbers for the same players/gameweeks rather
than guessing) immediately surfaced Bruno Fernandes showing EXACTLY 0.00 predicted points for
every gameweek -- a glaring, unmissable red flag once actually checked.

Root cause: player_id=5 ("Bruno Miguel Borges Fernandes", 2021-22 only, no 2026-27 link) vs
player_id=769 ("Bruno Borges Fernandes" -- middle name "Miguel" dropped, 2022-23 onward + the
live 2026-27 roster link). The EARLIER duplicate-merge fix (accent-stripping match) couldn't
catch this: it's not an accent difference, an entire name token is missing between sources.
Confirmed id=5 wasn't a live user-facing bug (no 2026-27 link means it never appears in
/api/players), but it WAS corrupting the training data quality for years of history that
should have belonged to id=769.

**Checked the scope properly rather than assuming Bruno was a one-off**: generalized the
matching key from "exact name after stripping accents" to "(first token, last token) after
stripping accents" -- catches dropped middle names too. Found 37 confirmed groups (verified
non-overlapping seasons, same discipline as the original 28), including several significant
players: Rodri, Alisson, Gabriel Magalhaes, Martinelli, Idrissa Gueye, Matheus Nunes, Antony,
and a 3-way split (Joao Cancelo across 3 ids). Rewrote merge_duplicate_players.py to handle
groups of any size (not just pairs) and merged all 37 after a dry-run review.

**Result**: Bruno Fernandes 0.00 -> 29.07 (GW1-5) after retraining every layer and
regenerating predictions -- specifically his GW1-3 total (18.19) now closely matches the
external tool's GW1-3 total (18.70), a ~3% gap instead of a complete miss. Re-ran
combine_xp.py afterward: overall MAE unchanged/marginally improved (1.008, still clearly
ahead of FPL's own predictor), confirming this large a merge didn't disturb overall
calibration -- it just fixed 37 players' worth of previously-fragmented history.

**Lesson for future dedup passes**: name-matching heuristics need to be revisited whenever a
NEW class of mismatch is suspected, not assumed fully solved after the first pass. The
original accent-stripping fix was real and correct for what it caught, but "solved" turned
out to mean "solved for accent differences specifically," not "solved for all name-format
divergences between the historical and live-fetch pipelines."

## External comparison, evidence-based (not just "we're lower")
With the merge fix applied, compared our GW1-3 predictions against the third-party tool's for
8 named players. Most (6 of 8) are 15-30% lower than theirs; Bruno now matches closely (~3%
gap); Wirtz is a dramatic outlier (~43% lower).

**Bruno**: was a straightforward data bug (above), now resolved.

**Most others (Haaland, Semenyo, Watkins, Palmer, Igor Thiago, Mbeumo)**: checked Haaland's
component breakdown specifically since it's the most cleanly quantifiable -- our GW1-3 goal_pts
(7.33) implies 1.83 expected goals; their stated pG is 2.56 -- a real, ~29% gap in the
underlying goal-scoring RATE specifically, not a formula or scoring-rule difference (assists
were actually very close: ours 0.41 vs their 0.39). This connects directly to this session's
own already-documented, still-open finding: price-tier Q4 (priciest players) showed a real,
unresolved -0.050 bias even after the xG/xA blend fix, and star players' P(60+ minutes) showed
mild under-confidence even outside the season-boundary case. This external comparison is
independent evidence pointing at the same underlying area (elite/expensive players still
running slightly conservative), not a new, disconnected finding.

**Wirtz specifically (the biggest gap, ~43-50% lower on both goals and assists)**: checked his
real history directly -- NOT a new-to-PL data gap (he has a full, genuine 2025-26 season: 38
games, but only 5 goals + 4 assists, a modest statistical return relative to his price/
reputation as a big-money signing). Our recency-weighted model is very likely faithfully
reflecting his actual underwhelming recent PL output. The gap here is most plausibly a genuine
difference in MODELING PHILOSOPHY, not a bug: the external tool may weight price/reputation/
non-PL underlying stats (e.g. Bundesliga output) more heavily than one season of PL data,
while our model has no mechanism to incorporate anything beyond PL history -- a real,
documented LIMITATION (we can't distinguish "genuinely underperforming" from "still elite,
just needs a settling-in period") rather than something to force-fix by assuming a prior we
have no data to justify.


## RESOLVED (properly, this time): permanent fix for player identity, not another dedup patch
User asked directly: how do we make sure naming conventions don't break again, and how do we
handle genuine namesakes (two different real people sharing a name)? Both good questions the
project had been dodging by reactively detecting and merging duplicates after the fact --
twice this session (accents, then dropped middle names). A third name-format edge case would
have found a third way through eventually; name STRINGS are fundamentally the wrong identity
key, not just something to keep patching.

**The real fix**: FPL's own data already has a stable, Opta-assigned `code` field per real
person -- confirmed present in both the live bootstrap-static API and the historical
players_raw.csv snapshots (checked directly, not assumed), and NEVER changes across seasons,
transfers, or name formatting. Exactly the same pattern already used for team shirt codes.

Added a `code` column to `players`. Rewrote fetch_current_roster.py (the live pipeline) to
key identity by `code` FIRST -- name-matching is now only a one-time bridge for rows that
predate this fix, and every touch backfills the code so the bridge is never needed twice for
the same row. Name itself is now refreshed freely on every run (formatting can improve over
time) without ever being confused with identity again.

**This also directly answers the namesake question**: `code` is assigned by the data provider
per real individual -- two different people who happen to share a name get different codes,
so they can never be incorrectly merged. The OLD approach (matching by name + a
non-overlapping-seasons check) could not fully rule this out: two genuinely different real
people with the same name and non-overlapping career spans (rare, but possible) would have
looked identical to that check.

**Safety net added, not just a one-time fix**: fetch_current_roster.py now checks after every
run whether any `code` maps to more than one player_id and prints a loud warning if so --
proactive detection instead of waiting for a user to notice broken predictions again.

**Verified live**: re-ran fetch_current_roster.py twice. First run backfilled code for all
577 currently-rostered players via the name-fallback (confirmed zero new duplicate rows
created -- total player count unchanged at 1978). Second run correctly showed "0 newly seen"
(everyone already resolved via code). Bruno Fernandes confirmed as exactly one player_id with
his code correctly populated.

**Deliberately NOT done today, and why**: a full historical backfill of `code` for player_id
rows that aren't on any current roster (retired/dropped-out players, still used for OTHER
players' training data quality via their historical seasons). Fetched and inspected the
historical players_raw.csv files directly (confirmed they DO have `code`), but transferring
a genuinely complete 1797-entry mapping wasn't worth doing as a rushed partial job -- a
half-applied backfill would leave an inconsistent, confusing state. Documented the exact
approach needed in load_player_gameweeks_to_cache.py's own docstring (fetch players_raw.csv
alongside merged_gw.csv, join on `element`/`id` to get `code`) so this isn't lost, without
forcing it through incompletely under time pressure. Not urgent: the live pipeline's ongoing
backfill already covers anyone who becomes currently relevant.

## External stats for other leagues (e.g. incorporating a player's Bundesliga form): investigated, mostly a dead end in this environment
Checked understat.com (connection failed entirely), fbref.com (403 Cloudflare, already
documented as unfixable), football-data.org and api-sports.io (both require paid API keys we
don't have configured -- 403 without auth, not a network block). No genuinely free,
sufficiently detailed, reachable source for cross-league player-level stats (goals/assists/
minutes/xG per player) found in this session's network environment.

**Honest assessment for the future**: if this is worth pursuing, the realistic paths are (a)
a paid API subscription (API-Football or similar) if the user wants to set one up, or (b) a
smaller, more achievable near-term step: incorporate PRICE more directly as a feature in
Layer 2's goal/assist rate model. FPL's own price-setting already reflects market
expectations of a player's quality (including non-PL reputation) that we don't otherwise
use anywhere in the goal/assist rate pipeline -- worth testing as a real, validated addition
before chasing external data sources that may not be accessible. Not implemented this
session; flagged as the more promising next step over external scraping.


## RESOLVED: price signal for MID goal/assist rate -- validated, real improvement, but a clear-eyed one
Followed through on the idea flagged at the end of the previous session (FPL's own pricing
reflects quality signals -- transfer fee, reputation, non-PL form -- the goal/assist rate
model never sees). Tested properly before implementing, same discipline as every other fix
this session.

**Checked whether price adds real incremental signal first**: computed the residual (actual
goals - EWM-predicted goals) and checked its correlation with price, BY POSITION, since
price might matter differently for different roles. Real for MID (0.048), negligible for FWD
(0.006) and DEF (0.007), unstable for GK (goals are too rare a target there to trust a
correlation on). Scoped the fix to MID ONLY on this evidence -- not applied uniformly "for
consistency."

**Backtested a price->rate blend for MID** (leave-one-season-out, same as every other blend
this session): a simple linear fit of price to per-90 rate, blended with the existing EWM
rate. Real, substantial improvement -- LogLoss cut from 0.186 to 0.148 for goals and 0.185 to
0.153 for assists at blend_weight=0.5. Implemented as PRICE_BLEND_WEIGHT_MID=0.5 with fitted
slope/intercept constants in fit_player_involvement.py, applied in add_player_rate_features
(the backtest path) AND predict_upcoming.py (the live path, using each player's LATEST known
price instead of the backtest's previous-match price) -- checked for and fixed the same
live/backtest duplication pattern found three times already this session.

**End-to-end result**: combine_xp.py's overall MAE improved from 1.008 to 0.996 (our vs FPL's
own predictor: 0.982 vs 1.006) -- a bigger, more clear-cut improvement than DefCon or bonus
shrinkage, because MID is the largest position group (~43% of all rows), so a real fix there
moves the aggregate more.

**Checked the actual motivating case directly, and reported it honestly rather than assuming
success**: Wirtz's total xP moved from 8.87 to 8.57 -- LOWER, not higher, moving him slightly
FURTHER from the external tool's estimate, not closer. This is understood, not a bug: his
price already dropped GBP8.5m -> GBP7.5m specifically because the market reacted to his
disappointing 2025-26 season, so his price-implied rate is now BELOW his own EWM rate --
price and his own history already agree he underperformed, so blending two signals that agree
doesn't move his number up. Price is a genuinely independent signal only for players whose own
results HAVEN'T yet caught up with what the market expected (e.g. a brand-new-to-PL summer
signing with zero PL history) -- not for someone who's already played a full season and had
his price adjusted down in response. Verified this distinction holds by checking Haaland (FWD,
correctly unaffected by the MID-only scoping) stayed exactly at his prior value (15.41).

**Honest overall takeaway**: real, validated, worthwhile fix -- and simultaneously confirms the
Wirtz gap versus the external tool remains genuinely unresolved, not fixed by this idea. If
that gap is still worth chasing, the next place to look is probably NOT price (checked, doesn't
support a higher number for him) but something the external tool has access to that we
don't -- likely genuine non-PL underlying data or a different assumption about "still
adapting" recovery, neither of which this project currently has a data source for.


## FINDING (open, not yet fixed): a real, systematic gap vs. the competitor's predictor, confirmed at scale
User provided the competitor's full player-statistics export (500+ players, not just a handful).
Matched 49 players to our own DB and compared directly -- far more statistically robust than the
earlier 8-player spot check.

**Result**: our xP is consistently ~70-75% of theirs, UNIFORMLY across every position (GK mean
ratio 0.72, DEF 0.71, MID 0.72, FWD 0.68 -- not concentrated in any one position). This uniformity
is itself the important clue: a position-specific modeling gap would show up unevenly; a gap this
consistent across positions points to something more systemic.

**Leading hypothesis, with real supporting evidence (not just a guess)**: checked their pMins
(expected minutes over 3 GWs) against our own appearance-certainty proxy for undisputed, near-
certain starters. Real, substantial gap -- most dramatic for goalkeepers: their pMins implies
~98% of a full 90 minutes for Raya and Alisson, ours implies something closer to 70-75% of that
same reliability. Same pattern, smaller magnitude, for outfield certainties (Virgil van Dijk,
James Tarkowski). This is independent, external evidence for something already flagged as an
OPEN item earlier this session (the P(60+) under-confidence for elite/reliable players, previously
concluded to be "substantially but not entirely an artifact" via the price-tier check) -- this
comparison suggests there's more real signal in that gap than that earlier conclusion allowed for.

**Deliberately NOT fixed today**: this needs proper investigation (a fresh look at Layer 3's
P(60+) calibration specifically for high-certainty players, ideally backtested the same way as
every other fix this session), not a rushed patch based on a single external comparison. Flagged
here as the most promising next thing to dig into, connecting back to the still-open Q4 price-tier
finding from earlier.

## DONE: player detail dialog (replaces row-expand-in-place)
Built to match a reference design: header (kit, name, POS/PRICE/TEAM badges, close button), a row
of per-gameweek point cards (color-banded by magnitude, opponent shown via existing fixtures data),
and two panels -- "Historic Stats" (last complete season's real minutes/goals/assists/xG/xA, a
new field) and "Breakdown of Predictions" (the existing component breakdown, reformatted, with a
Total xP footer).

Backend: added a `historic` field to `/api/players` (last-complete-season aggregate from
`player_gameweek_stats`, a separate query since it's a different season/shape than the rest of
the endpoint). New component: `frontend/src/components/PlayerDetailModal.tsx`. PlayerScout.tsx's
row click now opens this dialog instead of expanding inline; the old `GameweekBreakdown` and
`BreakdownPanel` inline components were removed since their content now lives in the dialog.

Note for future sessions: hit a real tooling mistake mid-build -- called the wrong `create_file`
tool (the computer-use sandbox one, not desktop-commander) which silently produced nothing on the
actual Windows machine. Caught it via a failed follow-up edit, not proactively. Worth remembering:
always verify a newly-created file exists via read_file/view before continuing to build on it,
not just trusting a "created successfully" message.

Verified: 41 backend tests + 24 frontend tests passing (4 tests updated to reflect the dialog
replacing the old inline expand). Confirmed live -- historic stats populate correctly (e.g.
Haaland: 2953 mins, 27 goals, 8 assists, 25.5 xG for 2025-26, matching the reference data closely).


## INVESTIGATED FURTHER (user directive): the playing-time under-confidence hypothesis, properly tested
Followed up on the "too low playing time" hypothesis from the external-tool comparison with real
investigation rather than accepting the raw comparison at face value.

**Found a genuine, concrete bug, confirmed directly**: `ewm_play_rate` (recency-weighted play
rate, a core Layer 3 feature) has NO protection against a single benign end-of-season rest, unlike
`last_match_minutes` (which gets `decayed_last_match_signal`'s gap-aware discounting). Confirmed
directly for David Raya: 12/12 real 90-minute appearances, then one 0-minute match on the final,
dead-rubber gameweek of 2025-26 -- his `ewm_play_rate` heading into 2026-27 reads 0.891 despite
true underlying reliability being essentially 1.0. This pattern isn't unique to Raya; end-of-season
squad rotation for dead rubbers is common practice across most clubs, and we are in pre-season
RIGHT NOW, meaning this was actively degrading a meaningful fraction of current live predictions
for established players.

**Investigated whether the aggregate impact matched the external comparison's implied scale --
it did not**, and said so honestly rather than assuming the initial hypothesis was fully right.
Correctly isolating the relevant subgroup (season-boundary rows where the PRE-GAP play rate was
near-perfect -- NOT filtering on `ewm_play_rate` itself, which would circularly exclude the exact
cases under test) showed the real gap is modest: GK-specific calibration was predicted=0.843 vs
actual=0.864 (~2pp), not the ~25-30 point gap the raw appearance-points comparison implied. Most
of that raw comparison's gap must come from elsewhere, still unresolved.

**Fix implemented and validated**: added `ewm_one_earlier` (the play-rate EWM as it stood BEFORE
the single most recent, possibly-boundary-corrupted match) as a companion feature to
`ewm_play_rate`, computed identically in both `add_features` (backtest/training) and
`current_state_features` (live) to avoid the train/inference mismatch pattern that's bitten this
project multiple times already. Backtested honestly: closes roughly a quarter of the real
GK-specific gap (0.843 -> 0.850), zero measurable cost to overall LogLoss/Brier or the full
combine_xp.py backtest MAE (0.996 -> 0.997, noise-level). Retrained (model_run_id=64/66), 41
backend tests still passing.

**Tested and explicitly REJECTED a follow-up idea**: hypothesized `games_since_last` (consecutive
zero-minute match count) has the same season-boundary blind spot, since Raya's live `p_played`
was still only 0.71 even after the `ewm_one_earlier` fix. Tested a corresponding adjustment
(zeroing a count of 1 when immediately followed by a long gap) via the same backtest -- it did NOT
improve GK calibration (0.8505 -> 0.8499, a wash). Did not ship this; a plausible-sounding
hypothesis that fails honest testing gets dropped, not forced through.

**What remains genuinely open**: Raya's own live `p_played` is still only ~0.71 despite
`ewm_one_earlier` correctly reading ~1.0 for him -- the model still isn't using that signal
strongly enough for his specific combination of feature values, and the `games_since_last` idea
that seemed like the obvious next culprit didn't pan out. The classifier's own probability ceiling
(found earlier: max achievable p_played across the whole dataset is ~97%, only modestly raised by
more boosting capacity) is a more likely remaining structural constraint than any single feature
fix. Also unresolved: this narrow fix does not explain the bulk of the earlier-found ~70-75%
aggregate xP ratio gap vs. the external tool -- that gap's primary driver(s) remain unidentified.
Next step, if pursued: a systematic per-feature calibration audit of the P(plays) classifier
specifically for the highest-price/most-reliable player subgroup, rather than another single-
feature guess.


## SYSTEMATIC AUDIT COMPLETED: Layer 3 minutes calibration is NOT the source of the aggregate gap
Followed through on the proposed next step from the previous investigation -- a proper, per-
component calibration audit by price quartile and position, rather than continuing to guess one
feature at a time.

**Method**: full leave-one-season-out backtest, out-of-fold predictions for all three Layer 3
components (P(plays), E[minutes|played], P(60+|played)) plus the combined expected_minutes,
checked against REAL outcomes, broken out by price quartile within each position.

**Result -- clean across the board**:
- P(plays): essentially perfect calibration everywhere, all diffs within +-1.4pp (noise-level),
  no price-related or position-related pattern.
- E[minutes|played]: biases under 2 minutes in every quartile.
- P(60+|played): a small, real, POSITION-specific bias for GK (~-2pp consistently across all
  price quartiles -- not price-related) and a smaller one for DEF (~-0.7pp). Already partially
  addressed by the earlier ewm_one_earlier fix. Too small to explain a large gap.
- Combined expected_minutes: for every quartile with meaningful minutes, predicted/actual ratio
  is between 0.98 and 1.02 -- essentially perfect. The only quartiles showing a larger ratio
  deviation (GK Q1 ~1.17, FWD Q1 ~1.21) are the "barely plays at all" fringe buckets where the
  absolute minutes base is tiny (2-3 minutes), so the ratio is not meaningful in points terms.

**Conclusion**: Layer 3 (playing time) is NOT the primary driver of the ~70-75% aggregate xP
ratio gap found against the external tool. This, combined with what was already established
this session -- the rate components (goals/assists/clean sheets/DefCon/bonus) also showed only
small 1-2% biases when checked via the same rigorous backtest discipline, and the full combined
model already beats FPL's own official predictor on MAE against real outcomes (0.982 vs 1.006) --
means our model's calibration against REAL RESULTS is good throughout, not just in the one place
checked today.

**This changes the shape of the open question**: the evidence increasingly points toward the gap
being explained by the EXTERNAL TOOL'S calibration, not ours -- i.e., it may be the other tool
running more optimistic than warranted, rather than us running too conservative. We have no direct
visibility into whether the external tool's own numbers are validated against real outcomes the
way every component of our own pipeline has now been checked. This isn't proven (we can't audit
their model), but it is the more likely explanation given everything found so far: every place we
looked in our own pipeline was well-calibrated against reality, and public FPL tools in general
have no particular incentive toward conservative, rigorously-backtested numbers (excitement/
engagement is a more natural default than caution for that kind of product).

**Recommendation going forward**: stop treating "make our numbers bigger to match theirs" as the
implicit goal. Our numbers being backtested and calibrated against 5 seasons of real results is a
real strength, not a gap to close. If this is revisited, the productive next step is not another
single-feature hunt inside our own pipeline, but either (a) accepting the difference as a genuine,
defensible difference in modeling philosophy, or (b) trying to find out concretely how the
external tool computes ITS numbers (if that's ever discoverable) before assuming it's more
"correct" than a rigorously validated alternative.


## RESOLVED (user was right to push back): a real transfer-specific blind spot in Layer 3
User disagreed with the "our minutes calibration is fine" conclusion, specifically trusting the
external tool's minutes more than ours. Rather than defending the prior conclusion or just
agreeing, tested the most concrete, mechanistic hypothesis that could explain a genuine
disagreement: every Layer 3 EWM feature is built from a player's OWN historical rows, which for
a summer transfer reflect their OLD club's context (competition for their position, tactical fit,
manager trust) -- info that doesn't carry over, while the new club's transfer fee/role is a
genuinely new signal the historical-EWM features can't see at all.

**Confirmed directly via backtest** (comparing rows where a player's team differs from their
previous match's team, vs. rows where it doesn't): non-transfer rows show essentially zero bias
in aggregate (p_played diff +0.001, expected_minutes diff +0.03) -- but transfer rows show a
REAL bias: p_played under-predicted by ~3.2pp, expected_minutes under-predicted by ~2 minutes.
Only ~0.87% of all historical rows, but this is exactly the situation concentrated hardest at
THIS moment -- pre-season, when every summer transfer hits it simultaneously, which is likely a
real contributor to the live discrepancy the user noticed.

**Fix implemented and validated**: added `is_transfer` as an explicit feature (current team,
from `players.current_team_id`, differs from the team of the player's last recorded match),
with sample-weighting during training (same rationale as the existing season-boundary weighting
-- too rare a pattern for the loss function to prioritize on its own). Computed identically in
`add_features` (backtest) and `current_state_features` (live) -- for live use specifically, had
to source "current team" from `players.current_team_id` rather than the historical rows
themselves, since a fresh signing may have zero match rows yet for their new club.

**Backtested honestly, and it's a real, substantial improvement**: transfer-row p_played bias
closed from -3.2pp to -1.2pp (roughly 60% closed); expected_minutes bias closed from -2.06 to
-0.96 minutes (roughly 53% closed). Non-transfer calibration stayed excellent and essentially
unchanged. Full combine_xp.py backtest MAE unchanged at noise-level (0.999, still comfortably
ahead of FPL's own 1.006). Retrained (model_run_id=67/69), 41 backend tests still passing.

**Verified on the exact kind of case this was meant to fix**: Florian Wirtz (Bayer Leverkusen ->
Liverpool this summer) moved from xP=8.57 to xP=9.13 for GW1-3, with appearance_pts specifically
rising from a below-average certainty level to ~1.48/2.0 per game -- a genuine, mechanistically
understood improvement, not a coincidental number shift.

**Honest scope of this fix**: this closes roughly half of a real, validated, transfer-specific
gap -- it is not a complete fix (the remaining ~40-47% of the transfer-specific bias is still
open), and transfers are still a small fraction of all rows even though they're concentrated
heavily right now. This does not by itself fully explain the earlier ~70-75% aggregate xP ratio
gap against the external tool, but it's a genuine, mechanistically-motivated, validated piece of
that puzzle that the earlier "well-calibrated" conclusion had missed by not specifically checking
for it -- the user's pushback here was warranted and led to a real fix, not just a reassurance.
