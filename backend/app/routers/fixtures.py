"""GET /api/fixtures -- upcoming fixture difficulty for the current season,
from our own cache (already loaded by fetch_upcoming_fixtures.py)."""
from fastapi import APIRouter, Query
from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])


@router.get("")
def list_fixtures(
    gw: int | None = None,
    gw_start: int | None = Query(None, description="First gameweek to include (inclusive) -- for an FDR strip over several gameweeks"),
    gw_end: int | None = Query(None, description="Last gameweek to include (inclusive)"),
):
    sql = """SELECT f.fixture_id, f.gw, f.kickoff_time, f.finished,
                     th.name AS home_team, ta.name AS away_team,
                     f.home_difficulty, f.away_difficulty,
                     f.home_goals, f.away_goals
              FROM fixtures f
              JOIN teams th ON f.home_team_id=th.team_id AND f.season_id=th.season_id
              JOIN teams ta ON f.away_team_id=ta.team_id AND f.season_id=ta.season_id
              WHERE f.season_id = ?"""
    params: tuple = (CURRENT_SEASON,)
    if gw is not None:
        sql += " AND f.gw = ?"
        params = params + (gw,)
    if gw_start is not None:
        sql += " AND f.gw >= ?"
        params = params + (gw_start,)
    if gw_end is not None:
        sql += " AND f.gw <= ?"
        params = params + (gw_end,)
    sql += " ORDER BY f.kickoff_time"
    df = query_df(sql, params)
    return {"season": CURRENT_SEASON, "fixtures": df.to_dict(orient="records")}
