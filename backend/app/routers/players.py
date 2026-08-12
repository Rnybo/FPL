"""GET /api/players -- the scout table: every player's predicted xP (summed
over a gameweek range) plus the FULL component breakdown, so the UI can show
exactly where a player's number comes from (goals, assists, clean sheets,
bonus, defensive contribution, etc.) -- see docs/model-architecture.md's
"never a black box" principle and xp_breakdown's schema comment for why this
always sums consistently with the headline xP number.
"""
from fastapi import APIRouter, Query
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

    players = []
    for row in df.to_dict(orient="records"):
        breakdown = {c: round(row.pop(c), 3) for c in BREAKDOWN_COLS}
        row["breakdown"] = breakdown
        row["gameweeks"] = gw_by_player.get(row["player_id"], [])
        row["historic"] = historic_by_player.get(row["player_id"])
        players.append(row)
    players.sort(key=lambda p: p["xP"], reverse=True)

    return {"run_id": run_id, "gw_start": gw_start, "gw_end": gw_end, "players": players}
