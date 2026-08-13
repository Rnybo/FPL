"""GET /api/players -- the scout table: every player's predicted xP (summed
over a gameweek range) plus the FULL component breakdown, so the UI can show
exactly where a player's number comes from (goals, assists, clean sheets,
bonus, defensive contribution, etc.) -- see docs/model-architecture.md's
"never a black box" principle and xp_breakdown's schema comment for why this
always sums consistently with the headline xP number.
"""
from fastapi import APIRouter, Query
import numpy as np
import pandas as pd
from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/players", tags=["players"])

BREAKDOWN_COLS = [
    "appearance_pts", "goal_pts", "assist_pts", "cs_pts", "conceded_penalty",
    "card_pen_pts", "pen_save_pts", "save_pts", "defcon_pts", "bonus_pts",
]

# Most recent COMPLETE season -- used for the "Historic Stats" panel in the
# player detail dialog. Hardcoded rather than derived from CURRENT_SEASON
# since "most recent complete" isn't simply "current season minus one" in
# every case (e.g. before any 2026-27 data exists at all).
LAST_COMPLETE_SEASON = "2025-26"

# Real scoring rules -- duplicated from captain_simulation.py/combine_xp.py
# rather than imported, same low-risk pattern already established between
# those two files. Used to reconstruct REAL historical points-by-component
# (goals/assists/bonus/etc.) from raw per-game stats, since FPL's API gives
# a game's total_points but not its breakdown. Validated against real
# 2025-26 data: 99% exact match on a 500-game random sample -- the residual
# ~1% is almost entirely players whose CURRENT position differs from what it
# was at the time (e.g. a MID->FWD reclassification since), not a rule error.
GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
DEFCON_POINTS = 2
DEFCON_THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}  # GK ineligible


