"""
Captaincy Monte Carlo simulation -- turns each player's point-estimate xP into a
full points DISTRIBUTION for a gameweek, using the SAME lambdas/probabilities the
main pipeline already computed (captain_sim_inputs, populated by predict_upcoming.py).
No new modeling: variance falls out naturally from what's already there -- a
striker's high goal-lambda means a fat right tail (goals pay 4-10pts each), a
defender's clean-sheet/defcon probabilities are bounded and near-deterministic
(tight distribution). See docs/GOTCHAS.md for the "why not back-derive from
xp_breakdown" note.

Simplifications (small-magnitude, don't affect the safe-vs-haul decision):
- Components sampled independently (goals/assists/CS/defcon in reality correlate
  a little through the match state -- not modeled here).
- minor_pts_fixed (cards, pen-miss/save, conceded-goals penalty) is added
  deterministically per sample -- too rare/small to be worth its own distribution.
- GK saves: lambda_saves is already an expected COUNT (from predict_upcoming.py's
  saves_rate90), sampled as Poisson, save points = floor(saves/3) per sample --
  exact given that lambda, unlike the E[floor(X/3)] approximation used elsewhere.

Bonus: expected_bonus is a full LightGBM prediction (see predict_upcoming.py),
not a closed-form function of goals/assists/CS/defcon -- can't be re-run
per-sample without loading the trained model here. Previously (a real bug,
found via user feedback: Haaland's simulated CEILING came out barely above a
single-goal game) it was added as a flat average to every sample regardless
of that sample's own goals/assists -- a hat-trick sample got the exact same
bonus as a blank, which artificially compressed the tail exactly where it
matters for a captaincy ceiling. Fixed by scaling expected_bonus per-sample by
(this sample's simulated goal/assist/CS/defcon points) / (the AVERAGE of the
same quantity, from the model's own lambdas) -- clipped to bonus's real [0,3]
range. This keeps the MEAN bonus across all samples equal to the trained
model's calibrated expected_bonus (so the average case is unchanged), while
letting individual samples swing above/below it in proportion to how big a
game they represent -- a haul sample now plausibly earns close to max bonus,
a blank sample earns close to none, exactly the correlation that was missing.

Doubles/blanks: pass every fixture row for a player in the gameweek; points sum
across fixtures naturally since samples are drawn and summed per fixture.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
CURRENT_SEASON = "2026-27"  # same hardcoded-per-script pattern as predict_upcoming.py
LAST_COMPLETE_SEASON = "2025-26"  # matches players.py's own constant, see its docstring

GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
DEFCON_POINTS = 2

# Real last-season start rate gets a MINORITY blend weight against the model's
# own predicted p_played -- a documented judgment call, same honesty standard
# as LOOKAHEAD_WEIGHT/CAPTAIN_CEILING_WEIGHT in squad.py. The model's p_played
# (Layer 3) already reflects team news, injuries, and recent rotation that a
# full season's start% can't see -- a player who started most of last season
# but has since been dropped/injured would look falsely reliable on history
# alone. Real history's job here is correcting small-sample noise in the
# model's own current estimate, not overriding it.
BLEND_WEIGHT_REAL_START_RATE = 0.3


def _scaled_bonus(base_pts: np.ndarray, expected_base_pts: float, expected_bonus: float) -> np.ndarray:
    """Pure logic split out of simulate_player_points for testability -- see
    the module docstring's "Bonus:" section for the full explanation. In
    short: scales expected_bonus by (this sample's base_pts) / (the average
    base_pts), so the mean bonus across all samples stays equal to
    expected_bonus while individual samples swing with their own performance."""
    if expected_base_pts > 1e-6:
        bonus_scale = base_pts / expected_base_pts
    else:
        bonus_scale = np.where(base_pts > 0, 3.0, 1.0)
    return np.clip(expected_bonus * bonus_scale, 0, 3)


def simulate_player_points(fixture_rows: pd.DataFrame, n_samples: int = 10000, seed: int = 0) -> np.ndarray:
    """fixture_rows: one or more captain_sim_inputs rows for ONE player (>1 = double
    gameweek). Returns an (n_samples,) array of total simulated gameweek points."""
    rng = np.random.default_rng(seed)
    total = np.zeros(n_samples)
    for row in fixture_rows.itertuples(index=False):
        pos = row.position
        goals = rng.poisson(row.lambda_goal, n_samples)
        assists = rng.poisson(row.lambda_assist, n_samples)
        clean_sheet = rng.random(n_samples) < row.p_clean_sheet
        defcon = rng.random(n_samples) < row.p_defcon

        base_pts = (
            goals * GOAL_POINTS[pos]
            + assists * ASSIST_POINTS
            + clean_sheet * CLEAN_SHEET_POINTS[pos]
            + defcon * DEFCON_POINTS
        )
        expected_base_pts = (
            row.lambda_goal * GOAL_POINTS[pos]
            + row.lambda_assist * ASSIST_POINTS
            + row.p_clean_sheet * CLEAN_SHEET_POINTS[pos] * row.p_60plus
            + row.p_defcon * DEFCON_POINTS
        )
        bonus = _scaled_bonus(base_pts, expected_base_pts, row.expected_bonus)

        pts = base_pts + bonus + row.minor_pts_fixed
        if pos == "GK" and row.lambda_saves > 0:
            saves = rng.poisson(row.lambda_saves, n_samples)
            pts = pts + (saves // 3)
        # Appearance points: played at all (1) + reached 60 (extra 1), each its own
        # coin flip consistent with p_played/p_60plus -- and everything above (goals,
        # assists, CS, defcon, bonus, minor) only counts if the player actually played.
        played = rng.random(n_samples) < row.p_played
        played_60 = played & (rng.random(n_samples) < np.divide(row.p_60plus, row.p_played, out=np.zeros(n_samples), where=row.p_played > 0))
        appearance = played.astype(float) + played_60.astype(float)
        total += np.where(played, appearance + pts, 0.0)
    return total


def summarize(samples: np.ndarray) -> dict:
    return {
        "mean": float(samples.mean()),
        "p10": float(np.percentile(samples, 10)),
        "p90": float(np.percentile(samples, 90)),
        "p_haul": float((samples >= 10).mean()),
        "p_blank": float((samples <= 2).mean()),
    }


def _blend_start_rate(model_p_played: pd.Series, model_p_60plus: pd.Series, real_start_rate: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Pure logic split out of load_latest_run_inputs for testability -- see
    BLEND_WEIGHT_REAL_START_RATE's docstring for the full explanation. Falls
    back to the model's own numbers unchanged wherever real_start_rate is NaN
    (no last-season data -- e.g. a new signing)."""
    has_real = real_start_rate.notna()
    blended_p_played = np.where(
        has_real,
        BLEND_WEIGHT_REAL_START_RATE * real_start_rate + (1 - BLEND_WEIGHT_REAL_START_RATE) * model_p_played,
        model_p_played,
    )
    # Preserve the model's own P(60+ minutes | played) ratio rather than
    # leaving p_60plus untouched -- otherwise a big blend swing could push
    # p_60plus above the new p_played, which isn't a valid probability
    # relationship (can't play 60+ more often than you play at all).
    ratio = np.divide(blended_p_played, model_p_played, out=np.ones(len(model_p_played)), where=model_p_played > 0)
    blended_p_60plus = np.minimum(model_p_60plus * ratio, blended_p_played)
    return blended_p_played, blended_p_60plus


