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
from fastapi import APIRouter, HTTPException

from app.config import CURRENT_SEASON
from app.services.db import query_df, get_connection

import optimise

router = APIRouter(prefix="/api/team", tags=["team"])
FPL_BASE = "https://fantasy.premierleague.com/api"


async def _fetch_json(url: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code == 200 else None)


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
    return df.groupby(
        ["player_id", "name", "position", "code", "team_id", "team", "team_code", "price"], as_index=False
    )["xP"].sum()


def _latest_run_id() -> int | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["run_id"] if row else None


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
    suggestions = optimise.suggest_transfers(squad_for_transfers, pool, result["bank"])
    result["suggestions"] = suggestions.to_dict(orient="records")

    return result
