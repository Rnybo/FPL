"""
The payoff: runs every layer on REAL upcoming fixtures (2026-27, loaded by
fetch_upcoming_fixtures.py) instead of only backtesting on history. Produces
actual forward-looking xP.

Uses "current state" features throughout -- the same unshifted-EWM pattern
introduced in fit_minutes_model.current_state_features: each player's latest
known rate, computed INCLUDING their most recent real match, since we're
predicting their genuinely next (unplayed) fixture rather than replaying a
known outcome. Falls back gracefully to model-only lambdas when market odds
aren't available for a fixture (true for all of 2026-27 right now -- see
docs/multi-gameweek-forecasting.md).

Live team-news override (apply_live_status_override.py) is applied to minutes.

Predicts a HORIZON of gameweeks in one run (see HORIZON_GAMEWEEKS), not just
the next one -- cheap, since Layers 3/5 only train once regardless of how
many fixture rows get looped over afterward. This lets the API sum any
sub-range (e.g. GW1-3 of a GW1-5 run) without re-running predictions.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom

import fit_minutes_model as l3
import fit_player_involvement as l2
import fit_discrete_events as l4b
import fit_defensive_contribution as l4a
import fit_bonus_points as l5
import blend_odds_with_model as l1b
import combine_xp as cx
from apply_live_status_override import apply_override, load_live_status, load_predicted_lineups

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
CURRENT_SEASON = "2026-27"
# Removed the old fixed HORIZON_GAMEWEEKS=5 cap (found via user report: xP
# stopped changing above GW5, since there simply was no prediction data past
# it). docs/multi-gameweek-forecasting.md already established Dixon-Coles
# doesn't degrade with horizon distance -- the only real limitation was
# market-odds availability, which the pipeline already falls back gracefully
# from. So: predict every remaining unplayed fixture in the season, not an
# arbitrary cutoff that could recreate this same bug at a different number.


def current_ewm_rates(hist: pd.DataFrame, cols: list, halflife: float) -> pd.DataFrame:
    """One row per player: current (unshifted, includes their latest real match)
    per-90 EWM rate for each column in cols. hist must be sorted by
    player_id, kickoff_time and have a 'minutes' column."""
    hist = hist.sort_values(["player_id", "kickoff_time"])
    out = {}
    for col in cols:
        def per_player(group, col=col):
            ewm_val = group[col].ewm(halflife=halflife, min_periods=1).mean()
            ewm_min = group["minutes"].ewm(halflife=halflife, min_periods=1).mean()
            return ewm_val / (ewm_min / 90).replace(0, np.nan)
        rate = hist.groupby("player_id", group_keys=False).apply(per_player)
        rate.index = hist.index
        out[f"{col}_rate90"] = rate
    result = pd.concat(out, axis=1)
    result.columns = out.keys()
    result["player_id"] = hist["player_id"]
    latest = result.groupby("player_id").tail(1).set_index("player_id")
    return latest


def current_ewm_raw(hist: pd.DataFrame, cols: list, halflife: float) -> pd.DataFrame:
    """Current (unshifted) EWM of raw per-match values (not per-90 rates) --
    matches fit_bonus_points.py's feature shape, which uses raw EWM directly."""
    hist = hist.sort_values(["player_id", "kickoff_time"])
    out = {}
    for col in cols:
        rate = hist.groupby("player_id", group_keys=False)[col].apply(
            lambda s: s.ewm(halflife=halflife, min_periods=1).mean()
        )
        rate.index = hist.index
        out[f"{col}_ewm"] = rate
    result = pd.concat(out, axis=1)
    result["player_id"] = hist["player_id"]
    return result.groupby("player_id").tail(1).set_index("player_id")