def load_latest_run_inputs(conn) -> pd.DataFrame:
    """Adds opponent + FDR (fixture difficulty, 1=easiest..5=hardest, same
    convention as the rest of this project) alongside the raw sim inputs --
    see top_captain_picks's own docstring for why haul% needs this context
    to actually mean something (a defender's "haul" via clean sheet + defcon
    reads very differently against a team that concedes a lot vs one that
    doesn't -- the number alone doesn't say which)."""
    run_id = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()[0]
    df = pd.read_sql_query(
        """SELECT csi.*, p.name, f.gw,
                  f.home_team_id, f.away_team_id, f.home_difficulty, f.away_difficulty,
                  ps.team_id AS player_team_id
           FROM captain_sim_inputs csi
           JOIN players p ON csi.player_id = p.player_id
           JOIN fixtures f ON csi.fixture_id = f.fixture_id
           JOIN player_season ps ON ps.player_id = csi.player_id AND ps.season_id = ?
           WHERE csi.run_id = ?""",
        conn, params=(CURRENT_SEASON, run_id),
    )
    if df.empty:
        return df
    is_home = df["player_team_id"] == df["home_team_id"]
    df["fdr"] = np.where(is_home, df["home_difficulty"], df["away_difficulty"])
    opp_team_id = np.where(is_home, df["away_team_id"], df["home_team_id"])
    team_names = pd.read_sql_query(
        "SELECT team_id, name FROM teams WHERE season_id = ?", conn, params=(CURRENT_SEASON,)
    ).set_index("team_id")["name"]
    df["opponent"] = pd.Series(opp_team_id, index=df.index).map(team_names)
    df["is_home"] = is_home

    # Blend the model's own p_played with real last-season start rate -- see
    # BLEND_WEIGHT_REAL_START_RATE's docstring for why it's a minority weight.
    # AVG(starts) over a season's rows IS the start rate (starts is 0/1 per
    # game) -- no separate percentage calculation needed. Players with no
    # 2025-26 data (new signings) keep the model's p_played unchanged.
    real_starts = pd.read_sql_query(
        "SELECT player_id, AVG(starts) AS real_start_rate FROM player_gameweek_stats "
        "WHERE season_id = ? GROUP BY player_id",
        conn, params=(LAST_COMPLETE_SEASON,),
    )
    df = df.merge(real_starts, on="player_id", how="left")
    df["p_played"], df["p_60plus"] = _blend_start_rate(df["p_played"], df["p_60plus"], df["real_start_rate"])
    return df


