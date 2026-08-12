"""GET /api/squad/optimal -- wraps optimise.py directly (no duplicated ILP
logic here). Runs the real solver on the latest predictions each call --
PuLP/CBC on ~500-600 players is fast (well under a second), so no caching
needed yet; revisit if this router gets hit often enough to matter.

Query params:
  gw_start, gw_end -- gameweek range to sum xP over (default: the full
    horizon predict_upcoming.py computed, see HORIZON_GAMEWEEKS there).
    Summing a sub-range needs no re-prediction -- predict_upcoming.py already
    stored every fixture in the horizon, keyed by fixture_id -> gw.
  locked -- comma-separated player_ids that MUST be in the squad (e.g.
    "want Haaland regardless of what the model ranks him"). See
    optimise.build_initial_squad's docstring for how this interacts with
    the other constraints.
"""
from fastapi import APIRouter, HTTPException, Query

from app.config import CURRENT_SEASON
from app.services.db import query_df, get_connection

import optimise

router = APIRouter(prefix="/api/squad", tags=["squad"])

# See user's own reasoning, verbatim: "easy fixtures often means points AND
# you can keep them for longer". The xP for the SELECTED window already
# reflects fixture difficulty within that window (Dixon-Coles uses the
# specific opponent's rating per fixture) -- that part needed no change.
# What was genuinely missing: nothing rewarded a player whose fixtures STAY
# easy just past the selected window, i.e. a squad pick you won't need to
# transfer out again soon. LOOKAHEAD_WEEKS/WEIGHT add exactly that, as a
# separate score used ONLY to influence which players the optimizer picks --
# the numbers actually shown to the user (total_xp, per-player xP) stay the
# true, undistorted figure for the window they asked for. Values are a
# documented judgment call (a few weeks, modest weight), not learned from
# data -- same honesty standard as BENCH_WEIGHT in optimise.py.
LOOKAHEAD_WEEKS = 3
LOOKAHEAD_WEIGHT = 0.3


def _load_pool(run_id: int, gw_start: int | None, gw_end: int | None):
    sql = """SELECT p.player_id, p.name, p.position, ps.team_id, t.name AS team, t.code AS team_code,
                    ps.price_end AS price, mp.predicted_points AS xP
             FROM model_predictions mp
             JOIN players p ON mp.player_id = p.player_id
             JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
             JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?
             JOIN fixtures f ON f.fixture_id = mp.fixture_id
             WHERE mp.run_id = ?"""
    params: tuple = (CURRENT_SEASON, CURRENT_SEASON, run_id)
    if gw_start is not None:
        sql += " AND f.gw >= ?"
        params += (gw_start,)
    if gw_end is not None:
        sql += " AND f.gw <= ?"
        params += (gw_end,)

    df = query_df(sql, params)
    # RULE FIX: sums across every fixture in the range for a player -- correctly
    # handles both a multi-gameweek horizon AND double-gameweeks within it (see
    # docs/GOTCHAS.md), since both just mean "more than one row for this player".
    return df.groupby(
        ["player_id", "name", "position", "team_id", "team", "team_code", "price"], as_index=False
    )["xP"].sum()


def _add_selection_score(pool, run_id: int, gw_end: int | None):
    """selection_score = xP + LOOKAHEAD_WEIGHT * (summed xP over the next
    LOOKAHEAD_WEEKS gameweeks after gw_end). Used ONLY as the ILP's objective
    (see module-level comment) -- never returned to the user as a real xP
    number. If gw_end is None (no explicit end -- using the full predicted
    horizon already), there's nothing beyond it to look ahead into, so
    selection_score just equals xP."""
    if gw_end is None:
        pool = pool.copy()
        pool["selection_score"] = pool["xP"]
        return pool
    lookahead_pool = _load_pool(run_id, gw_end + 1, gw_end + LOOKAHEAD_WEEKS)
    lookahead_xp = lookahead_pool.set_index("player_id")["xP"]
    pool = pool.copy()
    pool["selection_score"] = pool["xP"] + LOOKAHEAD_WEIGHT * pool["player_id"].map(lookahead_xp).fillna(0)
    return pool


