"""
Layer 2 -- player involvement model (see docs/model-architecture.md).

Splits a team's fixture-specific expected goals (Layer 1) into individual player
scoring/assisting probability, using each player's recency-weighted xG/xA-per-90
rate (their "share" of the team's attacking output), scaled by how much stronger
or weaker this particular fixture is versus that team's average fixture.

Expected minutes now comes from the Layer 3 hurdle model (fit_minutes_model.py),
trained leave-one-season-out to avoid leakage -- this replaces the old placeholder
(each player's own unconditional average minutes) used in earlier versions of
this script.

No lookahead: every player's rate at fixture t is computed using only their
matches strictly before t (shifted EWMA).
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import fit_minutes_model as l3

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
HALFLIFE_MATCHES = 24  # recency weighting for player rate features -- was 8, changed after
                         # a real backtest (found via user question re: Haaland's expected
                         # goals over 5 GWs looking low -- see docs/GOTCHAS.md). halflife=8
                         # made sense for playing-time features (genuinely changes fast with
                         # rotation/injury) but was too short for GOAL/ASSIST rate specifically,
                         # a more stable attribute -- his 5-season career average (0.772/90)
                         # and even last-2-seasons average (0.750/90) were both well above the
                         # halflife=8 estimate (0.654/90). Backtested Brier/LogLoss on real
                         # scoring/assisting outcomes across [4,8,12,16,24,38]: both goals and
                         # assists were minimized (or tied-best) at halflife=24, not 8.
ALL_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

# See add_player_rate_features's docstring -- backtested via a dedicated blend-weight
# sweep (not assumed): 0.6 minimizes Brier/LogLoss for both goals and assists. The
# calibration multipliers correct the remaining aggregate gap AT that blend weight
# (actual_total / predicted_total from the same backtest), so relative ranking (the
# blend's job) and absolute level (the multiplier's job) are each fit for what they're
# actually good at, rather than compromising both with one knob.
BLEND_WEIGHT_GOAL = 0.6
BLEND_WEIGHT_ASSIST = 0.6
CALIBRATION_MULTIPLIER_GOAL = 5357 / 4601      # 1.164
CALIBRATION_MULTIPLIER_ASSIST = 4847 / 3510    # 1.381

# PRICE SIGNAL (added via user-prompted iteration -- see docs/GOTCHAS.md): FPL's
# own pricing reflects market expectations of quality (transfer fee, reputation,
# non-PL form) that the EWM rate above never sees. Checked properly before
# assuming this would help: residual correlation (does price explain scoring the
# player's OWN history-based rate is missing) was real for MID (0.048) but
# negligible for FWD (0.006), DEF (0.007), and unstable/noisy for GK (goals are
# too rare a target there to trust a correlation) -- so this is MID-ONLY,
# deliberately not applied elsewhere. Backtested (leave-one-season-out): a
# simple linear price->rate fit, blended with the EWM rate, cut LogLoss from
# 0.186 to 0.148 for goals and 0.185 to 0.153 for assists at blend_weight=0.5 --
# a substantial, validated improvement in aggregate.
# IMPORTANT CAVEAT, checked directly (not assumed): this does NOT help every
# individual player -- for someone whose PRICE HAS ALREADY DROPPED to reflect a
# disappointing season (e.g. Wirtz: GBP8.5m -> GBP7.5m after an underwhelming
# 2025-26), the price-implied rate is LOWER than his own EWM rate, not higher --
# price and history already agree he underperformed, so blending doesn't lift
# him. This is correct behavior, not a bug: it just means price is a genuinely
# independent signal only until a player's own results have caught up with (or
# fallen short of) what the market expected.
PRICE_BLEND_WEIGHT_MID = 0.5
PRICE_SLOPE_GOAL_MID, PRICE_INTERCEPT_GOAL_MID = 0.03704, -0.07756
PRICE_SLOPE_ASSIST_MID, PRICE_INTERCEPT_ASSIST_MID = 0.03555, -0.08955


def compute_layer3_expected_minutes(conn) -> pd.DataFrame:
    """Leave-one-season-out expected minutes per (player_id, fixture_id), using
    the Layer 3 hurdle model -- trained on the OTHER 4 seasons each time, same
    walk-forward discipline used everywhere else, so this evaluation is honest."""
    m_df = l3.load_data(conn)
    m_df = l3.add_features(m_df)

    pieces = []
    for holdout in ALL_SEASONS:
        train_df = m_df[m_df["season_id"] != holdout]
        test_df = m_df[m_df["season_id"] == holdout].copy()
        r = l3.train_and_eval(train_df, test_df)
        p_played = r["clf"].predict_proba(test_df[l3.FEATURE_COLUMNS])[:, 1]
        e_minutes = r["reg"].predict(test_df[l3.FEATURE_COLUMNS])
        p_60plus_given_played = r["clf60"].predict_proba(test_df[l3.FEATURE_COLUMNS])[:, 1]
        test_df["layer3_expected_minutes"] = np.clip(p_played * e_minutes, 0, 95)
        test_df["layer3_p_played"] = p_played
        test_df["layer3_p_60plus_given_played"] = p_60plus_given_played
        pieces.append(test_df[["player_id", "fixture_id", "layer3_expected_minutes",
                                "layer3_p_played", "layer3_p_60plus_given_played"]])

    return pd.concat(pieces, ignore_index=True)


def load_data(conn):
    df = pd.read_sql_query(
        """SELECT pgs.player_id, p.name, p.position, pgs.season_id, pgs.gw, pgs.fixture_id,
                  pgs.minutes, pgs.goals, pgs.assists, pgs.xg, pgs.xa, pgs.was_home, pgs.price_at_time,
                  f.kickoff_time, f.home_team_id, f.away_team_id,
                  th.name AS home_team, ta.name AS away_team
           FROM player_gameweek_stats pgs
           JOIN players p ON pgs.player_id = p.player_id
           JOIN fixtures f ON pgs.fixture_id = f.fixture_id
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
           WHERE p.position IN ('GK','DEF','MID','FWD')""",
        conn,
    )
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    df["team"] = np.where(df["was_home"] == 1, df["home_team"], df["away_team"])
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def load_dixon_coles_params(conn):
    run_id = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='dixon_coles' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()[0]
    weights = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id=?", (run_id,)
    ).fetchall())
    strength = pd.read_sql_query(
        "SELECT team_name, attack, defence FROM team_strength WHERE run_id=?", conn, params=(run_id,)
    ).set_index("team_name")
    return weights["mu"], weights["home_adv"], strength


def add_player_rate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Shifted EWMA rates per player -- uses only matches strictly before the
    current one, so there's no lookahead into the match being predicted.

    RULE FIX (found via backtest_report.py's component-level calibration check
    -- see docs/GOTCHAS.md): pure xG/xA (the old `xg.fillna(goals)` pattern)
    systematically undershoots real output -- xG undershoots actual goals by
    -23.5% in aggregate, xA undershoots actual assists by -46.6%, a real,
    well-known property of these metrics (good finishers/passers consistently
    outperform the pre-shot/pre-pass "quality" estimate), not a bug in our
    data. Since xg/xa have ~100% coverage from 2022-23 onward, the old fillna
    fallback almost never triggered, so the model trained on an almost-pure
    signal that structurally undershoots reality -- this propagated straight
    into the final xP numbers, hitting star players hardest (they're the ones
    actually scoring/assisting above their underlying chance quality).

    Two-stage fix, backtested rather than assumed: BLEND_WEIGHT=0.6 for the
    per-match rate (minimizes Brier/LogLoss -- i.e. best for "will this
    specific player score/assist this match", tested across [0.0, 1.0] in
    0.1-1 steps) plus a separate CALIBRATION_MULTIPLIER (also backtested) that
    corrects the aggregate level without touching the relative ranking the
    blend already gets right."""
    df = df.copy()
    df["quality_goal_signal"] = BLEND_WEIGHT_GOAL * df["xg"] + (1 - BLEND_WEIGHT_GOAL) * df["goals"]
    df["quality_assist_signal"] = BLEND_WEIGHT_ASSIST * df["xa"] + (1 - BLEND_WEIGHT_ASSIST) * df["assists"]

    def shifted_ewm_rate(group, signal_col):
        signal_shifted = group[signal_col].shift(1)
        minutes_shifted = group["minutes"].shift(1)
        ewm_signal = signal_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        ewm_minutes = minutes_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        return ewm_signal / (ewm_minutes / 90).replace(0, np.nan)

    grouped = df.groupby("player_id", group_keys=False)
    df["goal_rate_per90"] = grouped.apply(lambda g: shifted_ewm_rate(g, "quality_goal_signal")).values * CALIBRATION_MULTIPLIER_GOAL
    df["assist_rate_per90"] = grouped.apply(lambda g: shifted_ewm_rate(g, "quality_assist_signal")).values * CALIBRATION_MULTIPLIER_ASSIST

    # PRICE BLEND, MID only -- see PRICE_BLEND_WEIGHT_MID's docstring above for
    # why it's scoped this way. price_shifted uses the PREVIOUS match's price
    # (shift(1)), same walk-forward discipline as the EWM rates -- no lookahead.
    if "price_at_time" in df.columns:
        df["price_shifted"] = grouped["price_at_time"].shift(1).values
        pos_avg_price = df.groupby("position")["price_shifted"].transform("mean")
        df["price_shifted"] = df["price_shifted"].fillna(pos_avg_price)
        mid_mask = df["position"] == "MID"
        price_rate_goal = (PRICE_SLOPE_GOAL_MID * df["price_shifted"] + PRICE_INTERCEPT_GOAL_MID).clip(lower=0)
        price_rate_assist = (PRICE_SLOPE_ASSIST_MID * df["price_shifted"] + PRICE_INTERCEPT_ASSIST_MID).clip(lower=0)
        df.loc[mid_mask, "goal_rate_per90"] = (
            PRICE_BLEND_WEIGHT_MID * df.loc[mid_mask, "goal_rate_per90"]
            + (1 - PRICE_BLEND_WEIGHT_MID) * price_rate_goal[mid_mask]
        )
        df.loc[mid_mask, "assist_rate_per90"] = (
            PRICE_BLEND_WEIGHT_MID * df.loc[mid_mask, "assist_rate_per90"]
            + (1 - PRICE_BLEND_WEIGHT_MID) * price_rate_assist[mid_mask]
        )

    # Shrinkage: small-sample / early-career players fall back toward position average
    pos_avg_goal = df.groupby("position")["goal_rate_per90"].transform("mean")
    pos_avg_assist = df.groupby("position")["assist_rate_per90"].transform("mean")
    df["goal_rate_per90"] = df["goal_rate_per90"].fillna(pos_avg_goal)
    df["assist_rate_per90"] = df["assist_rate_per90"].fillna(pos_avg_assist)
    return df