def top_captain_picks(conn, gameweek: int, candidates_top_n: int = 40, n_samples: int = 10000, seed: int = 0, top_k: int = 5):
    """Runs the simulation for the top-N candidates by simple xP proxy (sum of
    lambda-derived point components), then returns two top_k tables: safest by
    mean, and best haul-gamble by P(>=10).

    Includes each player's opponent + FDR for that gameweek in the output --
    haul% on its own doesn't say WHY it's high. A defender's clean-sheet +
    defcon route to "haul" and an attacker's goal-explosion route look
    identical as a bare percentage, but mean very different things for
    picking a captain -- showing the fixture lets you judge that yourself
    rather than trusting the number blind."""
    df = load_latest_run_inputs(conn)
    gw_df = df[df["gw"] == gameweek]
    if gw_df.empty:
        raise ValueError(f"No captain_sim_inputs rows for gw={gameweek} -- run predict_upcoming.py first")

    # Cheap proxy to shortlist candidates before running MC on all of them.
    proxy = (
        gw_df["lambda_goal"] * gw_df["position"].map(GOAL_POINTS)
        + gw_df["lambda_assist"] * ASSIST_POINTS
        + gw_df["p_clean_sheet"] * gw_df["position"].map(CLEAN_SHEET_POINTS) * gw_df["p_60plus"]
        + gw_df["p_defcon"] * DEFCON_POINTS
        + gw_df["expected_bonus"]
    ).groupby(gw_df["player_id"]).sum()
    shortlist = proxy.nlargest(candidates_top_n).index

    results = []
    for pid in shortlist:
        rows = gw_df[gw_df["player_id"] == pid]
        name = rows["name"].iloc[0]
        samples = simulate_player_points(rows, n_samples=n_samples, seed=seed)
        stats = summarize(samples)
        stats["player_id"] = pid
        stats["name"] = name
        # "+" joins a double gameweek's two fixtures (rare, but real).
        stats["fixture"] = " + ".join(
            f"{'vs' if r.is_home else '@'} {r.opponent} (FDR {int(r.fdr)})" for r in rows.itertuples()
        )
        stats["fdr"] = float(rows["fdr"].mean())  # mean across doubles, for sorting/filtering
        results.append(stats)
    result_df = pd.DataFrame(results)

    cols = ["name", "fixture", "fdr", "mean", "p10", "p90", "p_haul", "p_blank"]
    safe = result_df.nlargest(top_k, "mean")[cols]
    haul = result_df.nlargest(top_k, "p_haul")[cols]
    return safe, haul


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    next_gw = conn.execute(
        "SELECT MIN(gw) FROM captain_sim_inputs csi JOIN fixtures f ON csi.fixture_id = f.fixture_id"
    ).fetchone()[0]
    print(f"Captain picks for GW{next_gw}\n")
    safe, haul = top_captain_picks(conn, next_gw)
    print("=== Safest (highest mean xP) ===")
    print(safe.to_string(index=False, float_format="%.2f"))
    print("\n=== Haul gamble (highest P(>=10 pts)) ===")
    print(haul.to_string(index=False, float_format="%.2f"))
    conn.close()
