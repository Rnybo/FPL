"""GET /api/fixtures -- upcoming fixture difficulty for the current season,
from our own cache (already loaded by fetch_upcoming_fixtures.py). Also
attaches:
  - each side's clean-sheet probability from the current prediction run
    (backs Team Scout's clean-sheet ranking)
  - `recent_form`: each current team's HOME and AWAY goal record separately
    (see _recent_form_by_team) -- backs Team Scout's "Home"/"Away" form split
  - `last_season_team_stats`: each current team's full LAST_COMPLETE_SEASON
    record -- goals/conceded by venue, clean sheets, favorable/unfavorable
    opponents (see _team_last_season_stats)
  - `goals_vs_opponent`: for each of the SELECTED gameweeks, the opponent and
    average goals this team scored/conceded against that SAME opponent across
    the last TEAM_GOALS_VS_OPPONENT_SEASONS complete seasons, home/away legs
    separate (see _team_goals_vs_opponent) -- mirrors players.py's
    points_vs_opponent_last_season at team level

IMPORTANT data quirk driving a design choice below: FPL's numeric team `id`
is NOT a stable per-club identifier across seasons -- it's reassigned each
season based on that season's 20 clubs (roughly alphabetical slot 1-20), so
the SAME id can be a completely different real club from one season to the
next (verified in this cache: id=11 has been Liverpool, Leeds, Liverpool,
Leicester, and Leeds again across five recent seasons). Anything joining
fixtures ACROSS seasons in this file therefore matches by team NAME, not
team_id -- names are what's actually stable for the same real club. Only
WITHIN a single season (e.g. CURRENT_SEASON's own upcoming-fixture lookups)
is team_id safe to use directly.
"""
from fastapi import APIRouter, Query
import pandas as pd
from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])

RECENT_FORM_GAMES = 5

# Most recent COMPLETE season -- matches players.py's constant of the same
# name/value (duplicated rather than imported, same low-risk pattern already
# established between players.py and captain_simulation.py/combine_xp.py).
LAST_COMPLETE_SEASON = "2025-26"

# How many favorable/unfavorable opponents to surface -- a normal season
# means each team faces ~19 different opponents (home+away), so "top 5"
# here means "best/worst 5 of those ~19," from a SINGLE season's games only
# (not the multi-season lookback players.py's own _opponent_stats uses --
# "last year's stats" was asked for literally here).
FAVORABLE_OPPONENTS_TOP_N = 5

# How many complete seasons _team_goals_vs_opponent looks back across for
# each specific upcoming opponent -- a club normally meets each opponent
# once per venue per season, so 3 seasons gives up to 3 meetings per leg to
# average over (fewer if the opponent's only been in the league part of
# that span, e.g. recently promoted).
TEAM_GOALS_VS_OPPONENT_SEASONS = 3


def _recent_season_ids(latest: str, n: int) -> list[str]:
    """['2025-26', '2024-25', '2023-24'] counting back n seasons from
    `latest` (inclusive). Duplicated from players.py's identical helper --
    same low-risk pattern already established between these two routers."""
    start_year = int(latest.split("-")[0])
    return [f"{start_year - i}-{str(start_year - i + 1)[-2:]}" for i in range(n)]


