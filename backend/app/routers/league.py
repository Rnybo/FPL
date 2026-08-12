"""GET /api/league/{league_id} -- proxies FPL's public classic-league
standings. No auth needed, no user accounts needed on our side either (see
README.md's design note): a friend just pastes their real league ID.
"""
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/league", tags=["league"])
FPL_BASE = "https://fantasy.premierleague.com/api"


@router.get("/{league_id}")
async def get_league(league_id: int):
    url = f"{FPL_BASE}/leagues-classic/{league_id}/standings/"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"FPL API error fetching league {league_id}")

    data = resp.json()
    league_name = data.get("league", {}).get("name")
    standings = [
        {
            "rank": e["rank"],
            "manager_name": e["player_name"],
            "team_name": e["entry_name"],
            "team_id": e["entry"],
            "total_points": e["total"],
        }
        for e in data.get("standings", {}).get("results", [])
    ]
    return {"league_id": league_id, "league_name": league_name, "standings": standings}
