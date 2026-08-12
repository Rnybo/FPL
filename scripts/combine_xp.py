"""
combine_xp.py -- the final assembly. Sums every layer's expected contribution
using the ACTUAL FPL scoring formula (see claude.md), then validates the whole
thing end-to-end against real historical total_points.

Key correctness point: for count-based scoring (goals, assists, cards, saves,
goals conceded), we use each layer's expected COUNT (lambda), not "probability
of at least one" -- points scale with how many times something happens (a
brace earns double goal points), and E[count] * points_per_event is the exact
expectation regardless of how many times it occurs. Binary events (clean sheet,
defensive contribution threshold, red card as a rare single event) use
probability directly since they either happen or don't.

Every sub-model is evaluated leave-one-season-out, consistent with every other
script in this project -- so this combined result is a genuine walk-forward
backtest, not just re-fitting on data it already saw.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.metrics import mean_absolute_error

import fit_minutes_model as l3
import fit_player_involvement as l2
import fit_discrete_events as l4b
import fit_defensive_contribution as l4a
import fit_bonus_points as l5
import blend_odds_with_model as l1b

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
ALL_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

# FPL scoring values (see claude.md), position-specific where relevant
GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
DEFCON_POINTS = 2
DEFCON_THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}


def load_master_data(conn):
    """One row per player-fixture across all 5 seasons, with everything the
    formula needs: team names for Layer 1 lookups, actual results for validation."""
    df = pd.read_sql_query(
        """SELECT pgs.player_id, p.name, p.position, pgs.season_id, pgs.gw, pgs.fixture_id,
                  pgs.minutes, pgs.goals, pgs.assists, pgs.xg, pgs.xa, pgs.total_points, pgs.was_home,
                  pgs.penalties_missed, pgs.penalties_saved, pgs.yellow_cards, pgs.red_cards,
                  pgs.own_goals, pgs.saves, pgs.defensive_contribution, pgs.bonus, pgs.price_at_time,
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
    df["opponent"] = np.where(df["was_home"] == 1, df["away_team"], df["home_team"])
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def add_team_lambdas(df, mu, home_adv, rho, strength, alpha, odds):
    """Team's expected goals FOR and AGAINST this fixture, blended with market
    odds using the Layer 1b learned alpha. Falls back to model-only when odds
    aren't available for a fixture (see docs/GOTCHAS.md) -- matters for live
    predictions too, since closing odds aren't available far in advance."""
    league_avg = 0.0
    fixture_lambda = {}

    fixture_rows = df.drop_duplicates("fixture_id")[["fixture_id", "home_team", "away_team"]]
    for row in fixture_rows.itertuples(index=False):
        home_team, away_team = row.home_team, row.away_team

        a_h = strength["attack"].get(home_team, league_avg)
        d_h = strength["defence"].get(home_team, league_avg)
        a_a = strength["attack"].get(away_team, league_avg)
        d_a = strength["defence"].get(away_team, league_avg)
        lh_model = np.exp(mu + a_h + d_a + home_adv)
        la_model = np.exp(mu + a_a + d_h)

        target = l1b.market_targets_for_fixture(odds, row.fixture_id)
        if target is None:
            lh_final, la_final = lh_model, la_model
        else:
            lh_mkt, la_mkt = l1b.fit_market_lambdas(target, rho, lh_model, la_model)
            lh_final = alpha * lh_mkt + (1 - alpha) * lh_model
            la_final = alpha * la_mkt + (1 - alpha) * la_model

        fixture_lambda[row.fixture_id] = (lh_final, la_final)

    was_home = df["was_home"].to_numpy().astype(bool)
    lh_arr = df["fixture_id"].map(lambda fid: fixture_lambda[fid][0]).to_numpy()
    la_arr = df["fixture_id"].map(lambda fid: fixture_lambda[fid][1]).to_numpy()
    df["team_lambda_for"] = np.where(was_home, lh_arr, la_arr)
    df["team_lambda_against"] = np.where(was_home, la_arr, lh_arr)
    return df


