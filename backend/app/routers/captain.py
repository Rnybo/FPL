"""GET /api/captain/picks -- wraps captain_simulation.py directly (no
duplicated Monte Carlo logic here), same pattern as squad.py wraps optimise.py.

Returns two ranked top-5 lists for a gameweek: safest (highest mean simulated
points) and haul gamble (highest P(>=10)). See captain_simulation.py's module
docstring for the modeling approach and documented simplifications.
"""
from fastapi import APIRouter, HTTPException, Query

from app.config import CURRENT_SEASON
from app.services.db import get_connection

import captain_simulation as cs

router = APIRouter(prefix="/api/captain", tags=["captain"])


def _next_unplayed_gw(conn) -> int | None:
    row = conn.execute(
        "SELECT MIN(gw) FROM fixtures WHERE season_id=? AND finished=0", (CURRENT_SEASON,)
    ).fetchone()
    return row[0] if row else None


@router.get("/picks")
def captain_picks(
    gw: int | None = Query(None, description="Gameweek to pick a captain for (default: next unplayed)"),
    candidates: int = Query(40, description="How many top-xP players to run the simulation over"),
    samples: int = Query(10000, description="Monte Carlo samples per player"),
    top_k: int = Query(5, description="How many players to return per list"),
):
    conn = get_connection()
    target_gw = gw if gw is not None else _next_unplayed_gw(conn)
    if target_gw is None:
        conn.close()
        raise HTTPException(404, "No upcoming fixtures found for the current season")

    try:
        safe, haul = cs.top_captain_picks(
            conn, target_gw, candidates_top_n=candidates, n_samples=samples, seed=0, top_k=top_k
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(404, str(e))
    conn.close()

    return {
        "gw": target_gw,
        "safe": safe.to_dict(orient="records"),
        "haul": haul.to_dict(orient="records"),
    }