def load_full_history(conn):
    df = pd.read_sql_query(
        """SELECT pgs.*, p.name, p.position, f.kickoff_time, f.home_team_id, f.away_team_id
           FROM player_gameweek_stats pgs
           JOIN players p ON pgs.player_id = p.player_id
           JOIN fixtures f ON pgs.fixture_id = f.fixture_id
           WHERE p.position IN ('GK','DEF','MID','FWD')""",
        conn,
    )
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    # team_id per row -- needed by l3.add_features/current_state_features's
    # is_transfer feature (see docs/GOTCHAS.md). Same was_home-based
    # reconstruction used in l3.load_data and fit_player_involvement.py.
    df["team_id"] = np.where(df["was_home"] == 1, df["home_team_id"], df["away_team_id"])
    # RULE FIX (see fit_player_involvement.py's add_player_rate_features docstring
    # and docs/GOTCHAS.md): pure xG/xA systematically undershoots real goals/assists
    # (-23.5%/-46.6% in aggregate) -- this MUST match l2's blend exactly, or the fix
    # only helps the backtest metrics while leaving live 2026-27 predictions unfixed.
    df["quality_goal_signal"] = l2.BLEND_WEIGHT_GOAL * df["xg"] + (1 - l2.BLEND_WEIGHT_GOAL) * df["goals"]
    df["quality_assist_signal"] = l2.BLEND_WEIGHT_ASSIST * df["xa"] + (1 - l2.BLEND_WEIGHT_ASSIST) * df["assists"]
    df["played"] = (df["minutes"] > 0).astype(int)
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    hist = load_full_history(conn)
    print(f"Loaded {len(hist)} historical player-fixture rows across all seasons")

    print("Training Layer 3 (minutes) on full history...")
    l3_train = l3.add_features(hist.copy())
    l3_result = l3.train_and_eval(l3_train, l3_train)
    # current_team_by_player: needed for is_transfer -- a fresh summer signing
    # may have zero match rows yet for their new club, so this can't be derived
    # from hist's own rows alone (see fit_minutes_model.py's docstring).
    current_team_by_player = dict(conn.execute(
        "SELECT player_id, current_team_id FROM players WHERE current_team_id IS NOT NULL"
    ).fetchall())
    l3_current = l3.current_state_features(hist.copy(), current_team_by_player).set_index("player_id")

    print("Training Layer 5 (bonus) on full history...")
    l5_train = l5.add_features(hist.copy())
    l5_model = l5.train_and_eval(l5_train, l5_train)[0]
    bonus_current = current_ewm_raw(hist, l5.FEATURE_SOURCE_COLS, l5.HALFLIFE_MATCHES)
    # Same simple low-variance baseline as l5.add_features's bonus_ewm_simple --
    # RULE FIX: l5_model.predict() below is called directly on the live data,
    # bypassing train_and_eval's blend entirely (that blend only lives inside
    # the function, not the model object) -- exactly the same kind of live/backtest
    # duplication already found and fixed for goals/assists and DefCon this session.
    bonus_simple_current = current_ewm_raw(hist, ["bonus"], l5.HALFLIFE_MATCHES)

    print("Computing current-state rates (goals, assists, cards, penalties, saves)...")
    involvement_rates = current_ewm_rates(
        hist, ["quality_goal_signal", "quality_assist_signal"], l2.HALFLIFE_MATCHES
    )
    # Same calibration multipliers as l2.add_player_rate_features -- applied AFTER
    # the EWM rate (corrects the aggregate level; the blend above already handles
    # relative ranking, see that function's docstring for why these are separate).
    involvement_rates["quality_goal_signal_rate90"] *= l2.CALIBRATION_MULTIPLIER_GOAL
    involvement_rates["quality_assist_signal_rate90"] *= l2.CALIBRATION_MULTIPLIER_ASSIST
    event_rates = current_ewm_rates(
        hist, ["yellow_cards", "red_cards", "penalties_missed", "penalties_saved", "own_goals", "saves"],
        l4b.HALFLIFE_MATCHES,
    )

    dc_hist = hist[hist["season_id"] == "2025-26"].copy()
    if len(dc_hist):
        dc_rates = current_ewm_rates(dc_hist, ["defensive_contribution"], l4a.HALFLIFE_MATCHES)
        dc_games_played = dc_hist.groupby("player_id")["played"].sum().rename("dc_games_played")
        dc_rates = dc_rates.join(dc_games_played, how="left")
        dc_rates["dc_games_played"] = dc_rates["dc_games_played"].fillna(0)
        position_by_player = dc_hist.drop_duplicates("player_id").set_index("player_id")["position"]
        dc_rates = dc_rates.join(position_by_player, how="left")
        dc_rates["dc_pos_avg"] = dc_rates.groupby("position")["defensive_contribution_rate90"].transform("mean")
    else:
        dc_rates = pd.DataFrame(columns=["defensive_contribution_rate90", "dc_games_played", "dc_pos_avg"])


    print("Loading upcoming fixtures + current roster...")
    mu, home_adv, strength = l2.load_dixon_coles_params(conn)
    rho = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id="
        "(SELECT run_id FROM model_runs WHERE model_type='dixon_coles' ORDER BY run_id DESC LIMIT 1)"
    ).fetchall())["rho"]
    alpha = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id="
        "(SELECT run_id FROM model_runs WHERE model_type='dixon_coles_market_blend' ORDER BY run_id DESC LIMIT 1)"
    ).fetchall())["alpha"]

    next_gw = conn.execute(
        "SELECT MIN(gw) FROM fixtures WHERE season_id=? AND finished=0", (CURRENT_SEASON,)
    ).fetchone()[0]
    horizon_end_gw = conn.execute(
        "SELECT MAX(gw) FROM fixtures WHERE season_id=? AND finished=0", (CURRENT_SEASON,)
    ).fetchone()[0]
    print(f"Predicting GW{next_gw}-{horizon_end_gw} of {CURRENT_SEASON} (every remaining unplayed fixture)")

    fixtures = pd.read_sql_query(
        """SELECT f.fixture_id, f.gw, th.name AS home_team, ta.name AS away_team,
                  f.home_team_id, f.away_team_id
           FROM fixtures f
           JOIN teams th ON f.home_team_id=th.team_id AND f.season_id=th.season_id
           JOIN teams ta ON f.away_team_id=ta.team_id AND f.season_id=ta.season_id
           WHERE f.season_id=? AND f.finished=0""",
        conn, params=(CURRENT_SEASON,),
    )

    roster = pd.read_sql_query(
        """SELECT p.player_id, p.name, p.position, ps.team_id
           FROM player_season ps JOIN players p ON ps.player_id=p.player_id
           WHERE ps.season_id=? AND p.position IN ('GK','DEF','MID','FWD')""",
        conn, params=(CURRENT_SEASON,),
    )

    home = fixtures.rename(columns={"home_team_id": "team_id"})[["fixture_id", "gw", "team_id", "home_team", "away_team"]]
    home["was_home"] = True
    away = fixtures.rename(columns={"away_team_id": "team_id"})[["fixture_id", "gw", "team_id", "home_team", "away_team"]]
    away["was_home"] = False
    fixture_teams = pd.concat([home, away], ignore_index=True)

    df = roster.merge(fixture_teams, on="team_id", how="inner")
    df["team"] = np.where(df["was_home"], df["home_team"], df["away_team"])
    print(f"{len(df)} player-fixture predictions to compute")

    odds = pd.read_sql_query("SELECT fixture_id, market, team_or_outcome, price FROM match_odds", conn)
    df = cx.add_team_lambdas(df, mu, home_adv, rho, strength, alpha, odds)
    df = cx.add_clean_sheet_prob(df, rho)

    league_avg = 0.0
    df["team_avg_lambda"] = df["team"].map(
        lambda t: np.exp(mu + strength["attack"].get(t, league_avg) + home_adv / 2)
    )
    df["fixture_adjustment"] = df["team_lambda_for"] / df["team_avg_lambda"]


    print("Merging current-state rates + applying live status override...")
    df = df.set_index("player_id")
    df = df.join(l3_current[l3.FEATURE_COLUMNS], how="left")
    df = df.join(involvement_rates, how="left")
    df = df.join(event_rates, how="left")
    df = df.join(dc_rates.drop(columns=["position"], errors="ignore"), how="left")
    df = df.join(bonus_current, how="left")
    df = df.join(bonus_simple_current, how="left")
    df = df.reset_index()

    # PRICE BLEND, MID only -- see l2.PRICE_BLEND_WEIGHT_MID's docstring for why
    # this is scoped to MID specifically. Uses each player's LATEST known price
    # (their current price going into the fixtures being predicted) -- the live
    # equivalent of the backtest's price_shifted (previous-match price).
    latest_price = hist.sort_values(["player_id", "kickoff_time"]).groupby("player_id")["price_at_time"].last()
    df = df.set_index("player_id")
    df["latest_price"] = latest_price
    df["latest_price"] = df["latest_price"].fillna(df.groupby("position")["latest_price"].transform("mean"))
    mid_mask = df["position"] == "MID"
    price_rate_goal = (l2.PRICE_SLOPE_GOAL_MID * df["latest_price"] + l2.PRICE_INTERCEPT_GOAL_MID).clip(lower=0)
    price_rate_assist = (l2.PRICE_SLOPE_ASSIST_MID * df["latest_price"] + l2.PRICE_INTERCEPT_ASSIST_MID).clip(lower=0)
    df.loc[mid_mask, "quality_goal_signal_rate90"] = (
        l2.PRICE_BLEND_WEIGHT_MID * df.loc[mid_mask, "quality_goal_signal_rate90"]
        + (1 - l2.PRICE_BLEND_WEIGHT_MID) * price_rate_goal[mid_mask]
    )
    df.loc[mid_mask, "quality_assist_signal_rate90"] = (
        l2.PRICE_BLEND_WEIGHT_MID * df.loc[mid_mask, "quality_assist_signal_rate90"]
        + (1 - l2.PRICE_BLEND_WEIGHT_MID) * price_rate_assist[mid_mask]
    )
    df = df.reset_index()

    for col in df.columns:
        if col.endswith("_rate90") or col.endswith("_ewm"):
            pos_avg = df.groupby("position")[col].transform("mean")
            df[col] = df[col].fillna(pos_avg)
    df[l3.FEATURE_COLUMNS] = df[l3.FEATURE_COLUMNS].fillna(0)

    df["p_played_model"] = l3_result["clf"].predict_proba(df[l3.FEATURE_COLUMNS])[:, 1]
    df["e_minutes_given_played"] = l3_result["reg"].predict(df[l3.FEATURE_COLUMNS])
    df["p_60plus_given_played"] = l3_result["clf60"].predict_proba(df[l3.FEATURE_COLUMNS])[:, 1]

    live = load_live_status(conn)
    df = df.merge(live[["player_id", "status", "chance_of_playing_next_round"]], on="player_id", how="left")
    df["status"] = df["status"].fillna("a")

    # FFS predicted-XI tier -- merged on (player_id, fixture_id) since
    # predicted_lineups.fixture_id is specific to each player's OWN next
    # match (see apply_live_status_override.py's docstring); every other row
    # in this player's multi-gameweek horizon simply gets no match (NaN),
    # correctly falling through to the model's own estimate in apply_override.
    predicted_lineups = load_predicted_lineups(conn)
    df = df.merge(predicted_lineups, on=["player_id", "fixture_id"], how="left")

    df["p_played_final"] = df.apply(
        lambda r: apply_override(r["p_played_model"], r["status"], r["chance_of_playing_next_round"],
                                  r["predicted_start"]), axis=1
    )
    df["expected_minutes"] = np.clip(df["p_played_final"] * df["e_minutes_given_played"], 0, 95)


    print("Assembling xP...")
    df["lambda_goal"] = df["quality_goal_signal_rate90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]
    df["lambda_assist"] = df["quality_assist_signal_rate90"] * (df["expected_minutes"] / 90) * df["fixture_adjustment"]
    df["goal_pts"] = df["lambda_goal"] * df["position"].map(cx.GOAL_POINTS)
    df["assist_pts"] = df["lambda_assist"] * cx.ASSIST_POINTS
    p_60plus = df["p_played_final"] * df["p_60plus_given_played"]
    df["p_60plus"] = p_60plus  # kept as its own column for captain_simulation.py -- see schema.sql
    df["cs_pts"] = df["p_clean_sheet"] * df["position"].map(cx.CLEAN_SHEET_POINTS) * p_60plus
    df["appearance_pts"] = df["p_played_final"] * (
        df["p_60plus_given_played"] * 2 + (1 - df["p_60plus_given_played"]) * 1
    )

    df["conceded_penalty"] = 0.0
    def_gk_mask = df["position"].isin(["GK", "DEF"])
    df.loc[def_gk_mask, "conceded_penalty"] = -cx.expected_floor_div_k(
        df.loc[def_gk_mask, "team_lambda_against"].values, k=2
    ) * p_60plus[def_gk_mask].values

    for ev, pts in l4b.POINTS_PER_EVENT.items():
        df[f"lambda_{ev}"] = df[f"{ev}_rate90"] * (df["expected_minutes"] / 90)
    df["card_pen_pts"] = (df["lambda_yellow_cards"] * -1 + df["lambda_red_cards"] * -3
                           + df["lambda_penalties_missed"] * -2 + df["lambda_own_goals"] * -2)
    df["pen_save_pts"] = 0.0
    gk_mask = df["position"] == "GK"
    df.loc[gk_mask, "pen_save_pts"] = df.loc[gk_mask, "lambda_penalties_saved"] * 5

    lam_saves = (df["saves_rate90"] * (df["expected_minutes"] / 90)).clip(lower=0).values
    df["expected_save_points"] = l4b.expected_save_points(lam_saves)
    df.loc[~gk_mask, "expected_save_points"] = 0.0
    df["lambda_saves"] = lam_saves  # for captain_simulation.py -- see schema.sql
    df.loc[~gk_mask, "lambda_saves"] = 0.0


    df["expected_defcon_points"] = 0.0
    df["p_defcon"] = 0.0  # for captain_simulation.py -- see schema.sql
    dc_mask = df["position"].isin(["DEF", "MID", "FWD"]) & df["defensive_contribution_rate90"].notna()
    if dc_mask.any():
        dc_weights = dict(conn.execute(
            "SELECT feature_name, weight FROM model_weights WHERE run_id="
            "(SELECT run_id FROM model_runs WHERE model_type='defensive_contribution_negbinom' ORDER BY run_id DESC LIMIT 1)"
        ).fetchall())
        dc_K, dc_alpha = dc_weights["shrinkage_K"], dc_weights["nb_dispersion_alpha"]

        n = df.loc[dc_mask, "dc_games_played"].fillna(0)
        weight = n / (n + dc_K) if dc_K > 0 else (n > 0).astype(float)
        pos_avg_fallback = df.loc[dc_mask, "dc_pos_avg"].fillna(df.loc[dc_mask, "defensive_contribution_rate90"].mean())
        shrunk_rate = weight * df.loc[dc_mask, "defensive_contribution_rate90"] + (1 - weight) * pos_avg_fallback
        # Same calibration multiplier as combine_xp.py -- corrects the real, verified
        # trend-lag (defcon rates rose over 2025-26, a backward-looking EWM lags a
        # rising trend). Must match exactly or this fix only helps backtest metrics.
        shrunk_rate = shrunk_rate * l4a.CALIBRATION_MULTIPLIER_MU

        thresholds = df.loc[dc_mask, "position"].map(l4a.THRESHOLDS).to_numpy(dtype=int)
        mu = (shrunk_rate * (df.loc[dc_mask, "expected_minutes"] / 90)).clip(lower=1e-6).to_numpy(dtype=float)
        if dc_alpha > 1e-8:
            n_param = 1.0 / dc_alpha
            p_param = n_param / (n_param + mu)
            p_defcon = 1 - nbinom.cdf(thresholds - 1, n_param, p_param)
        else:
            p_defcon = 1 - poisson.cdf(thresholds - 1, mu)
        df.loc[dc_mask, "expected_defcon_points"] = p_defcon * cx.DEFCON_POINTS
        df.loc[dc_mask, "p_defcon"] = p_defcon

    bonus_feature_cols = [f"{c}_ewm" for c in l5.FEATURE_SOURCE_COLS] + ["position_code", "was_home"]
    df["position_code"] = df["position"].astype("category").cat.codes
    df["was_home"] = df["was_home"].astype(int)
    lgb_bonus_pred = l5_model.predict(df[bonus_feature_cols])
    # Same shrinkage blend as l5.train_and_eval -- see BLEND_WEIGHT_BONUS's docstring.
    df["expected_bonus"] = (l5.BLEND_WEIGHT_BONUS * lgb_bonus_pred
                             + (1 - l5.BLEND_WEIGHT_BONUS) * df["bonus_ewm"]).clip(0, 3)

    df["xP"] = (df["appearance_pts"] + df["goal_pts"] + df["assist_pts"] + df["cs_pts"]
                + df["conceded_penalty"] + df["card_pen_pts"] + df["pen_save_pts"]
                + df["expected_save_points"] + df["expected_defcon_points"] + df["expected_bonus"])

    print(f"\nTop 20 by TOTAL xP across GW{next_gw}-{horizon_end_gw}, {CURRENT_SEASON}:")
    totals = df.groupby(["name", "team", "position"], as_index=False)["xP"].sum()
    print(totals.nlargest(20, "xP").to_string(index=False, formatters={"xP": "{:.2f}".format})
          .encode("ascii", "replace").decode())

    conn.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), CURRENT_SEASON, "ALL", "predict_upcoming",
         f"gw={next_gw}-{horizon_end_gw}, n_predictions={len(df)}"),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.executemany(
        "INSERT INTO model_predictions (run_id, player_id, fixture_id, predicted_points, actual_points) "
        "VALUES (?,?,?,?,NULL)",
        [(run_id, int(r.player_id), int(r.fixture_id), float(r.xP)) for r in df.itertuples()],
    )
    # Transparency: persist the COMPONENT breakdown too, not just the final xP -- see
    # docs/model-architecture.md's "never a black box" principle. Same run_id/player_id/
    # fixture_id as model_predictions, so summing predicted_points and summing these
    # components across any gameweek range will always add up consistently (same source row).
    conn.executemany(
        """INSERT INTO xp_breakdown
           (run_id, player_id, fixture_id, appearance_pts, goal_pts, assist_pts, cs_pts,
            conceded_penalty, card_pen_pts, pen_save_pts, save_pts, defcon_pts, bonus_pts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(run_id, int(r.player_id), int(r.fixture_id), float(r.appearance_pts), float(r.goal_pts),
          float(r.assist_pts), float(r.cs_pts), float(r.conceded_penalty), float(r.card_pen_pts),
          float(r.pen_save_pts), float(r.expected_save_points), float(r.expected_defcon_points),
          float(r.expected_bonus)) for r in df.itertuples()],
    )
    # Captaincy Monte Carlo simulation inputs -- see schema.sql / captain_simulation.py.
    # Additive only: reuses columns already computed above, changes no existing formula.
    conn.executemany(
        """INSERT INTO captain_sim_inputs
           (run_id, player_id, fixture_id, position, p_played, p_60plus, lambda_goal,
            lambda_assist, p_clean_sheet, p_defcon, lambda_saves, expected_bonus, minor_pts_fixed)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(run_id, int(r.player_id), int(r.fixture_id), r.position, float(r.p_played_final),
          float(r.p_60plus), float(r.lambda_goal), float(r.lambda_assist), float(r.p_clean_sheet),
          float(r.p_defcon), float(r.lambda_saves), float(r.expected_bonus),
          float(r.card_pen_pts + r.conceded_penalty + r.pen_save_pts)) for r in df.itertuples()],
    )
    conn.commit()
    print(f"\nPersisted {len(df)} predictions as model_run_id={run_id}")
    conn.close()