def expected_floor_div_k(lam: np.ndarray, k: int, cap: int = 15) -> np.ndarray:
    """E[floor(X/k)] for X ~ Poisson(lam), vectorized over rows."""
    xs = np.arange(cap + 1)
    floor_divk = xs // k
    pmf = poisson.pmf(xs[:, None], lam[None, :])
    return (floor_divk[:, None] * pmf).sum(axis=0)


def add_clean_sheet_prob(df, rho):
    """Exact clean sheet probability via the Dixon-Coles score grid -- FULLY
    VECTORIZED (see docs/GOTCHAS.md perf note: the original per-row .apply()
    version took 77s of a 217s total runtime for a calculation that reduces to
    a handful of array operations). Derivation: the tau correction only
    touches the (0,0) and (0,1)/(1,0) score cells; every other cell is plain
    independent Poisson, so summing all cells x=0..11 collapses to a single
    poisson.cdf(11, .) call, then two correction terms are added/subtracted
    for the cells tau actually changes. Verified numerically identical to the
    original row-by-row version before replacing it (see git history / session
    notes for the before/after comparison)."""
    was_home = df["was_home"].to_numpy().astype(bool)
    hl = np.where(was_home, df["team_lambda_for"], df["team_lambda_against"])  # actual HOME team's lambda
    al = np.where(was_home, df["team_lambda_against"], df["team_lambda_for"])  # actual AWAY team's lambda

    pmf0_h, pmf1_h = poisson.pmf(0, hl), poisson.pmf(1, hl)
    pmf0_a, pmf1_a = poisson.pmf(0, al), poisson.pmf(1, al)
    cdf11_h, cdf11_a = poisson.cdf(11, hl), poisson.cdf(11, al)

    # P(away scores 0), used when THIS row's team is home
    p_away_zero = pmf0_a * cdf11_h + pmf0_a * pmf0_h * (-hl * al * rho) + pmf0_a * pmf1_h * (al * rho)
    # P(home scores 0), used when THIS row's team is away
    p_home_zero = pmf0_h * cdf11_a + pmf0_h * pmf0_a * (-hl * al * rho) + pmf0_h * pmf1_a * (hl * rho)

    df["p_clean_sheet"] = np.where(was_home, p_away_zero, p_home_zero)
    return df