def _serialize(run_id, gw_start, gw_end, squad_df, lineup, extra=None):
    # starter_ids/bench_ids are the AUTHORITATIVE fields -- matching on names is
    # fragile (this project found real accent-encoding bugs splitting player
    # records by name earlier this session, see docs/GOTCHAS.md). Names are
    # kept too since some callers/tests already read them, but the frontend
    # should use the id lists.
    starters_df = lineup["starters"]
    bench_df = lineup["bench"]
    out = {
        "run_id": run_id, "gw_start": gw_start, "gw_end": gw_end,
        "total_cost": float(squad_df["price"].sum()),
        "total_xp": float(squad_df["xP"].sum()),
        "squad": squad_df.to_dict(orient="records"),
        "lineup": {
            "formation": lineup["formation"],
            "captain": lineup["captain"],
            "vice_captain": lineup["vice_captain"],
            "expected_points": float(lineup["expected_points"]),
            "expected_points_with_captain": float(lineup["expected_points_with_captain"]),
            "starters": starters_df["name"].tolist(),
            "bench": bench_df["name"].tolist(),
            "starter_ids": starters_df["player_id"].astype(int).tolist(),
            "bench_ids": bench_df["player_id"].astype(int).tolist(),
        },
    }
    if extra:
        out.update(extra)
    return out


@router.get("/optimal")
def optimal_squad(
    gw_start: int | None = Query(None, description="First gameweek to include (inclusive)"),
    gw_end: int | None = Query(None, description="Last gameweek to include (inclusive)"),
    locked: str | None = Query(None, description="Comma-separated player_ids that must be included"),
):
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, "No predictions available yet -- run predict_upcoming.py first")

    pool = _load_pool(row["run_id"], gw_start, gw_end)
    pool = _add_selection_score(pool, row["run_id"], gw_end)
    locked_ids = [int(pid) for pid in locked.split(",") if pid.strip()] if locked else []

    # Joint squad+lineup optimizer (see optimise.py's docstring) -- fixes a real
    # objective bug found via user feedback: the old two-stage approach valued
    # all 15 squad players equally, when only 11 actually score points.
    # score_col='selection_score' (not 'xP') so the OPTIMIZER also rewards
    # fixtures staying easy past the window -- but the numbers reported below
    # are recomputed from the true 'xP' column, so what's shown to the user
    # never gets inflated by the lookahead (see _add_selection_score's docstring).
    result = optimise.build_optimal_squad_and_lineup(
        pool, score_col="selection_score", locked_player_ids=locked_ids
    )
    if result["status"] == "PlayerNotFound":
        raise HTTPException(400, f"Locked player_id(s) not found: {result['missing_player_ids']}")
    if result["squad"] is None:
        raise HTTPException(
            409, f"No valid squad exists under budget/position/club rules with these locks "
                 f"(solver status: {result['status']})"
        )

    # Use the joint optimizer ONLY for which 15 players to buy (x_i) -- that's
    # the genuinely long-term decision the lookahead should influence. Which
    # 11 of them START, and who's captain, is purely about points THIS
    # window, so re-derive that independently from the TRUE 'xP' column
    # rather than trusting the selection_score-based y_i the optimizer
    # returned. Cheap and exact -- best_lineup() is greedy formation search,
    # see optimise.py's own docstring for why that's provably correct.
    result["lineup"] = optimise.best_lineup(result["squad"], score_col="xP")

    return _serialize(row["run_id"], gw_start, gw_end, result["squad"], result["lineup"],
                       extra={"locked_player_ids": locked_ids})


@router.get("/lineup")
def lineup_for_squad(
    player_ids: str = Query(..., description="Comma-separated player_ids -- exactly 15, any combination"),
    gw_start: int | None = Query(None),
    gw_end: int | None = Query(None),
):
    """Given an ARBITRARY 15 players (e.g. after a manual remove/replace edit
    in the UI), return their xP + the best lineup for that exact squad. No
    ILP here -- best_lineup() is exact greedy formation search (see
    optimise.py's module docstring for why that's provably correct, unlike
    squad-from-scratch selection), so this is cheap and deterministic even
    though the squad itself wasn't chosen by the optimizer this time."""
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, "No predictions available yet -- run predict_upcoming.py first")

    ids = [int(pid) for pid in player_ids.split(",") if pid.strip()]
    if len(ids) != 15:
        raise HTTPException(400, f"Expected exactly 15 player_ids, got {len(ids)}")

    pool = _load_pool(row["run_id"], gw_start, gw_end)
    squad = pool[pool["player_id"].isin(ids)]
    missing = set(ids) - set(squad["player_id"])
    if missing:
        raise HTTPException(400, f"player_id(s) not found in current predictions: {sorted(missing)}")

    counts = squad["position"].value_counts().to_dict()
    for pos, n in optimise.SQUAD_LIMITS.items():
        if counts.get(pos, 0) != n:
            raise HTTPException(400, f"Invalid squad shape: {counts} (need {optimise.SQUAD_LIMITS})")

    lineup = optimise.best_lineup(squad)
    return _serialize(row["run_id"], gw_start, gw_end, squad, lineup)
