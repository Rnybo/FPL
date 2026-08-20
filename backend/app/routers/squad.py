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
import pandas as pd

from app.config import CURRENT_SEASON
from app.services.db import query_df, get_connection

import optimise
from apply_live_status_override import load_live_status, STATUS_LABELS, UNAVAILABLE_STATUSES, set_piece_roles

router = APIRouter(prefix="/api/squad", tags=["squad"])


def _parse_formation(s: str) -> dict:
    """"D-M-F" (e.g. "4-4-2") -> {"GK":1,"DEF":D,"MID":M,"FWD":F}. GK is
    omitted from the string since it's always exactly 1 in FPL -- matches
    common football shorthand rather than inventing a new format."""
    parts = s.split("-")
    if len(parts) != 3 or not all(p.strip().isdigit() for p in parts):
        raise HTTPException(400, f"Invalid formation {s!r} -- expected 'DEF-MID-FWD', e.g. '4-4-2'")
    d, m, f = (int(p) for p in parts)
    return {"GK": 1, "DEF": d, "MID": m, "FWD": f}

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


def _status_df():
    """Current live availability, one row per player_id -- status code,
    human label, chance of playing next round, and set-piece duty (e.g.
    ["Pen1", "DF2"]). Joined onto the candidate pool so injured/suspended
    players can be (a) hard-excluded from the optimizer's picks and (b)
    still flagged for display when they slip through via an explicit lock.
    Not cached here (unlike players.py/performance.py's own versions) --
    this router's whole pool query already runs fresh on every request (see
    module docstring: "no caching needed yet"), so a fresh status read costs
    nothing extra relatively."""
    conn = get_connection()
    try:
        live = load_live_status(conn)
    finally:
        conn.close()
    live["status"] = live["status"].fillna("a")
    live["status_label"] = live["status"].map(STATUS_LABELS).fillna(live["status"])
    live["set_piece_roles"] = live.apply(set_piece_roles, axis=1)
    return live[["player_id", "status", "status_label", "chance_of_playing_next_round", "set_piece_roles"]]