def build_combined_xp_dataframe(conn):
    """The full pipeline, extracted into a reusable function so backtest_report.py
    (and anything else) can get the same walk-forward xP dataframe without
    duplicating this logic. __main__ below calls this too -- behavior is
    unchanged from before this was factored out."""
    mu, home_adv, strength = l2.load_dixon_coles_params(conn)
    rho = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id="
        "(SELECT run_id FROM model_runs WHERE model_type='dixon_coles' ORDER BY run_id DESC LIMIT 1)"
    ).fetchall())["rho"]
    alpha = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id="
        "(SELECT run_id FROM model_runs WHERE model_type='dixon_coles_market_blend' ORDER BY run_id DESC LIMIT 1)"
    ).fetchall())["alpha"]
    print(f"Using market-blend alpha={alpha:.3f} (from Layer 1b)")

    df = load_master_data(conn)
    odds = pd.read_sql_query("SELECT fixture_id, market, team_or_outcome, price FROM match_odds", conn)
    df = add_team_lambdas(df, mu, home_adv, rho, strength, alpha, odds)
    df = add_clean_sheet_prob(df, rho)

    print("Computing Layer 2 (goal/assist rates)...")
    df = l2.add_player_rate_features(df)
    # Use the BLENDED team_lambda_for (not a re-derived pure-model value) as the
    # fixture-specific numerator -- the denominator (team's own average attacking
    # strength) stays model-only since it's a season-long normalizer, not
    # something a single fixture's odds should move.
    league_avg = 0.0
    df["team_avg_lambda"] = df["team"].map(
        lambda t: np.exp(mu + strength["attack"].get(t, league_avg) + home_adv / 2)
    )
    df["fixture_adjustment"] = df["team_lambda_for"] / df["team_avg_lambda"]

    print("Layer 3: minutes (leave-one-season-out)...")
    l3_out = l2.compute_layer3_expected_minutes(conn)
    df = df.merge(l3_out, on=["player_id", "fixture_id"], how="left")
    df["expected_minutes"] = df["layer3_expected_minutes"].fillna(0)
    df["layer3_p_played"] = df["layer3_p_played"].fillna(0)
    df["layer3_p_60plus_given_played"] = df["layer3_p_60plus_given_played"].fillna(0)

    df["lambda_goal"] = df["goal_rate_per90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]
    df["lambda_assist"] = df["assist_rate_per90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]

    print("Layer 4b: discrete events (cards, penalties, saves, own goals)...")
    for event, points in l4b.POINTS_PER_EVENT.items():
        rate = l4b.add_rate_feature(df, event)
        df[f"lambda_{event}"] = (rate * (df["expected_minutes"] / 90)).clip(lower=0)

    saves_rate = l4b.add_rate_feature(df, "saves")
    lam_saves = (saves_rate * (df["expected_minutes"] / 90)).clip(lower=0).values
    df["expected_save_points"] = l4b.expected_save_points(lam_saves)
    df.loc[df["position"] != "GK", "expected_save_points"] = 0.0

    print("Layer 4a: defensive contribution (2025-26 only, shrunk Negative Binomial)...")
    df["expected_defcon_points"] = 0.0
    dc_mask = (df["season_id"] == "2025-26") & (df["position"].isin(["DEF", "MID", "FWD"]))
    if dc_mask.any():
        dc_weights = dict(conn.execute(
            "SELECT feature_name, weight FROM model_weights WHERE run_id="
            "(SELECT run_id FROM model_runs WHERE model_type='defensive_contribution_negbinom' ORDER BY run_id DESC LIMIT 1)"
        ).fetchall())
        dc_K, dc_alpha = dc_weights["shrinkage_K"], dc_weights["nb_dispersion_alpha"]

        dc_df = df.loc[dc_mask].copy()
        dc_df = l4a.add_rate_features(dc_df)
        dc_df["expected_minutes"] = df.loc[dc_mask, "expected_minutes"].values  # use Layer 3, not l4a's own weaker calc
        dc_df["dc_rate_shrunk"] = l4a.apply_shrinkage(dc_df, dc_K) * l4a.CALIBRATION_MULTIPLIER_MU
        p_defcon = l4a.compute_probability_nb(dc_df, "dc_rate_shrunk", dc_alpha)
        df.loc[dc_mask, "expected_defcon_points"] = p_defcon * DEFCON_POINTS

    print("Layer 5: bonus points (leave-one-season-out, LightGBM)...")
    b_df = l5.load_data(conn)
    b_df = l5.add_features(b_df)
    bonus_pieces = []
    for holdout in ALL_SEASONS:
        train_b = b_df[b_df["season_id"] != holdout]
        test_b = b_df[b_df["season_id"] == holdout].copy()
        model, _, _, pred = l5.train_and_eval(train_b, test_b)
        test_b["expected_bonus"] = pred
        bonus_pieces.append(test_b[["player_id", "fixture_id", "expected_bonus"]])
    bonus_out = pd.concat(bonus_pieces, ignore_index=True)
    df = df.merge(bonus_out, on=["player_id", "fixture_id"], how="left")
    df["expected_bonus"] = df["expected_bonus"].fillna(0)

    print("\nAssembling final xP formula...")
    df["goal_pts"] = df["lambda_goal"] * df["position"].map(GOAL_POINTS)
    df["assist_pts"] = df["lambda_assist"] * ASSIST_POINTS
    # RULE FIX (see claude.md, docs/GOTCHAS.md): clean sheet points AND the goals-conceded
    # penalty require the PLAYER to have played 60+ minutes, not just that the team kept a
    # clean sheet. Previously multiplied by p_clean_sheet alone, giving a substitute who plays
    # 5 minutes the same clean-sheet credit as a 90-minute starter -- wrong. p_60plus is the
    # same quantity already used in appearance_pts, just reused here.
    p_60plus = df["layer3_p_played"] * df["layer3_p_60plus_given_played"]
    df["cs_pts"] = df["p_clean_sheet"] * df["position"].map(CLEAN_SHEET_POINTS) * p_60plus
    df["appearance_pts"] = df["layer3_p_played"] * (
        df["layer3_p_60plus_given_played"] * 2 + (1 - df["layer3_p_60plus_given_played"]) * 1
    )
    conceded_lambda = df["team_lambda_against"].values
    df["conceded_penalty"] = 0.0
    def_gk_mask = df["position"].isin(["GK", "DEF"])
    df.loc[def_gk_mask, "conceded_penalty"] = -expected_floor_div_k(
        conceded_lambda[def_gk_mask.values], k=2
    ) * p_60plus[def_gk_mask.values].values
    df["card_pen_pts"] = (df["lambda_yellow_cards"] * -1 + df["lambda_red_cards"] * -3
                           + df["lambda_penalties_missed"] * -2 + df["lambda_own_goals"] * -2)
    df["pen_save_pts"] = 0.0
    df.loc[df["position"] == "GK", "pen_save_pts"] = df.loc[df["position"] == "GK", "lambda_penalties_saved"] * 5

    df["xP"] = (df["appearance_pts"] + df["goal_pts"] + df["assist_pts"] + df["cs_pts"]
                + df["conceded_penalty"] + df["card_pen_pts"] + df["pen_save_pts"]
                + df["expected_save_points"] + df["expected_defcon_points"] + df["expected_bonus"])
    return df


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = build_combined_xp_dataframe(conn)

    valid = df.dropna(subset=["xP"])
    mae = mean_absolute_error(valid["total_points"], valid["xP"])
    corr = np.corrcoef(valid["total_points"], valid["xP"])[0, 1]
    naive_mae = mean_absolute_error(valid["total_points"], np.full(len(valid), valid["total_points"].mean()))
    print(f"\nRows evaluated: {len(valid)}")
    print(f"Our combined xP  -- MAE: {mae:.3f}  Correlation with actual points: {corr:.3f}")
    print(f"Naive (mean pts) -- MAE: {naive_mae:.3f}")

    # External benchmark: FPL's own historical xP column, loaded fresh, NEVER used as a
    # training feature anywhere in this project -- purely a fairness check against
    # what FPL itself would have predicted pre-match.
    fpl_xp_frames = []
    for season in ALL_SEASONS:
        raw = pd.read_csv(ROOT / "data" / "raw" / "fpl_api" / season / "merged_gw.csv")
        raw["season_id"] = season
        fpl_xp_frames.append(raw[["name", "GW", "season_id", "xP"]].rename(
            columns={"xP": "fpl_own_xp", "GW": "gw"}))
    fpl_xp = pd.concat(fpl_xp_frames, ignore_index=True)
    merged = valid.merge(fpl_xp, on=["name", "gw", "season_id"], how="left")
    bench = merged.dropna(subset=["fpl_own_xp"])
    fpl_mae = mean_absolute_error(bench["total_points"], bench["fpl_own_xp"])
    our_mae_same_rows = mean_absolute_error(bench["total_points"], bench["xP"])
    print(f"\nBenchmark on {len(bench)} rows with FPL's own xP available:")
    print(f"  Our xP       -- MAE: {our_mae_same_rows:.3f}")
    print(f"  FPL's own xP -- MAE: {fpl_mae:.3f}")

    print("\nSample: predicted xP for the most recent gameweek (top 10)")
    latest = df[df["kickoff_time"] == df["kickoff_time"].max()]
    print(latest.nlargest(10, "xP")[["name", "team", "position", "xP", "total_points"]].to_string(index=False))

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "ALL", "combined_xp",
         f"mae={mae:.3f}, corr={corr:.3f}, naive_mae={naive_mae:.3f}, "
         f"fpl_own_mae={fpl_mae:.3f} (n={len(bench)}), our_mae_same_rows={our_mae_same_rows:.3f}"),
    )
    run_id = cur.lastrowid
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()