def add_fixture_adjustment(df: pd.DataFrame, mu, home_adv, strength) -> pd.DataFrame:
    """How much stronger/weaker this fixture is vs. this team's average fixture,
    from the Layer 1 Dixon-Coles fit -- used to scale player rates up/down.
    Vectorized (see docs/GOTCHAS.md perf note) -- was .apply(axis=1) over the
    full 138k-row dataset, same anti-pattern fixed in combine_xp.py."""
    league_avg = 0.0
    was_home = df["was_home"].to_numpy().astype(bool)
    opponent = np.where(was_home, df["away_team"], df["home_team"])

    team_attack = df["team"].map(lambda t: strength["attack"].get(t, league_avg)).to_numpy()
    opp_defence = pd.Series(opponent).map(lambda t: strength["defence"].get(t, league_avg)).to_numpy()
    adv = np.where(was_home, home_adv, 0.0)

    df["fixture_lambda"] = np.exp(mu + team_attack + opp_defence + adv)
    df["team_avg_lambda"] = np.exp(mu + team_attack + home_adv / 2)
    df["fixture_adjustment"] = df["fixture_lambda"] / df["team_avg_lambda"]
    return df


def compute_player_expected_goals(df: pd.DataFrame) -> pd.DataFrame:
    df["player_lambda_goal"] = (
        df["goal_rate_per90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]
    )
    df["player_lambda_assist"] = (
        df["assist_rate_per90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]
    )
    df["p_score"] = 1 - np.exp(-df["player_lambda_goal"].clip(lower=0))
    df["p_assist"] = 1 - np.exp(-df["player_lambda_assist"].clip(lower=0))
    return df


def brier_and_logloss(p, actual):
    p = np.clip(p, 1e-10, 1 - 1e-10)
    actual = actual.astype(float)
    brier = np.mean((p - actual) ** 2)
    logloss = -np.mean(actual * np.log(p) + (1 - actual) * np.log(1 - p))
    return brier, logloss


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    mu, home_adv, strength = load_dixon_coles_params(conn)
    df = load_data(conn)
    df = add_player_rate_features(df)

    print("Computing Layer 3 expected minutes (leave-one-season-out)...")
    l3_minutes = compute_layer3_expected_minutes(conn)
    df = df.merge(l3_minutes, on=["player_id", "fixture_id"], how="left")
    df["expected_minutes"] = df["layer3_expected_minutes"].fillna(0)

    df = add_fixture_adjustment(df, mu, home_adv, strength)
    df = compute_player_expected_goals(df)

    # Only evaluate rows with a real prior-history-based rate (min_periods handled NaNs already)
    valid = df.dropna(subset=["p_score", "p_assist"])
    actual_scored = (valid["goals"] > 0).astype(int)
    actual_assisted = (valid["assists"] > 0).astype(int)

    # Naive baseline: fixture_adjustment forced to 1.0 (no fixture-specific scaling),
    # still using the NEW Layer 3 minutes -- isolates the fixture-adjustment effect specifically
    naive_p_score = 1 - np.exp(-(valid["goal_rate_per90"] * (valid["expected_minutes"] / 90)).clip(lower=0))

    brier_fx, ll_fx = brier_and_logloss(valid["p_score"].values, actual_scored.values)
    brier_naive, ll_naive = brier_and_logloss(naive_p_score.values, actual_scored.values)
    brier_a, ll_a = brier_and_logloss(valid["p_assist"].values, actual_assisted.values)

    print(f"Rows evaluated: {len(valid)}")
    print(f"\nGoal-scoring probability:")
    print(f"  fixture-adjusted -- Brier: {brier_fx:.4f}  LogLoss: {ll_fx:.4f}")
    print(f"  naive (no fixture adj) -- Brier: {brier_naive:.4f}  LogLoss: {ll_naive:.4f}")
    print(f"\nAssist probability (fixture-adjusted) -- Brier: {brier_a:.4f}  LogLoss: {ll_a:.4f}")

    print("\nSample: top 10 predicted scoring probabilities for the most recent gameweek")
    latest = df[df["kickoff_time"] == df["kickoff_time"].max()]
    print(latest.nlargest(10, "p_score")[["name", "team", "p_score", "p_assist", "expected_minutes"]]
          .to_string(index=False))

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "PLAYER", "player_involvement_ewm",
         f"halflife_matches={HALFLIFE_MATCHES}, brier_fixture_adj={brier_fx:.4f}, brier_naive={brier_naive:.4f}, "
         f"logloss_fixture_adj={ll_fx:.4f}, logloss_naive={ll_naive:.4f}, brier_assist={brier_a:.4f}"),
    )
    run_id = cur.lastrowid
    cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                (run_id, "halflife_matches", float(HALFLIFE_MATCHES), "GLOBAL"))
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()