def _add_status(pool):
    """Left-joins status onto a candidate pool, defaulting missing rows
    (no live-status row at all) to 'a'/Available -- same reasoning as
    players.py's _status_by_player. chance_of_playing_next_round is
    replaced with plain Python None (not NaN) via .where() so the eventual
    .to_dict(orient="records") is directly JSON-safe -- a raw float NaN
    isn't valid JSON and can trip FastAPI's encoder (same trap already
    hit/fixed once in performance.py's _json_safe)."""
    pool = pool.merge(_status_df(), on="player_id", how="left")
    pool["status"] = pool["status"].fillna("a")
    pool["status_label"] = pool["status_label"].fillna(STATUS_LABELS["a"])
    pool["chance_of_playing_next_round"] = pool["chance_of_playing_next_round"].astype(object).where(
        pool["chance_of_playing_next_round"].notna(), None
    )
    # A player absent from live_player_status entirely merges in as NaN
    # (float), not a missing list -- .apply() with isna() replaces those
    # specifically (a real, present list must not be touched: `if x` on a
    # non-empty list is fine, but pd.isna() on a list raises, so isinstance
    # is checked first).
    pool["set_piece_roles"] = pool["set_piece_roles"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    return pool


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
    pool = df.groupby(
        ["player_id", "name", "position", "team_id", "team", "team_code", "price"], as_index=False
    )["xP"].sum()
    return _add_status(pool)


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


def _load_per_gw(run_id: int, gw_start: int | None, gw_end: int | None):
    """Same base data as _load_pool, but grouped by (player_id, gw) instead of
    summed across the whole window -- needed for anything that cares about
    an INDIVIDUAL gameweek's number rather than the window total (the
    captain ceiling bonus below, and the client-side captaincy draft plan --
    see PlayerScout/SquadBuilder's own per-gameweek data, which is the exact
    same shape as this)."""
    sql = """SELECT mp.player_id, f.gw, mp.predicted_points AS xP
             FROM model_predictions mp
             JOIN fixtures f ON f.fixture_id = mp.fixture_id
             WHERE mp.run_id = ?"""
    params: tuple = (run_id,)
    if gw_start is not None:
        sql += " AND f.gw >= ?"
        params += (gw_start,)
    if gw_end is not None:
        sql += " AND f.gw <= ?"
        params += (gw_end,)
    df = query_df(sql, params)
    if df.empty:
        return df
    return df.groupby(["player_id", "gw"], as_index=False)["xP"].sum()  # double-GW-safe within a single gw


# Captaincy matters: whoever captains a gameweek scores DOUBLE that week, so
# a squad with at least one genuine single-week standout is worth more than
# the same total spread flatly across 15 consistent-but-unspectacular
# players. CAPTAIN_CEILING_WEIGHT nudges squad SELECTION toward that --
# a documented judgment call, not learned from data, same honesty standard
# as LOOKAHEAD_WEIGHT/BENCH_WEIGHT elsewhere in this pipeline.
CAPTAIN_CEILING_WEIGHT = 0.3


def _captain_ceiling_from_per_gw(pool, per_gw):
    """Pure logic split out from _add_captain_ceiling_bonus below so it's
    testable with synthetic per-gw data, no DB round-trip needed -- see
    tests/test_squad.py."""
    if per_gw.empty:
        return pool
    ceiling = per_gw.groupby("player_id")["xP"].max()
    pool = pool.copy()
    pool["selection_score"] = pool["selection_score"] + CAPTAIN_CEILING_WEIGHT * pool["player_id"].map(ceiling).fillna(0)
    return pool


def _add_captain_ceiling_bonus(pool, run_id: int, gw_start: int | None, gw_end: int | None):
    """Adds CAPTAIN_CEILING_WEIGHT * (player's own best single gameweek in
    the window) to selection_score -- added ONLY to the optimizer's objective
    (never shown as real xP, same convention as _add_selection_score above).

    This is a documented APPROXIMATION: each player's OWN peak week, not an
    exact joint optimization of "who captains which specific week" (that
    would need one binary captain-variable per player per gameweek inside
    the ILP). Deliberately not built that way -- captaincy is inherently a
    week-by-week decision independent of this window's one-shot squad
    choice, exactly like the real game (you keep your squad, but repick
    captain every week). The EXACT per-week version -- which squad member
    actually has the biggest number in gameweek N specifically -- is
    computed separately and precisely once a squad exists, from the same
    per-gameweek breakdown already returned by GET /api/players (see
    SquadBuilder's captaincy draft plan, built client-side from that data
    rather than needing a second backend round-trip)."""
    per_gw = _load_per_gw(run_id, gw_start, gw_end)
    return _captain_ceiling_from_per_gw(pool, per_gw)


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
    formation: str | None = Query(None, description="Force a specific formation, e.g. '4-4-2' (DEF-MID-FWD). Omit for the auto-optimal formation."),
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
    pool = _add_captain_ceiling_bonus(pool, row["run_id"], gw_start, gw_end)
    locked_ids = [int(pid) for pid in locked.split(",") if pid.strip()] if locked else []

    # Hard-exclude injured/suspended/unavailable players from AUTOMATIC
    # selection -- the model already suppresses their xP toward zero (see
    # apply_live_status_override.py), but that's a soft signal (a cheap
    # injured player could still get parked as a near-costless bench filler,
    # and the residual "expected_bonus" component isn't gated on p_played at
    # all). An explicit lock overrides this -- if the person specifically
    # wants to keep someone through a short injury, that's a deliberate
    # choice, not something this filter should silently override.
    unavailable_mask = pool["status"].isin(UNAVAILABLE_STATUSES) & ~pool["player_id"].isin(locked_ids)
    pool = pool[~unavailable_mask].reset_index(drop=True)

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
    forced_formation = _parse_formation(formation) if formation else None
    lineup = optimise.best_lineup(result["squad"], score_col="xP", formation=forced_formation)
    if lineup is None:
        raise HTTPException(400, f"Formation {formation!r} isn't feasible for this squad")
    result["lineup"] = lineup

    return _serialize(row["run_id"], gw_start, gw_end, result["squad"], result["lineup"],
                       extra={"locked_player_ids": locked_ids})


@router.get("/lineup")
def lineup_for_squad(
    player_ids: str = Query(..., description="Comma-separated player_ids -- exactly 15, any combination"),
    gw_start: int | None = Query(None),
    gw_end: int | None = Query(None),
    formation: str | None = Query(None, description="Force a specific formation, e.g. '4-4-2' (DEF-MID-FWD). Omit for the auto-optimal formation."),
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

    forced_formation = _parse_formation(formation) if formation else None
    lineup = optimise.best_lineup(squad, formation=forced_formation)
    if lineup is None:
        raise HTTPException(400, f"Formation {formation!r} isn't feasible for this squad")
    return _serialize(row["run_id"], gw_start, gw_end, squad, lineup)


@router.get("/plan")
def squad_plan(
    player_ids: str = Query(..., description="Comma-separated player_ids -- exactly 15, any combination"),
    gw_start: int | None = Query(None, description="First gameweek to plan (default: the earliest predicted gameweek)"),
    horizon: int = Query(5, ge=1, le=15, description="Number of gameweeks to plan"),
    free_transfers: int = Query(1, ge=0, le=optimise.MAX_BANKED_FREE_TRANSFERS,
                                 description="Free transfers banked at the start of the window"),
    min_gain: float = Query(2.0, description="Minimum xP gain (over the lookahead window) to justify a transfer"),
    allow_hits: bool = Query(False, description="Allow -4pt hits for transfers beyond the free ones, when worth it"),
    hit_cost: float = Query(4.0, ge=0, description="Points deducted per hit (real FPL rule: 4)"),
    budget: float = Query(100.0, ge=0, description="Total squad budget -- starting bank = budget minus this squad's own cost"),
):
    """The 'Drejebog' -- a round-by-round playbook (starting XI, captain,
    substitutions, transfers) across a multi-gameweek horizon for a squad
    that's being BUILT here (not yet a real FPL team), so there's no actual
    manager bank/free-transfer count to query -- starting bank is `budget`
    minus this exact squad's own cost, and free_transfers is whatever the
    person says they're planning around (1 going into GW1 for everyone,
    same as real FPL). Same engine as team.py's GET /{team_id}/plan
    (optimise.plan_horizon -- see its docstring for exactly how it decides:
    greedy, round-by-round, free transfers first then optional real -4
    hits). Duplicated serialization/wiring rather than shared with team.py,
    per this project's own small-duplication-over-cross-router-imports
    convention."""
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, "No predictions available yet -- run predict_upcoming.py first")
    run_id = row["run_id"]

    ids = [int(pid) for pid in player_ids.split(",") if pid.strip()]
    if len(ids) != 15:
        raise HTTPException(400, f"Expected exactly 15 player_ids, got {len(ids)}")

    if gw_start is None:
        earliest = query_df(
            """SELECT MIN(f.gw) AS gw FROM model_predictions mp
               JOIN fixtures f ON f.fixture_id = mp.fixture_id WHERE mp.run_id = ?""",
            (run_id,),
        )
        gw_start = int(earliest["gw"].iloc[0]) if not earliest.empty and earliest["gw"].iloc[0] is not None else 1

    pool = _load_pool(run_id, gw_start, None)
    squad_df = pool[pool["player_id"].isin(ids)].copy()
    missing = set(ids) - set(squad_df["player_id"])
    if missing:
        raise HTTPException(400, f"player_id(s) not found in current predictions: {sorted(missing)}")
    counts = squad_df["position"].value_counts().to_dict()
    for pos, n in optimise.SQUAD_LIMITS.items():
        if counts.get(pos, 0) != n:
            raise HTTPException(400, f"Invalid squad shape: {counts} (need {optimise.SQUAD_LIMITS})")

    bank = budget - float(squad_df["price"].sum())
    if bank < -1e-6:
        raise HTTPException(
            400, f"This squad costs £{squad_df['price'].sum():.1f}m, over the £{budget:.1f}m budget"
        )

    gameweeks = list(range(gw_start, gw_start + horizon))
    per_gw_xp = _load_per_gw(run_id, gw_start, gameweeks[-1] + optimise.PLAN_LOOKAHEAD_WEEKS)

    # Never suggest bringing IN an injured/suspended/unavailable player --
    # same reasoning as /optimal's hard-exclude above. plan_horizon itself
    # excludes anyone already in squad_df from candidates (by player_id).
    candidates = pool[~pool["player_id"].isin(ids) & ~pool["status"].isin(UNAVAILABLE_STATUSES)]

    plan = optimise.plan_horizon(
        squad_df, candidates, per_gw_xp, gameweeks, bank,
        free_transfers=free_transfers, min_gain=min_gain,
        allow_hits=allow_hits, hit_cost=hit_cost,
    )

    return {
        "gameweeks": gameweeks,
        "starting_bank": bank,
        "starting_free_transfers": free_transfers,
        "allow_hits": allow_hits,
        "hit_cost": hit_cost,
        "plan": [
            {
                "gameweek": step["gameweek"],
                "formation": step["formation"],
                "captain": step["captain"],
                "vice_captain": step["vice_captain"],
                "starter_ids": step["starters"]["player_id"].astype(int).tolist(),
                "bench_ids": step["bench"]["player_id"].astype(int).tolist(),
                "squad": pd.concat([step["starters"], step["bench"]])[
                    ["player_id", "name", "position", "team", "price"]
                ].to_dict(orient="records"),
                "transfers_in": step["transfers_in"],
                "transfers_out": step["transfers_out"],
                "transfers_in_names": step["transfers_in_names"],
                "transfers_out_names": step["transfers_out_names"],
                "hits_taken": step["hits_taken"],
                "free_transfers_after": step["free_transfers_after"],
                "bank_after": step["bank_after"],
                "expected_points": float(step["expected_points"]),
                "expected_points_with_captain": float(step["expected_points_with_captain"]),
                "expected_points_after_hits": float(step["expected_points_after_hits"]),
                "expected_points_with_captain_after_hits": float(step["expected_points_with_captain_after_hits"]),
            }
            for step in plan
        ],
    }