def _last_season_breakdown(position_by_player: dict[int, str]) -> dict[int, dict]:
    """Per-player: real points for every game they started (see
    load_player_gameweeks_to_cache.py's docstring for why `starts` -- a true
    started-the-match flag -- is used rather than `minutes > 0`, matching
    exactly what the person asked for: "data points for when starting a
    game"), the top-25%/50%/75%/overall average of those games, and the
    real points-by-component total for the season. Used for the "Last
    season stats" chart in the player detail modal -- variance/std_dev
    alone weren't intuitive, this replaces them with something visual."""
    raw = query_df(
        """SELECT player_id, gw, minutes, starts, goals, assists, clean_sheet, goals_conceded,
                  saves, penalties_saved, penalties_missed, yellow_cards, red_cards, own_goals,
                  bonus, defensive_contribution
           FROM player_gameweek_stats WHERE season_id = ?""",
        (LAST_COMPLETE_SEASON,),
    )
    if raw.empty:
        return {}

    # Double-gameweek-safe: sum every fixture within the same gw first, same
    # convention as gw_by_player above.
    numeric_cols = ["minutes", "starts", "goals", "assists", "clean_sheet", "goals_conceded",
                     "saves", "penalties_saved", "penalties_missed", "yellow_cards", "red_cards",
                     "own_goals", "bonus", "defensive_contribution"]
    raw = raw.groupby(["player_id", "gw"], as_index=False)[numeric_cols].sum()
    raw["position"] = raw["player_id"].map(position_by_player)
    raw = raw.dropna(subset=["position"])  # player_id not in the current players table at all
    if raw.empty:
        return {}

    pos = raw["position"]
    played_60 = raw["minutes"] >= 60
    raw["appearance_pts"] = (raw["minutes"] > 0).astype(int) + played_60.astype(int)
    raw["goal_pts"] = raw["goals"] * pos.map(GOAL_POINTS)
    raw["assist_pts"] = raw["assists"] * ASSIST_POINTS
    raw["cs_pts"] = np.where((raw["clean_sheet"] > 0) & played_60, pos.map(CLEAN_SHEET_POINTS), 0)
    raw["conceded_pts"] = np.where(pos.isin(["GK", "DEF"]), -(raw["goals_conceded"] // 2), 0)
    raw["save_pts"] = np.where(pos == "GK", raw["saves"] // 3, 0)
    raw["card_pts"] = -1 * raw["yellow_cards"] + -3 * raw["red_cards"]
    raw["pen_pts"] = 5 * raw["penalties_saved"] + -2 * raw["penalties_missed"] + -2 * raw["own_goals"]
    defcon_threshold = pos.map(DEFCON_THRESHOLDS)
    raw["defcon_pts"] = np.where(
        defcon_threshold.notna() & (raw["defensive_contribution"].fillna(0) >= defcon_threshold),
        DEFCON_POINTS, 0,
    )
    raw["points"] = (
        raw["appearance_pts"] + raw["goal_pts"] + raw["assist_pts"] + raw["cs_pts"]
        + raw["conceded_pts"] + raw["save_pts"] + raw["card_pts"] + raw["pen_pts"]
        + raw["bonus"] + raw["defcon_pts"]
    )

    result: dict[int, dict] = {}
    for pid, g in raw.groupby("player_id"):
        started = g[g["starts"] >= 1]
        if started.empty:
            continue
        pts_sorted = np.sort(started["points"].values)[::-1]  # descending -- best games first
        n = len(pts_sorted)

        def top_pct_avg(frac: float) -> float:
            k = max(1, int(np.ceil(n * frac)))
            return round(float(pts_sorted[:k].mean()), 2)

        result[int(pid)] = {
            "games": [
                {"gw": int(r.gw), "points": int(r.points)}
                for r in started.sort_values("gw").itertuples()
            ],
            "percentile_averages": {
                "top25": top_pct_avg(0.25),
                "top50": top_pct_avg(0.50),
                "top75": top_pct_avg(0.75),
                "overall": round(float(pts_sorted.mean()), 2),
            },
            "points_by_component": {
                "appearance": int(started["appearance_pts"].sum()),
                "goals": int(started["goal_pts"].sum()),
                "assists": int(started["assist_pts"].sum()),
                "clean_sheet": int(started["cs_pts"].sum()),
                "defcon": int(started["defcon_pts"].sum()),
                "bonus": int(started["bonus"].sum()),
                "cards": int(started["card_pts"].sum()),
                "conceded": int(started["conceded_pts"].sum()),
                "saves": int(started["save_pts"].sum()),
                "penalties": int(started["pen_pts"].sum()),
            },
        }
    return result


@router.get("")
def list_players(
    gw_start: int | None = Query(None, description="First gameweek to include (inclusive)"),
    gw_end: int | None = Query(None, description="Last gameweek to include (inclusive)"),
):
    latest_run = query_df(
        "SELECT run_id, notes FROM model_runs WHERE model_type='predict_upcoming' "
        "ORDER BY run_id DESC LIMIT 1"
    )
    if latest_run.empty:
        return {"players": [], "run_id": None, "note": "No predictions generated yet"}
    run_id = int(latest_run.iloc[0]["run_id"])

    breakdown_cols_sql = ", ".join(f"b.{c}" for c in BREAKDOWN_COLS)
    sql = f"""SELECT p.player_id, p.name, p.position, t.name AS team, t.code AS team_code,
                     ps.price_end AS price, mp.predicted_points AS xP, f.gw, {breakdown_cols_sql}
              FROM model_predictions mp
              JOIN players p ON mp.player_id = p.player_id
              JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
              JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?
              JOIN fixtures f ON f.fixture_id = mp.fixture_id
              JOIN xp_breakdown b ON b.run_id = mp.run_id AND b.player_id = mp.player_id
                                   AND b.fixture_id = mp.fixture_id
              WHERE mp.run_id = ?"""
    params: tuple = (CURRENT_SEASON, CURRENT_SEASON, run_id)
    if gw_start is not None:
        sql += " AND f.gw >= ?"
        params += (gw_start,)
    if gw_end is not None:
        sql += " AND f.gw <= ?"
        params += (gw_end,)

    df = query_df(sql, params)

    # Per-gameweek xP -- summed within a gameweek first (double-gameweek-safe:
    # two fixtures in the same gw add together, matching how the headline xP
    # already handles doubles elsewhere in the pipeline), kept SEPARATE from
    # the range-wide aggregate below so the UI can show/sort by an individual
    # gameweek without losing the overall total.
    per_gw = df.groupby(["player_id", "gw"], as_index=False)["xP"].sum()
    gw_by_player: dict[int, list[dict]] = {}
    for row in per_gw.to_dict(orient="records"):
        gw_by_player.setdefault(row["player_id"], []).append(
            {"gw": int(row["gw"]), "xP": round(row["xP"], 3)}
        )
    for pid in gw_by_player:
        gw_by_player[pid].sort(key=lambda r: r["gw"])

    # Same double-gameweek-safe aggregation as optimise.py/squad.py -- sum every
    # fixture in the range for a player, both the headline xP and each component.
    sum_cols = ["xP"] + BREAKDOWN_COLS
    df = df.groupby(["player_id", "name", "position", "team", "team_code", "price"], as_index=False)[sum_cols].sum()

    # Historic Stats panel data -- last complete season's real totals, not a
    # prediction. Separate query since it's a different season/shape than
    # the rest of this endpoint's current-season prediction data.
    historic_df = query_df(
        """SELECT player_id, SUM(minutes) AS minutes, SUM(goals) AS goals, SUM(assists) AS assists,
                  SUM(xg) AS xg, SUM(xa) AS xa
           FROM player_gameweek_stats WHERE season_id = ? GROUP BY player_id""",
        (LAST_COMPLETE_SEASON,),
    )
    historic_by_player = {
        row["player_id"]: {k: round(v, 2) if isinstance(v, float) else v
                            for k, v in row.items() if k != "player_id"}
        for row in historic_df.to_dict(orient="records")
    }

    # Real per-gameweek REAL points distribution (not our model's xP -- actual
    # scored FPL points), last complete season -- mean/max/min/variance for
    # understanding a player's genuine ceiling/floor, plus start% (starts is
    # a true "started the match" flag, not inferred from minutes -- see
    # load_player_gameweeks_to_cache.py's docstring; NULL for players with no
    # 2025-26 data at all, e.g. a brand-new signing). Population variance
    # (ddof=0), not sample variance -- describing this player's own actual
    # season, not estimating a wider population from a sample of it.
    last_season_gw = query_df(
        "SELECT player_id, total_points, starts FROM player_gameweek_stats WHERE season_id = ?",
        (LAST_COMPLETE_SEASON,),
    )
    last_season_stats_by_player: dict[int, dict] = {}
    if not last_season_gw.empty:
        agg = last_season_gw.groupby("player_id").agg(
            games=("total_points", "count"),
            starts=("starts", "sum"),
            mean_points=("total_points", "mean"),
            max_points=("total_points", "max"),
            min_points=("total_points", "min"),
            variance=("total_points", lambda s: s.var(ddof=0)),
            std_dev=("total_points", lambda s: s.std(ddof=0)),
        ).reset_index()
        agg["start_pct"] = (100 * agg["starts"] / agg["games"]).round(1)
        for r in agg.to_dict(orient="records"):
            last_season_stats_by_player[r["player_id"]] = {
                "games": int(r["games"]),
                "starts": int(r["starts"]) if pd.notna(r["starts"]) else None,
                "start_pct": r["start_pct"] if pd.notna(r["start_pct"]) else None,
                "mean_points": round(r["mean_points"], 2),
                "max_points": int(r["max_points"]),
                "min_points": int(r["min_points"]),
                "variance": round(r["variance"], 2),
                "std_dev": round(r["std_dev"], 2),
            }

    players = []
    position_by_player = {row["player_id"]: row["position"] for row in df.to_dict(orient="records")}
    breakdown_by_player = _last_season_breakdown(position_by_player)
    for row in df.to_dict(orient="records"):
        breakdown = {c: round(row.pop(c), 3) for c in BREAKDOWN_COLS}
        row["breakdown"] = breakdown
        row["gameweeks"] = gw_by_player.get(row["player_id"], [])
        row["historic"] = historic_by_player.get(row["player_id"])
        row["last_season_stats"] = last_season_stats_by_player.get(row["player_id"])
        row["last_season_breakdown"] = breakdown_by_player.get(row["player_id"])
        players.append(row)
    players.sort(key=lambda p: p["xP"], reverse=True)

    return {"run_id": run_id, "gw_start": gw_start, "gw_end": gw_end, "players": players}
