"""GET /api/fixtures -- upcoming fixture difficulty for the current season,
from our own cache (already loaded by fetch_upcoming_fixtures.py). Also
attaches each side's clean-sheet probability from the current prediction
run where available (backs Fixture Swing's clean-sheet ranking), and a
top-level `recent_form` map of each current team's last 5 REAL results
(backs Fixture Swing's GF/game, GA/game columns).
"""
from fastapi import APIRouter, Query
from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])

RECENT_FORM_GAMES = 5


def _clean_sheet_prob_by_fixture_team() -> dict[tuple[int, int], float]:
    """{(fixture_id, team_id): p_clean_sheet} for the LATEST predict_upcoming
    run. p_clean_sheet in captain_sim_inputs is schema-documented as team-
    level -- every player on the same team shares an identical value for a
    given fixture (it's the TEAM's clean-sheet chance, not any individual
    player's) -- so any one player's value per (fixture, team) IS the
    team's own probability; .first() just picks one, all identical.
    Only covers fixtures within the current prediction run's horizon --
    fixtures beyond that, or already finished, simply won't have an entry
    here, handled as None by the caller.
    """
    latest_run = query_df(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    )
    if latest_run.empty:
        return {}
    run_id = int(latest_run.iloc[0]["run_id"])
    df = query_df(
        """SELECT csi.fixture_id, ps.team_id, csi.p_clean_sheet
           FROM captain_sim_inputs csi
           JOIN player_season ps ON ps.player_id = csi.player_id AND ps.season_id = ?
           WHERE csi.run_id = ?""",
        (CURRENT_SEASON, run_id),
    )
    if df.empty:
        return {}
    grouped = df.groupby(["fixture_id", "team_id"])["p_clean_sheet"].first()
    return {(int(fid), int(tid)): round(float(v), 3) for (fid, tid), v in grouped.items()}


def _recent_form_by_team(n: int = RECENT_FORM_GAMES) -> dict[str, dict]:
    """Last n REAL finished results per CURRENT team, spanning season
    boundaries if the current season doesn't have n finished games of its
    own yet -- e.g. right now, pre-season, CURRENT_SEASON has ZERO finished
    fixtures at all, so restricting this to CURRENT_SEASON only would leave
    every team with no recent-form data whatsoever. Pulling from the whole
    `fixtures` table (every season) and just taking the actual last n by
    kickoff_time naturally falls back to last season's closing games
    instead -- a team's "recent form" is a real, continuous thing that
    doesn't reset to a blank slate the moment a new season is created in
    the database, even before a ball's been kicked in it.

    Keyed by the team's CURRENT-season name -- team_id is the stable
    identity used for the actual lookup (same convention as players.py's
    _opponent_stats), but the frontend matches teams by name, same as
    buildFdrByTeam/buildTeamFixtureList on the frontend.
    """
    current_teams = query_df(
        "SELECT team_id, name FROM teams WHERE season_id = ?", (CURRENT_SEASON,)
    )
    if current_teams.empty:
        return {}

    all_finished = query_df(
        """SELECT home_team_id, away_team_id, home_goals, away_goals, kickoff_time
           FROM fixtures
           WHERE finished = 1 AND home_goals IS NOT NULL AND away_goals IS NOT NULL"""
    )
    if all_finished.empty:
        return {}

    out: dict[str, dict] = {}
    for row in current_teams.itertuples():
        team_id, name = row.team_id, row.name
        team_games = all_finished[
            (all_finished["home_team_id"] == team_id) | (all_finished["away_team_id"] == team_id)
        ].sort_values("kickoff_time")
        recent = team_games.tail(n)
        if recent.empty:
            continue
        gf, ga = [], []
        for r in recent.itertuples():
            if r.home_team_id == team_id:
                gf.append(r.home_goals)
                ga.append(r.away_goals)
            else:
                gf.append(r.away_goals)
                ga.append(r.home_goals)
        out[name] = {
            "gf_per_game": round(sum(gf) / len(gf), 2),
            "ga_per_game": round(sum(ga) / len(ga), 2),
            "games": len(gf),
        }
    return out


@router.get("")
def list_fixtures(
    gw: int | None = None,
    gw_start: int | None = Query(None, description="First gameweek to include (inclusive) -- for an FDR strip over several gameweeks"),
    gw_end: int | None = Query(None, description="Last gameweek to include (inclusive)"),
):
    sql = """SELECT f.fixture_id, f.gw, f.kickoff_time, f.finished,
                     th.name AS home_team, ta.name AS away_team,
                     f.home_team_id, f.away_team_id,
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

    cs_prob = _clean_sheet_prob_by_fixture_team()
    fixtures = []
    for row in df.to_dict(orient="records"):
        home_team_id = row.pop("home_team_id")
        away_team_id = row.pop("away_team_id")
        row["home_clean_sheet_prob"] = cs_prob.get((row["fixture_id"], home_team_id))
        row["away_clean_sheet_prob"] = cs_prob.get((row["fixture_id"], away_team_id))
        fixtures.append(row)

    return {"season": CURRENT_SEASON, "fixtures": fixtures, "recent_form": _recent_form_by_team()}
