"""GET /api/team/{team_id} -- a real manager's public overview, and (once
picks are published -- not before a gameweek kicks off, see claude.md/
api-reference.md) their squad matched to our own player data.

NOT YET WIRED: personalized transfer suggestions (optimise.suggest_transfers
against this squad + our xP candidates). The picks endpoint returns nothing
until a real gameweek is live, so this can't be tested yet either -- adding
the suggestion logic now would be untested code pretending to work. Wire it
once the season starts and a real squad can be fetched to test against.
"""
import httpx
from fastapi import APIRouter, HTTPException

from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/team", tags=["team"])
FPL_BASE = "https://fantasy.premierleague.com/api"


async def _fetch_json(url: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    return resp.status_code, (resp.json() if resp.status_code == 200 else None)


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
        "picks": None,
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
    element_ids = [p["element"] for p in picks_data["picks"]]

    our_players = query_df(
        """SELECT p.player_id, p.name, p.position, t.name AS team, ps.price_end AS price
           FROM players p
           JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
           JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?""",
        (CURRENT_SEASON, CURRENT_SEASON),
    )
    bootstrap_names = {el["id"]: f"{el['first_name']} {el['second_name']}".strip() for el in bootstrap["elements"]}
    name_to_row = {row["name"]: row for _, row in our_players.iterrows()}

    squad_rows = []
    for pid in element_ids:
        name = bootstrap_names.get(pid)
        match = name_to_row.get(name)
        if match is not None:
            squad_rows.append(match.to_dict())
    result["picks"] = squad_rows
    result["note"] = f"GW{current_gw} squad, {len(squad_rows)}/{len(element_ids)} players matched to our data"
    return result
