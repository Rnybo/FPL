"""GET /api/team/{team_id} -- a real manager's public overview, and (once
picks are published -- not before a gameweek kicks off, see claude.md/
api-reference.md) their squad matched to our own player data, plus our own
best lineup for it and personalized transfer suggestions.

Matching is done via `code` (FPL's stable Opta id, present on both
bootstrap-static elements and our own players table) rather than name --
see docs/GOTCHAS.md's encoding/duplicate-name bugs that name-matching used
to hit. This was previously deferred ("NOT YET WIRED") because picks can't
be fetched/tested until a real gameweek is live; the 2026-27 season's GW1
deadline (2026-08-21) hasn't passed as of this writing, so `squad_published`
will be false for everyone until then -- that's real API behavior, not a
bug here, and is exercised by test_team.py via a monkeypatched fetch rather
than waiting for the season.
"""
import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.config import CURRENT_SEASON
from app.services.db import query_df, get_connection

import optimise
from apply_live_status_override import load_live_status, STATUS_LABELS, UNAVAILABLE_STATUSES, set_piece_roles

router = APIRouter(prefix="/api/team", tags=["team"])
FPL_BASE = "https://fantasy.premierleague.com/api"


async def _fetch_json(url: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code == 200 else None)


def _status_df():
    """Current live availability, one row per player_id -- see squad.py's
    identical helper for the full reasoning (duplicated here rather than
    imported cross-router, matching this project's existing pattern of
    small per-router duplication, e.g. LAST_COMPLETE_SEASON)."""
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
    pool = pool.merge(_status_df(), on="player_id", how="left")
    pool["status"] = pool["status"].fillna("a")
    pool["status_label"] = pool["status_label"].fillna(STATUS_LABELS["a"])
    pool["chance_of_playing_next_round"] = pool["chance_of_playing_next_round"].astype(object).where(
        pool["chance_of_playing_next_round"].notna(), None
    )
    pool["set_piece_roles"] = pool["set_piece_roles"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    return pool


def _load_pool(run_id: int) -> pd.DataFrame:
    """Full current-season candidate pool -- player_id, name, position, code,
    team, team_code, price, xP -- summed across the model's full predicted
    horizon (no gw filter, unlike squad.py's windowed version, since "my
    team" isn't scoped to one optimizer session's chosen window). Same
    column shape squad.py's pool uses, so optimise.best_lineup/
    suggest_transfers work against it unmodified."""
    sql = """SELECT p.player_id, p.name, p.position, p.code, ps.team_id, t.name AS team, t.code AS team_code,
                    ps.price_end AS price, mp.predicted_points AS xP
             FROM model_predictions mp
             JOIN players p ON mp.player_id = p.player_id
             JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
             JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?
             WHERE mp.run_id = ?"""
    df = query_df(sql, (CURRENT_SEASON, CURRENT_SEASON, run_id))
    pool = df.groupby(
        ["player_id", "name", "position", "code", "team_id", "team", "team_code", "price"], as_index=False
    )["xP"].sum()
    return _add_status(pool)


def _latest_run_id() -> int | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["run_id"] if row else None


def _load_per_gw_xp(run_id: int, gw_start: int, gw_end: int) -> pd.DataFrame:
    """player_id, gw, xP for every predicted fixture in [gw_start, gw_end] --
    same shape/reasoning as squad.py's _load_per_gw (duplicated here, not
    imported, matching this project's own small-duplication-over-cross-
    router-imports convention). plan_horizon needs each gameweek's OWN
    number, not the summed-across-window total _load_pool returns."""
    sql = """SELECT mp.player_id, f.gw, mp.predicted_points AS xP
             FROM model_predictions mp
             JOIN fixtures f ON f.fixture_id = mp.fixture_id
             WHERE mp.run_id = ? AND f.gw >= ? AND f.gw <= ?"""
    df = query_df(sql, (run_id, gw_start, gw_end))
    if df.empty:
        return df
    return df.groupby(["player_id", "gw"], as_index=False)["xP"].sum()  # double-GW-safe within a single gw


@router.get("/{team_id}")
async def get_team(team_id: int):
    status, overview = await _fetch_json(f"{FPL_BASE}/entry/{team_id}/")
    if status != 200:
        raise HTTPException(status, f"FPL API error fetching manager {team_id}")

    bootstrap_status, bootstrap = await _fetch_json(f"{FPL_BASE}/bootstrap-static/")
    current_gw = next((e["id"] for e in bootstrap["events"] if e["is_current"]), None) if bootstrap else None

    result = {
        "team_id": team_id,
        "manager_name": f"{overview.get('player_first_name', '')} {overview.get('player_last_name', '')}".strip(),
        "team_name": overview.get("name"),
        "overall_rank": overview.get("summary_overall_rank"),
        "total_points": overview.get("summary_overall_points"),
        "squad_published": False,
        "bank": None,
        "picks": None,
        "lineup": None,
        "suggestions": None,
    }

    if current_gw is None:
        result["note"] = "Season hasn't started yet -- no current gameweek, squad picks not published"
        return result

    picks_status, picks_data = await _fetch_json(f"{FPL_BASE}/entry/{team_id}/event/{current_gw}/picks/")
    if picks_status != 200:
        result["note"] = f"Squad not published yet for GW{current_gw} (normal before that gameweek's deadline)"
        return result

    result["squad_published"] = True
    result["bank"] = picks_data.get("entry_history", {}).get("bank", 0) / 10

    element_to_code = {el["id"]: el["code"] for el in bootstrap["elements"]}
    selling_price_by_code = {
        element_to_code[p["element"]]: p["selling_price"] / 10
        for p in picks_data["picks"] if p["element"] in element_to_code
    }

    run_id = _latest_run_id()
    if run_id is None:
        result["note"] = "Squad published, but no predictions available yet to match against"
        return result

    pool = _load_pool(run_id)
    squad_df = pool[pool["code"].isin(selling_price_by_code)].copy()
    squad_df["selling_price"] = squad_df["code"].map(selling_price_by_code)

    matched = len(squad_df)
    result["picks"] = squad_df.drop(columns=["code"]).to_dict(orient="records")
    result["note"] = f"GW{current_gw} squad, {matched}/{len(selling_price_by_code)} players matched to our data"

    if matched != 15:
        return result  # can't compute a lineup/suggestions from a partial squad

    lineup = optimise.best_lineup(squad_df, score_col="xP")
    result["lineup"] = {
        "formation": lineup["formation"],
        "captain": lineup["captain"],
        "vice_captain": lineup["vice_captain"],
        "expected_points": float(lineup["expected_points"]),
        "expected_points_with_captain": float(lineup["expected_points_with_captain"]),
        "starter_ids": lineup["starters"]["player_id"].astype(int).tolist(),
        "bench_ids": lineup["bench"]["player_id"].astype(int).tolist(),
    }

    # Real transfer economics: what you'd actually recoup for each owned
    # player is their selling_price (can be LESS than current price -- FPL
    # only refunds half of any rise since you bought), not the current
    # listed price -- so suggest_transfers runs against a copy with `price`
    # swapped to selling_price. The candidate pool keeps current price
    # (that's what buying them would actually cost).
    squad_for_transfers = squad_df.drop(columns=["price"]).rename(columns={"selling_price": "price"})
    # Never suggest bringing IN an injured/suspended/unavailable player --
    # this only filters the INCOMING candidates; the person's own existing
    # squad_df above is left untouched (can't retroactively un-own a real
    # player, and they still need to see it -- and be able to sell it -- if
    # one of their own picks gets hurt).
    available_candidates = pool[~pool["status"].isin(UNAVAILABLE_STATUSES)]
    suggestions = optimise.suggest_transfers(squad_for_transfers, available_candidates, result["bank"])
    result["suggestions"] = suggestions.to_dict(orient="records")

    return result


@router.get("/{team_id}/plan")
async def get_team_plan(
    team_id: int,
    gw_start: int | None = Query(None, description="First gameweek to plan (default: current gameweek)"),
    horizon: int = Query(5, ge=1, le=15, description="Number of gameweeks to plan"),
    free_transfers: int = Query(1, ge=0, le=optimise.MAX_BANKED_FREE_TRANSFERS,
                                 description="Free transfers currently banked, before this window"),
    min_gain: float = Query(2.0, description="Minimum xP gain (over the lookahead window) to justify a transfer"),
    allow_hits: bool = Query(False, description="Allow -4pt hits for transfers beyond the free ones, when worth it"),
    hit_cost: float = Query(4.0, ge=0, description="Points deducted per hit (real FPL rule: 4)"),
):
    """Round-by-round game plan across `horizon` gameweeks: lineup/captain
    each week plus greedy transfer decisions (free first, then optional
    point hits), built on optimise.plan_horizon (see its docstring -- greedy
    round-by-round, matches this module's own honesty standard for
    suggest_transfers). Reuses the same squad-matching flow as GET
    /api/team/{team_id} -- duplicated rather than refactored into a shared
    helper, since that endpoint is tested and working (small duplication
    over cross-router/cross-endpoint imports, per this project's own
    convention)."""
    status, overview = await _fetch_json(f"{FPL_BASE}/entry/{team_id}/")
    if status != 200:
        raise HTTPException(status, f"FPL API error fetching manager {team_id}")

    bootstrap_status, bootstrap = await _fetch_json(f"{FPL_BASE}/bootstrap-static/")
    current_gw = next((e["id"] for e in bootstrap["events"] if e["is_current"]), None) if bootstrap else None
    if current_gw is None:
        raise HTTPException(409, "Season hasn't started yet -- no current gameweek, squad picks not published")

    picks_status, picks_data = await _fetch_json(f"{FPL_BASE}/entry/{team_id}/event/{current_gw}/picks/")
    if picks_status != 200:
        raise HTTPException(409, f"Squad not published yet for GW{current_gw} (normal before that gameweek's deadline)")

    bank = picks_data.get("entry_history", {}).get("bank", 0) / 10
    element_to_code = {el["id"]: el["code"] for el in bootstrap["elements"]}
    selling_price_by_code = {
        element_to_code[p["element"]]: p["selling_price"] / 10
        for p in picks_data["picks"] if p["element"] in element_to_code
    }

    run_id = _latest_run_id()
    if run_id is None:
        raise HTTPException(404, "No predictions available yet -- run predict_upcoming.py first")

    pool = _load_pool(run_id)
    squad_df = pool[pool["code"].isin(selling_price_by_code)].copy()
    squad_df["selling_price"] = squad_df["code"].map(selling_price_by_code)
    matched = len(squad_df)
    if matched != 15:
        raise HTTPException(
            409, f"Only {matched}/15 squad players matched to our data -- can't plan from a partial squad"
        )
    squad_df = squad_df.drop(columns=["code"])

    start = gw_start if gw_start is not None else current_gw
    gameweeks = list(range(start, start + horizon))
    per_gw_xp = _load_per_gw_xp(run_id, start, gameweeks[-1] + optimise.PLAN_LOOKAHEAD_WEEKS)

    # Never suggest bringing IN an injured/suspended/unavailable player --
    # same reasoning as get_team's suggestions above. plan_horizon itself
    # excludes anyone already in squad_df from candidates (by player_id), so
    # no separate filter for that is needed here.
    candidates = pool[~pool["status"].isin(UNAVAILABLE_STATUSES)].drop(columns=["code"])

    plan = optimise.plan_horizon(
        squad_df, candidates, per_gw_xp, gameweeks, bank,
        free_transfers=free_transfers, min_gain=min_gain,
        allow_hits=allow_hits, hit_cost=hit_cost,
    )

    return {
        "team_id": team_id,
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
                # Full per-round squad (name/team/position/price) -- needed
                # client-side to render anyone the plan transferred IN, who
                # won't be present in the original GET /api/team picks list.
                "squad": pd.concat([step["starters"], step["bench"]])[
                    ["player_id", "name", "position", "team", "price"]
                ].to_dict(orient="records"),
                "transfers_in": step["transfers_in"],
                "transfers_out": step["transfers_out"],
                "transfers_in_names": step["transfers_in_names"],
                "transfers_out_names": step["transfers_out_names"],
                # The last `hits_taken` entries of transfers_in/out above are
                # the paid ones -- everything before that was free.
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