def _clean_sheet_prob_by_fixture_team() -> dict[tuple[int, int], float]:
    """{(fixture_id, team_id): p_clean_sheet} for the LATEST predict_upcoming
    run. p_clean_sheet in captain_sim_inputs is schema-documented as team-
    level -- every player on the same team shares an identical value for a
    given fixture (it's the TEAM's clean-sheet chance, not any individual
    player's) -- so any one player's value per (fixture, team) IS the
    team's own probability; .first() just picks one, all identical.
    Only covers fixtures within the current prediction run's horizon --
    fixtures beyond that, or already finished, simply won't have an entry
    here, handled as None by the caller. team_id here is safe -- this is
    entirely WITHIN CURRENT_SEASON, no cross-season comparison.
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


def _current_teams() -> pd.DataFrame:
    return query_df("SELECT team_id, name FROM teams WHERE season_id = ?", (CURRENT_SEASON,))


def _all_finished_with_names() -> pd.DataFrame:
    """Every finished fixture, ANY season, with both sides' names already
    joined in (not just team_ids) -- the join happens ONCE here rather than
    per-team in the callers below, and matching across seasons is by NAME
    from the start (see module docstring for why)."""
    return query_df(
        """SELECT th.name AS home_team, ta.name AS away_team,
                  f.home_goals, f.away_goals, f.kickoff_time
           FROM fixtures f
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
           WHERE f.finished = 1 AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL"""
    )


def _recent_form_by_team(n: int = RECENT_FORM_GAMES) -> dict[str, dict]:
    """Last n REAL finished results per CURRENT team, HOME and AWAY tracked
    SEPARATELY (not blended into one average) -- a team's home form and away
    form can genuinely differ, and since their NEXT fixture is specifically
    either home or away, a single blended number would obscure whichever
    split actually matters for it. Each split independently spans a season
    boundary if the current season doesn't have n finished games of its own
    at that venue yet -- e.g. right now, pre-season, CURRENT_SEASON has ZERO
    finished fixtures at all, so restricting this to CURRENT_SEASON only
    would leave every team with no recent-form data whatsoever. Matched by
    team NAME across seasons (see module docstring) -- team_id is NOT a
    safe cross-season key.
    """
    current_teams = _current_teams()
    if current_teams.empty:
        return {}

    all_finished = _all_finished_with_names()
    if all_finished.empty:
        return {}

    out: dict[str, dict] = {}
    for row in current_teams.itertuples():
        name = row.name
        home_games = all_finished[all_finished["home_team"] == name].sort_values("kickoff_time").tail(n)
        away_games = all_finished[all_finished["away_team"] == name].sort_values("kickoff_time").tail(n)
        if home_games.empty and away_games.empty:
            continue

        out[name] = {
            "home_gf_per_game": round(float(home_games["home_goals"].mean()), 2) if not home_games.empty else None,
            "home_ga_per_game": round(float(home_games["away_goals"].mean()), 2) if not home_games.empty else None,
            "home_games": int(len(home_games)),
            "away_gf_per_game": round(float(away_games["away_goals"].mean()), 2) if not away_games.empty else None,
            "away_ga_per_game": round(float(away_games["home_goals"].mean()), 2) if not away_games.empty else None,
            "away_games": int(len(away_games)),
        }
    return out


def _next_meeting_by_team() -> dict[tuple[int, int], int]:
    """{(team_id, opponent_id): next_gw} from CURRENT_SEASON's unplayed
    fixtures -- team_id is safe here, entirely WITHIN one season (no
    cross-season comparison) -- shared helper for _team_last_season_stats'
    favorable/unfavorable opponent entries, same convention as players.py's
    _opponent_stats."""
    upcoming = query_df(
        "SELECT gw, home_team_id, away_team_id FROM fixtures WHERE season_id = ? AND finished = 0",
        (CURRENT_SEASON,),
    )
    next_meeting: dict[tuple[int, int], int] = {}
    for r in upcoming.itertuples():
        for team_id, opp_id in ((r.home_team_id, r.away_team_id), (r.away_team_id, r.home_team_id)):
            key = (team_id, opp_id)
            if key not in next_meeting or r.gw < next_meeting[key]:
                next_meeting[key] = int(r.gw)
    return next_meeting


def _team_last_season_stats() -> dict[str, dict]:
    """Per CURRENT team, from LAST_COMPLETE_SEASON only (a single real
    season's record, not the multi-season blend _recent_form_by_team falls
    back to -- "stats for last year" is meant literally here):
      - goals for/against, split by venue
      - clean sheets, split by venue (+ total)
      - favorable/unfavorable opponents (top N each), ranked by average
        GOAL DIFFERENCE per meeting last season (a club normally meets each
        opponent exactly twice -- home and away -- so this is usually a
        2-game average, occasionally 1 if a fixture was voided/unplayed)
    A newly-promoted club with zero top-flight games last season is simply
    omitted (nothing meaningful to report), not included with all-zero stats.
    Matched by team NAME throughout the cross-season parts (see module
    docstring) -- team_id is only used for the next_gw lookup, which is
    entirely WITHIN CURRENT_SEASON and therefore safe.
    """
    current_teams = _current_teams()
    if current_teams.empty:
        return {}

    last_season_games = query_df(
        """SELECT th.name AS home_team, ta.name AS away_team, f.home_goals, f.away_goals
           FROM fixtures f
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
           WHERE f.season_id = ? AND f.finished = 1
                 AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL""",
        (LAST_COMPLETE_SEASON,),
    )
    if last_season_games.empty:
        return {}

    next_meeting = _next_meeting_by_team()
    current_team_id_by_name = dict(zip(current_teams["name"], current_teams["team_id"]))

    out: dict[str, dict] = {}
    for row in current_teams.itertuples():
        team_id, name = row.team_id, row.name
        home = last_season_games[last_season_games["home_team"] == name]
        away = last_season_games[last_season_games["away_team"] == name]
        if home.empty and away.empty:
            continue

        home_meetings = pd.DataFrame({
            "opponent": home["away_team"],
            "goal_diff": home["home_goals"] - home["away_goals"],
        })
        away_meetings = pd.DataFrame({
            "opponent": away["home_team"],
            "goal_diff": away["away_goals"] - away["home_goals"],
        })
        all_meetings = pd.concat([home_meetings, away_meetings])
        opp_avg = all_meetings.groupby("opponent")["goal_diff"].mean()
        opp_games = all_meetings.groupby("opponent")["goal_diff"].count()
        ranked = opp_avg.sort_values(ascending=False)

        def build_opp_entry(opp_name) -> dict:
            # None if the opponent isn't in the league THIS season (e.g.
            # relegated) -- team_id-based next_gw lookup only makes sense
            # for an opponent that still has a CURRENT_SEASON team_id.
            opp_current_id = current_team_id_by_name.get(opp_name)
            next_gw = next_meeting.get((team_id, opp_current_id)) if opp_current_id is not None else None
            return {
                "opponent": opp_name,
                "avg_goal_diff": round(float(opp_avg[opp_name]), 2),
                "games": int(opp_games[opp_name]),
                "next_gw": next_gw,
            }

        favorable = [build_opp_entry(opp) for opp in ranked.head(FAVORABLE_OPPONENTS_TOP_N).index]
        unfavorable = [build_opp_entry(opp) for opp in ranked.tail(FAVORABLE_OPPONENTS_TOP_N).index[::-1]]

        out[name] = {
            "goals_for_home": int(home["home_goals"].sum()),
            "goals_for_away": int(away["away_goals"].sum()),
            "goals_against_home": int(home["away_goals"].sum()),
            "goals_against_away": int(away["home_goals"].sum()),
            "clean_sheets_home": int((home["away_goals"] == 0).sum()),
            "clean_sheets_away": int((away["home_goals"] == 0).sum()),
            "clean_sheets_total": int((home["away_goals"] == 0).sum()) + int((away["home_goals"] == 0).sum()),
            "games_home": int(len(home)),
            "games_away": int(len(away)),
            "favorable_opponents": favorable,
            "unfavorable_opponents": unfavorable,
        }
    return out


def _team_goals_vs_opponent(current_fixtures: pd.DataFrame) -> dict[str, list[dict]]:
    """For each CURRENT team, for each of THEIR fixtures within the already
    gw-filtered `current_fixtures` (the same window /api/fixtures was
    called with): the opponent, and AVERAGE goals THIS team has scored/
    conceded against that SAME opponent across the last
    TEAM_GOALS_VS_OPPONENT_SEASONS complete seasons, home leg and away leg
    reported separately (a club meets each opponent once at each venue per
    season, so 3 seasons gives up to 3 meetings per leg). Averaged, not
    summed -- this spans MULTIPLE seasons/meetings, so a raw sum would be a
    less directly comparable number than "how many goals do they typically
    get in this fixture" (same per-game-rate convention as
    _recent_form_by_team elsewhere in this file). Each leg's game count is
    included too, for transparency about how many meetings the average is
    actually built from.

    Mirrors players.py's _points_vs_opponent_last_season, but at team level
    with real goals instead of individual fantasy points (a team has two
    separate meaningful numbers here -- scored AND conceded -- where a
    player's points already combine both into one), and a longer lookback
    (3 seasons here vs that one's single season) since a team's per-fixture
    trend is more meaningful with more than one data point.

    `venue_now` says which leg is "the same fixture" -- the frontend
    highlights that column. Any goals figure is None if they never met at
    that venue across the lookback window at all (e.g. a newly-promoted
    opponent) -- shown as "-" rather than a misleading 0. Matched by team
    NAME across the season boundary (see module docstring -- team_id is
    NOT stable across seasons in this cache).
    """
    if current_fixtures.empty:
        return {}

    season_ids = _recent_season_ids(LAST_COMPLETE_SEASON, TEAM_GOALS_VS_OPPONENT_SEASONS)
    placeholders = ",".join("?" for _ in season_ids)
    history = query_df(
        f"""SELECT th.name AS home_team, ta.name AS away_team, f.home_goals, f.away_goals
            FROM fixtures f
            JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
            JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
            WHERE f.season_id IN ({placeholders}) AND f.finished = 1
                  AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL""",
        tuple(season_ids),
    )

    out: dict[str, list[dict]] = {}
    sorted_fixtures = current_fixtures.sort_values("gw")
    for row in sorted_fixtures.itertuples():
        for team_name, opponent_name, is_home in (
            (row.home_team, row.away_team, True),
            (row.away_team, row.home_team, False),
        ):
            if history.empty:
                home_gf = home_ga = away_gf = away_ga = None
                home_games = away_games = 0
            else:
                vs_home = history[(history["home_team"] == team_name) & (history["away_team"] == opponent_name)]
                vs_away = history[(history["away_team"] == team_name) & (history["home_team"] == opponent_name)]
                home_gf = round(float(vs_home["home_goals"].mean()), 2) if not vs_home.empty else None
                home_ga = round(float(vs_home["away_goals"].mean()), 2) if not vs_home.empty else None
                away_gf = round(float(vs_away["away_goals"].mean()), 2) if not vs_away.empty else None
                away_ga = round(float(vs_away["home_goals"].mean()), 2) if not vs_away.empty else None
                home_games = int(len(vs_home))
                away_games = int(len(vs_away))

            out.setdefault(team_name, []).append({
                "gw": int(row.gw),
                "opponent": opponent_name,
                "venue_now": "H" if is_home else "A",
                "home_gf": home_gf,
                "home_ga": home_ga,
                "home_games": home_games,
                "away_gf": away_gf,
                "away_ga": away_ga,
                "away_games": away_games,
            })
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

    return {
        "season": CURRENT_SEASON,
        "fixtures": fixtures,
        "recent_form": _recent_form_by_team(),
        "last_season_team_stats": _team_last_season_stats(),
        "goals_vs_opponent": _team_goals_vs_opponent(df),
    }
