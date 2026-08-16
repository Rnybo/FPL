"""GET /api/players -- the scout table: every player's predicted xP (summed
over a gameweek range) plus the FULL component breakdown, so the UI can show
exactly where a player's number comes from (goals, assists, clean sheets,
bonus, defensive contribution, etc.) -- see docs/model-architecture.md's
"never a black box" principle and xp_breakdown's schema comment for why this
always sums consistently with the headline xP number.
"""
import threading

from fastapi import APIRouter, Query
import numpy as np
import pandas as pd
from app.config import CURRENT_SEASON
from app.services.db import query_df

router = APIRouter(prefix="/api/players", tags=["players"])

BREAKDOWN_COLS = [
    "appearance_pts", "goal_pts", "assist_pts", "cs_pts", "conceded_penalty",
    "card_pen_pts", "pen_save_pts", "save_pts", "defcon_pts", "bonus_pts",
]

# Most recent COMPLETE season -- used for the "Historic Stats" panel in the
# player detail dialog. Hardcoded rather than derived from CURRENT_SEASON
# since "most recent complete" isn't simply "current season minus one" in
# every case (e.g. before any 2026-27 data exists at all).
LAST_COMPLETE_SEASON = "2025-26"

# Real scoring rules -- duplicated from captain_simulation.py/combine_xp.py
# rather than imported, same low-risk pattern already established between
# those two files. Used to reconstruct REAL historical points-by-component
# (goals/assists/bonus/etc.) from raw per-game stats, since FPL's API gives
# a game's total_points but not its breakdown. Validated against real
# 2025-26 data: 99% exact match on a 500-game random sample -- the residual
# ~1% is almost entirely players whose CURRENT position differs from what it
# was at the time (e.g. a MID->FWD reclassification since), not a rule error.
GOAL_POINTS = {"GK": 6, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_POINTS = 3
DEFCON_POINTS = 2
DEFCON_THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}  # GK ineligible


# ---------------------------------------------------------------------------
# In-process cache. Most of the analysis below (opponent history, monthly
# trends, last-season stats/breakdown, historic stats) does NOT depend on
# gw_start/gw_end at all -- it's the SAME answer regardless of which
# gameweek window Player Scout has selected -- but was previously
# recomputed from scratch on every single /api/players call, including
# every time someone just changed their GW filter. That's the "every time I
# select a new gameweek it loads" complaint this cache exists to fix: these
# are now computed once per process and reused, invalidated only by a
# genuine data refresh (see invalidate_players_cache, wired into
# scheduler.py), not by the window selection.
#
# The genuinely gw-window-DEPENDENT results (this window's own predictions,
# outcome probabilities, points-vs-opponent-in-window) go through the same
# cache too, but keyed by a tuple that includes gw_start/gw_end (and run_id
# where relevant) -- a different window still gets a correct, distinct
# answer; only an IDENTICAL repeated request (e.g. a page refresh without
# changing filters) reuses a cached result.
#
# A single process-wide dict behind a lock is deliberately simple -- this
# runs as one uvicorn worker (see deploy/push_and_deploy.ps1's docker
# compose setup), not a multi-process/multi-machine deployment, so there's
# no need for a shared external cache (Redis etc.) to keep workers in sync.
#
# RLock, not Lock: several cached functions call ANOTHER cached function
# from inside their own compute() (e.g. _opponent_stats calls
# _load_all_gw_with_opponent, which is itself cached) -- with a plain Lock
# that's an immediate same-thread deadlock the first time the outer cache is
# empty, since compute() runs WHILE _cached still holds the lock. RLock
# allows the same thread to re-enter.
# ---------------------------------------------------------------------------
_cache_lock = threading.RLock()
_cache: dict = {}


def invalidate_players_cache():
    """Call after a genuine data refresh -- new finished-gameweek stats or a
    new prediction run (see scheduler.py, which calls this after
    fetch_live_gameweek_stats.py / predict_upcoming.py succeed) -- so the
    NEXT request recomputes fresh. Lazy: just clears the cache, doesn't
    recompute immediately, so invalidating itself stays fast regardless of
    how expensive the underlying analysis is.
    """
    with _cache_lock:
        _cache.clear()


def _cached(key, compute):
    with _cache_lock:
        if key not in _cache:
            _cache[key] = compute()
        return _cache[key]


def _position_by_player() -> dict[int, str]:
    """Every player's position, straight from the players table -- NOT
    derived from any particular gw window's predictions query (a position
    doesn't change depending on which gameweeks you're looking at), so this
    is safe to cache globally and stays correct even for a player who
    happens to have zero rows in a narrow selected window.
    """
    def compute():
        df = query_df("SELECT player_id, position FROM players")
        return dict(zip(df["player_id"], df["position"]))
    return _cached("position_by_player", compute)


def _historic_by_player() -> dict[int, dict]:
    """Last complete season's real minutes/goals/assists/xG/xA per player --
    backs the "Historic Stats" panel. Independent of gw window."""
    def compute():
        historic_df = query_df(
            """SELECT player_id, SUM(minutes) AS minutes, SUM(goals) AS goals, SUM(assists) AS assists,
                      SUM(xg) AS xg, SUM(xa) AS xa
               FROM player_gameweek_stats WHERE season_id = ? GROUP BY player_id""",
            (LAST_COMPLETE_SEASON,),
        )
        return {
            row["player_id"]: {k: round(v, 2) if isinstance(v, float) else v
                                for k, v in row.items() if k != "player_id"}
            for row in historic_df.to_dict(orient="records")
        }
    return _cached("historic_by_player", compute)


def _last_season_stats_by_player() -> dict[int, dict]:
    """Real per-gameweek REAL points distribution (not our model's xP --
    actual scored FPL points), last complete season -- mean/max/min/variance
    for understanding a player's genuine ceiling/floor, plus start% (starts
    is a true "started the match" flag, not inferred from minutes -- see
    load_player_gameweeks_to_cache.py's docstring; NULL for players with no
    2025-26 data at all, e.g. a brand-new signing). Population variance
    (ddof=0), not sample variance -- describing this player's own actual
    season, not estimating a wider population from a sample of it.
    Independent of gw window.
    """
    def compute():
        last_season_gw = query_df(
            "SELECT player_id, total_points, starts FROM player_gameweek_stats WHERE season_id = ?",
            (LAST_COMPLETE_SEASON,),
        )
        out: dict[int, dict] = {}
        if last_season_gw.empty:
            return out
        agg = last_season_gw.groupby("player_id").agg(
            games=("total_points", "count"),
            starts=("starts", "sum"),
            total_points=("total_points", "sum"),
            mean_points=("total_points", "mean"),
            max_points=("total_points", "max"),
            min_points=("total_points", "min"),
            variance=("total_points", lambda s: s.var(ddof=0)),
            std_dev=("total_points", lambda s: s.std(ddof=0)),
        ).reset_index()
        agg["start_pct"] = (100 * agg["starts"] / agg["games"]).round(1)
        for r in agg.to_dict(orient="records"):
            out[r["player_id"]] = {
                "games": int(r["games"]),
                "starts": int(r["starts"]) if pd.notna(r["starts"]) else None,
                "start_pct": r["start_pct"] if pd.notna(r["start_pct"]) else None,
                "total_points": int(r["total_points"]),
                "mean_points": round(r["mean_points"], 2),
                "max_points": int(r["max_points"]),
                "min_points": int(r["min_points"]),
                "variance": round(r["variance"], 2),
                "std_dev": round(r["std_dev"], 2),
            }
        return out
    return _cached("last_season_stats_by_player", compute)


def _last_season_breakdown() -> dict[int, dict]:
    """Per-player: real points for every game they started (see
    load_player_gameweeks_to_cache.py's docstring for why `starts` -- a true
    started-the-match flag -- is used rather than `minutes > 0`, matching
    exactly what the person asked for: "data points for when starting a
    game"), the top-25%/50%/75%/overall average of those games, and the
    real points-by-component total for the season. Used for the "Last
    season stats" chart in the player detail modal -- variance/std_dev
    alone weren't intuitive, this replaces them with something visual.
    Independent of gw window -- positions come from _position_by_player(),
    not from any particular window's predictions query.
    """
    def compute():
        position_by_player = _position_by_player()
        raw = query_df(
            """SELECT player_id, gw, minutes, starts, goals, assists, clean_sheet, goals_conceded,
                      saves, penalties_saved, penalties_missed, yellow_cards, red_cards, own_goals,
                      bonus, defensive_contribution
               FROM player_gameweek_stats WHERE season_id = ?""",
            (LAST_COMPLETE_SEASON,),
        )
        if raw.empty:
            return {}

        # Double-gameweek-safe: sum every fixture within the same gw first,
        # same convention as gw_by_player in list_players.
        numeric_cols = ["minutes", "starts", "goals", "assists", "clean_sheet", "goals_conceded",
                         "saves", "penalties_saved", "penalties_missed", "yellow_cards", "red_cards",
                         "own_goals", "bonus", "defensive_contribution"]
        raw = raw.groupby(["player_id", "gw"], as_index=False)[numeric_cols].sum()
        raw["position"] = raw["player_id"].map(position_by_player)
        raw = raw.dropna(subset=["position"])  # player_id not in the current players table at all
        if raw.empty:
            return {}

        pos = raw["position"]
        played_60 = raw["minutes"] >= 60
        raw["appearance_pts"] = (raw["minutes"] > 0).astype(int) + played_60.astype(int)
        raw["goal_pts"] = raw["goals"] * pos.map(GOAL_POINTS)
        raw["assist_pts"] = raw["assists"] * ASSIST_POINTS
        raw["cs_pts"] = np.where((raw["clean_sheet"] > 0) & played_60, pos.map(CLEAN_SHEET_POINTS), 0)
        raw["conceded_pts"] = np.where(pos.isin(["GK", "DEF"]), -(raw["goals_conceded"] // 2), 0)
        raw["save_pts"] = np.where(pos == "GK", raw["saves"] // 3, 0)
        raw["card_pts"] = -1 * raw["yellow_cards"] + -3 * raw["red_cards"]
        raw["pen_pts"] = 5 * raw["penalties_saved"] + -2 * raw["penalties_missed"] + -2 * raw["own_goals"]
        defcon_threshold = pos.map(DEFCON_THRESHOLDS)
        raw["defcon_pts"] = np.where(
            defcon_threshold.notna() & (raw["defensive_contribution"].fillna(0) >= defcon_threshold),
            DEFCON_POINTS, 0,
        )
        raw["points"] = (
            raw["appearance_pts"] + raw["goal_pts"] + raw["assist_pts"] + raw["cs_pts"]
            + raw["conceded_pts"] + raw["save_pts"] + raw["card_pts"] + raw["pen_pts"]
            + raw["bonus"] + raw["defcon_pts"]
        )

        result: dict[int, dict] = {}
        for pid, g in raw.groupby("player_id"):
            started = g[g["starts"] >= 1]
            if started.empty:
                continue
            pts_sorted = np.sort(started["points"].values)[::-1]  # descending -- best games first
            n = len(pts_sorted)

            def top_pct_avg(frac: float) -> float:
                k = max(1, int(np.ceil(n * frac)))
                return round(float(pts_sorted[:k].mean()), 2)

            result[int(pid)] = {
                "games": [
                    {"gw": int(r.gw), "points": int(r.points)}
                    for r in started.sort_values("gw").itertuples()
                ],
                "percentile_averages": {
                    "top25": top_pct_avg(0.25),
                    "top50": top_pct_avg(0.50),
                    "top75": top_pct_avg(0.75),
                    "overall": round(float(pts_sorted.mean()), 2),
                },
                "points_by_component": {
                    "appearance": int(started["appearance_pts"].sum()),
                    "goals": int(started["goal_pts"].sum()),
                    "assists": int(started["assist_pts"].sum()),
                    "clean_sheet": int(started["cs_pts"].sum()),
                    "defcon": int(started["defcon_pts"].sum()),
                    "bonus": int(started["bonus"].sum()),
                    "cards": int(started["card_pts"].sum()),
                    "conceded": int(started["conceded_pts"].sum()),
                    "saves": int(started["save_pts"].sum()),
                    "penalties": int(started["pen_pts"].sum()),
                },
            }
        return result
    return _cached("last_season_breakdown", compute)


def _outcome_probabilities(run_id: int, gw_start: int | None, gw_end: int | None) -> dict[int, dict]:
    """Per-player likelihood of actually EARNING points from goals/assists/
    clean sheets/defensive contribution over the selected window -- P(>=1
    goal), P(>=1 assist), P(>=1 clean sheet), P(>=1 DefCon threshold hit) --
    from the same lambda_goal/lambda_assist/p_clean_sheet/p_defcon already
    computed by predict_upcoming.py for the captaincy Monte Carlo sim
    (captain_sim_inputs), reused here rather than recomputed. Goal/assist
    counts are ~Poisson (independent per fixture, so the summed rate across
    the window is still Poisson -- P(>=1) = 1-e^-sum(lambda)). Clean sheet
    and DefCon are both already PER-FIXTURE PROBABILITIES, not rates, so
    they combine differently: P(>=1) = 1 - product(P(miss) per fixture).
    p_clean_sheet itself is schema-documented as "independent of minutes" --
    i.e. it's the TEAM's clean-sheet chance, not this player's chance of
    actually being credited for it, which also needs 60+ minutes (p_60plus)
    -- so it's multiplied in here, same gating predict_upcoming.py already
    applies when computing cs_pts itself. p_defcon has no such gating (it's
    already conditioned on expected minutes when computed).

    Genuinely gw-window-dependent -- cached by (run_id, gw_start, gw_end),
    not globally, since a different window really does need a different answer.
    """
    def compute():
        sql = """SELECT csi.player_id, csi.lambda_goal, csi.lambda_assist, csi.p_clean_sheet,
                        csi.p_60plus, csi.p_defcon
                  FROM captain_sim_inputs csi
                  JOIN fixtures f ON f.fixture_id = csi.fixture_id
                  WHERE csi.run_id = ?"""
        params: tuple = (run_id,)
        if gw_start is not None:
            sql += " AND f.gw >= ?"
            params += (gw_start,)
        if gw_end is not None:
            sql += " AND f.gw <= ?"
            params += (gw_end,)
        df = query_df(sql, params)
        if df.empty:
            return {}

        df["p_cs_effective"] = df["p_clean_sheet"] * df["p_60plus"]
        out: dict[int, dict] = {}
        for pid, g in df.groupby("player_id"):
            p_no_cs = (1 - g["p_cs_effective"]).clip(lower=0).prod()
            p_no_defcon = (1 - g["p_defcon"]).clip(lower=0).prod()
            out[int(pid)] = {
                "goal_pts": round(1 - float(np.exp(-g["lambda_goal"].sum())), 3),
                "assist_pts": round(1 - float(np.exp(-g["lambda_assist"].sum())), 3),
                "cs_pts": round(1 - float(p_no_cs), 3),
                "defcon_pts": round(1 - float(p_no_defcon), 3),
            }
        return out
    return _cached(("outcome_probs", run_id, gw_start, gw_end), compute)


def _load_all_gw_with_opponent() -> pd.DataFrame:
    """Every player-gameweek row across ALL seasons in the cache, joined to
    its fixture to derive who the opponent was and what FDR this player's
    OWN team faced (home_difficulty is the HOME team's own difficulty --
    i.e. how hard the away side is -- see fixtures.py's docstring/FdrStrip's
    buildFdrByTeam on the frontend for the same convention). Backs both the
    "favorite/worst opponents" stats AND "points vs opponent last season" --
    shared via this cache rather than each of those two re-running the same
    full-history join independently (previously it ran TWICE per single
    /api/players request). Independent of gw window.
    """
    def compute():
        df = query_df(
            """SELECT pgs.player_id, pgs.season_id, pgs.gw, pgs.total_points, pgs.was_home,
                      f.home_team_id, f.away_team_id, f.home_difficulty, f.away_difficulty
               FROM player_gameweek_stats pgs
               JOIN fixtures f ON f.fixture_id = pgs.fixture_id
               WHERE pgs.was_home IS NOT NULL AND f.home_difficulty IS NOT NULL
                     AND f.away_difficulty IS NOT NULL"""
        )
        if df.empty:
            return df
        df["opponent_team_id"] = np.where(df["was_home"] == 1, df["away_team_id"], df["home_team_id"])
        df["fdr_faced"] = np.where(df["was_home"] == 1, df["home_difficulty"], df["away_difficulty"]).astype(int)
        return df
    return _cached("all_gw_with_opponent", compute)


def _opponent_stats() -> dict[int, dict]:
    """Per-player: favorite/least-favorite opponents (by average real points
    over the LAST 5 encounters specifically against each one -- clubs meet
    ~2x/season, so "last 5" naturally reaches back across seasons) and
    best/worst FDR tier (average points across ALL historical games at that
    difficulty, not just the last 5). Each opponent entry includes the
    upcoming gameweek this player's CURRENT team next faces them, if the
    fixture list already has one scheduled -- omitted (None) if not (e.g.
    the opponent was relegated, or the season's fixture list doesn't reach
    that far yet). Independent of gw window.
    """
    def compute():
        df = _load_all_gw_with_opponent()
        if df.empty:
            return {}
        df = df.sort_values(["season_id", "gw"])  # chronological, so .tail(5) below is really "last 5"

        teams_df = query_df("SELECT team_id, season_id, name FROM teams")
        team_name_by_id = teams_df.sort_values("season_id").groupby("team_id")["name"].last().to_dict()

        current_team_by_player = query_df(
            "SELECT player_id, team_id FROM player_season WHERE season_id = ?", (CURRENT_SEASON,)
        ).set_index("player_id")["team_id"].to_dict()

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

        out: dict[int, dict] = {}
        for pid, g in df.groupby("player_id"):
            cur_team = current_team_by_player.get(pid)

            last5 = g.groupby("opponent_team_id").tail(5)
            opp_avg = last5.groupby("opponent_team_id")["total_points"].mean()
            opp_games = last5.groupby("opponent_team_id")["total_points"].count()
            ranked = opp_avg.sort_values(ascending=False)

            def build_entry(opp_id) -> dict:
                return {
                    "opponent": team_name_by_id.get(opp_id, f"Team {opp_id}"),
                    "avg_points": round(float(opp_avg[opp_id]), 2),
                    "games": int(opp_games[opp_id]),
                    "next_gw": next_meeting.get((cur_team, opp_id)) if cur_team is not None else None,
                }

            best = [build_entry(opp) for opp in ranked.head(5).index]
            worst = [build_entry(opp) for opp in ranked.tail(5).index[::-1]]  # worst-first

            fdr_avg = g.groupby("fdr_faced")["total_points"].mean()
            fdr_games = g.groupby("fdr_faced")["total_points"].count()
            best_fdr, worst_fdr = fdr_avg.idxmax(), fdr_avg.idxmin()

            out[int(pid)] = {
                "best_opponents": best,
                "worst_opponents": worst,
                "best_fdr": {"fdr": int(best_fdr), "avg_points": round(float(fdr_avg[best_fdr]), 2), "games": int(fdr_games[best_fdr])},
                "worst_fdr": {"fdr": int(worst_fdr), "avg_points": round(float(fdr_avg[worst_fdr]), 2), "games": int(fdr_games[worst_fdr])},
            }
        return out
    return _cached("opponent_stats", compute)


# How many of the most recent complete seasons the monthly points-by-month
# view looks back across -- see _monthly_points_per_game.
MONTHLY_LOOKBACK_SEASONS = 5

# Premier League calendar order (not Jan-Dec) -- Jun/Jul included defensively
# for a rare rearranged/delayed fixture, but the cache only goes back to
# 2021-22 so this is unlikely to ever populate.
MONTH_ORDER = ["Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"]


def _recent_season_ids(latest: str, n: int) -> list[str]:
    """['2025-26', '2024-25', ...] counting back n seasons from `latest`
    (inclusive). Assumes the "YYYY-YY" format used throughout this cache."""
    start_year = int(latest.split("-")[0])
    return [f"{start_year - i}-{str(start_year - i + 1)[-2:]}" for i in range(n)]


def _monthly_points_per_game() -> dict[int, dict]:
    """Per-player: real points PER GAME by calendar month, across the last
    MONTHLY_LOOKBACK_SEASONS complete seasons -- e.g. "in August, across his
    last 5 seasons, he's averaged X/Y/Z points per game he actually played."
    Two deliberate normalizations, both directly requested:
      - Per-fixture, not per-gameweek: `minutes > 0` is the filter, so a
        month he barely featured in doesn't drag the average down just
        because it's counted as a "0" -- it's excluded outright, not zeroed.
      - Points PER GAME within the month, not a monthly total: a month with
        5 fixtures doesn't outweigh a month with 3 just because it had more
        games -- both are rates, directly comparable.
    Each month can have up to 5 values (one per season he had games that
    month) -- returned as the full array PLUS pre-computed min/q1/median/q3/
    max, so the frontend's box plot doesn't need to recompute quartiles
    itself. A month he never played across all 5 seasons is omitted
    entirely, not included as an empty/zero entry. Independent of gw window.
    """
    def compute():
        season_ids = _recent_season_ids(LAST_COMPLETE_SEASON, MONTHLY_LOOKBACK_SEASONS)
        placeholders = ",".join("?" for _ in season_ids)
        df = query_df(
            f"""SELECT pgs.player_id, pgs.season_id, pgs.total_points, f.kickoff_time
                FROM player_gameweek_stats pgs
                JOIN fixtures f ON f.fixture_id = pgs.fixture_id
                WHERE pgs.season_id IN ({placeholders}) AND pgs.minutes > 0
                      AND f.kickoff_time IS NOT NULL""",
            tuple(season_ids),
        )
        if df.empty:
            return {}
        df["month"] = pd.to_datetime(df["kickoff_time"]).dt.strftime("%b")

        # Sum points and count games within (player, season, month) FIRST --
        # a double gameweek or simply multiple fixtures in one calendar month
        # for one season combine into a single points-per-game figure for
        # that season's copy of that month, not multiple separate data points.
        grouped = df.groupby(["player_id", "season_id", "month"]).agg(
            pts=("total_points", "sum"), games=("total_points", "count")
        ).reset_index()
        grouped["ppg"] = grouped["pts"] / grouped["games"]

        out: dict[int, dict] = {}
        for pid, g in grouped.groupby("player_id"):
            months_out = []
            for month in MONTH_ORDER:
                values = sorted(g.loc[g["month"] == month, "ppg"].tolist())
                if not values:
                    continue
                months_out.append({
                    "month": month,
                    "values": [round(v, 2) for v in values],
                    "min": round(min(values), 2),
                    "q1": round(float(np.percentile(values, 25)), 2),
                    "median": round(float(np.median(values)), 2),
                    "q3": round(float(np.percentile(values, 75)), 2),
                    "max": round(max(values), 2),
                    "n_seasons": len(values),
                })
            if months_out:
                out[int(pid)] = {"months": months_out, "seasons_included": season_ids}
        return out
    return _cached("monthly_points_per_game", compute)


def _current_season_fixture_opponents(gw_start: int | None, gw_end: int | None) -> pd.DataFrame:
    """Every player's CURRENT-season fixture within [gw_start, gw_end] --
    which opponent, and whether their own team is home or away for it. Backs
    the "Points vs opponent last season" table: this is the list of upcoming/
    selected fixtures the table is FOR, distinct from _load_all_gw_with_opponent
    (which is the historical record used to answer what he scored in each).
    Genuinely gw-window-dependent -- not cached on its own (cheap query;
    the expensive part it's paired with, _load_all_gw_with_opponent, IS
    cached -- see _points_vs_opponent_last_season below).
    """
    sql = """SELECT ps.player_id, ps.team_id, f.gw, f.home_team_id, f.away_team_id
             FROM player_season ps
             JOIN fixtures f ON (f.home_team_id = ps.team_id OR f.away_team_id = ps.team_id)
                              AND f.season_id = ?
             WHERE ps.season_id = ?"""
    params: tuple = (CURRENT_SEASON, CURRENT_SEASON)
    if gw_start is not None:
        sql += " AND f.gw >= ?"
        params += (gw_start,)
    if gw_end is not None:
        sql += " AND f.gw <= ?"
        params += (gw_end,)
    df = query_df(sql, params)
    if df.empty:
        return df
    df["is_home"] = df["team_id"] == df["home_team_id"]
    df["opponent_team_id"] = np.where(df["is_home"], df["away_team_id"], df["home_team_id"])
    return df


def _points_vs_opponent_last_season(gw_start: int | None, gw_end: int | None) -> dict[int, list[dict]]:
    """Per-player, for each of their CURRENT-season fixtures in the selected
    [gw_start, gw_end] window: the opponent, and the REAL points they scored
    against that SAME opponent last season, home leg and away leg reported
    separately (a club meets each opponent once at each venue in a normal
    season). `venue_now` says which leg is "the same fixture, one year on"
    -- the frontend highlights that column. Either leg is None if they
    didn't meet at that venue last season at all (e.g. a newly-promoted
    opponent, or the player himself wasn't at this club yet) -- shown as
    "-" rather than a misleading 0.

    Deliberately player-centric, not team-centric: if he changed clubs, this
    is still HIS points against that opponent last season (for whichever
    team he was on then), same philosophy as _opponent_stats above -- not
    "what this team's other players scored," which would be a different,
    less personally-relevant question.

    Genuinely gw-window-dependent -- cached by (gw_start, gw_end). Reuses
    the CACHED _load_all_gw_with_opponent() rather than re-running that
    full-history join itself.
    """
    def compute():
        current = _current_season_fixture_opponents(gw_start, gw_end)
        if current.empty:
            return {}

        hist = _load_all_gw_with_opponent()
        last_season_hist = hist[hist["season_id"] == LAST_COMPLETE_SEASON] if not hist.empty else hist

        teams_df = query_df("SELECT team_id, season_id, name FROM teams")
        team_name_by_id = teams_df.sort_values("season_id").groupby("team_id")["name"].last().to_dict()

        out: dict[int, list[dict]] = {}
        for pid, g in current.groupby("player_id"):
            player_hist = last_season_hist[last_season_hist["player_id"] == pid] if not last_season_hist.empty else last_season_hist
            rows = []
            for r in g.sort_values("gw").itertuples():
                opp_id = r.opponent_team_id
                if not player_hist.empty:
                    vs_opp = player_hist[player_hist["opponent_team_id"] == opp_id]
                    home_pts = vs_opp.loc[vs_opp["was_home"] == 1, "total_points"]
                    away_pts = vs_opp.loc[vs_opp["was_home"] == 0, "total_points"]
                else:
                    home_pts = away_pts = pd.Series(dtype=float)
                rows.append({
                    "gw": int(r.gw),
                    "opponent": team_name_by_id.get(opp_id, f"Team {opp_id}"),
                    "venue_now": "H" if r.is_home else "A",
                    "home_points_last_season": int(home_pts.sum()) if not home_pts.empty else None,
                    "away_points_last_season": int(away_pts.sum()) if not away_pts.empty else None,
                })
            if rows:
                out[int(pid)] = rows
        return out
    return _cached(("points_vs_opp", gw_start, gw_end), compute)


@router.get("")
def list_players(
    gw_start: int | None = Query(None, description="First gameweek to include (inclusive)"),
    gw_end: int | None = Query(None, description="Last gameweek to include (inclusive)"),
):
    latest_run = query_df(
        "SELECT run_id, notes FROM model_runs WHERE model_type='predict_upcoming' "
        "ORDER BY run_id DESC LIMIT 1"
    )
    if latest_run.empty:
        return {"players": [], "run_id": None, "note": "No predictions generated yet"}
    run_id = int(latest_run.iloc[0]["run_id"])

    def _fetch_raw_predictions():
        breakdown_cols_sql = ", ".join(f"b.{c}" for c in BREAKDOWN_COLS)
        sql = f"""SELECT p.player_id, p.name, p.position, t.name AS team, t.code AS team_code,
                         ps.price_end AS price, mp.predicted_points AS xP, f.gw, {breakdown_cols_sql}
                  FROM model_predictions mp
                  JOIN players p ON mp.player_id = p.player_id
                  JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
                  JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?
                  JOIN fixtures f ON f.fixture_id = mp.fixture_id
                  JOIN xp_breakdown b ON b.run_id = mp.run_id AND b.player_id = mp.player_id
                                       AND b.fixture_id = mp.fixture_id
                  WHERE mp.run_id = ?"""
        params: tuple = (CURRENT_SEASON, CURRENT_SEASON, run_id)
        if gw_start is not None:
            sql += " AND f.gw >= ?"
            params += (gw_start,)
        if gw_end is not None:
            sql += " AND f.gw <= ?"
            params += (gw_end,)
        return query_df(sql, params)

    # This window's own predictions -- genuinely gw-dependent, so cached by
    # (run_id, gw_start, gw_end), not globally. A repeat of the SAME window
    # (e.g. a page refresh with no filter change) reuses this; a different
    # window correctly recomputes.
    raw_df = _cached(("raw_predictions", run_id, gw_start, gw_end), _fetch_raw_predictions)

    # Per-gameweek xP -- summed within a gameweek first (double-gameweek-safe:
    # two fixtures in the same gw add together, matching how the headline xP
    # already handles doubles elsewhere in the pipeline), kept SEPARATE from
    # the range-wide aggregate below so the UI can show/sort by an individual
    # gameweek without losing the overall total.
    per_gw = raw_df.groupby(["player_id", "gw"], as_index=False)["xP"].sum()
    gw_by_player: dict[int, list[dict]] = {}
    for row in per_gw.to_dict(orient="records"):
        gw_by_player.setdefault(row["player_id"], []).append(
            {"gw": int(row["gw"]), "xP": round(row["xP"], 3)}
        )
    for pid in gw_by_player:
        gw_by_player[pid].sort(key=lambda r: r["gw"])

    # Same double-gameweek-safe aggregation as optimise.py/squad.py -- sum every
    # fixture in the range for a player, both the headline xP and each component.
    sum_cols = ["xP"] + BREAKDOWN_COLS
    df = raw_df.groupby(["player_id", "name", "position", "team", "team_code", "price"], as_index=False)[sum_cols].sum()

    historic_by_player = _historic_by_player()
    last_season_stats_by_player = _last_season_stats_by_player()
    breakdown_by_player = _last_season_breakdown()
    prob_by_player = _outcome_probabilities(run_id, gw_start, gw_end)
    opponent_stats_by_player = _opponent_stats()
    monthly_by_player = _monthly_points_per_game()
    points_vs_opponent_by_player = _points_vs_opponent_last_season(gw_start, gw_end)

    players = []
    for row in df.to_dict(orient="records"):
        breakdown = {c: round(row.pop(c), 3) for c in BREAKDOWN_COLS}
        row["breakdown"] = breakdown
        row["gameweeks"] = gw_by_player.get(row["player_id"], [])
        row["historic"] = historic_by_player.get(row["player_id"])
        last_season_stats = last_season_stats_by_player.get(row["player_id"])
        row["last_season_stats"] = last_season_stats
        # Flattened onto the row (not just nested in last_season_stats) so
        # Player Scout can sort by it directly, the same way it already
        # sorts by xP/price -- see SortField in PlayerScout.tsx.
        row["last_season_total_points"] = last_season_stats["total_points"] if last_season_stats else 0
        row["last_season_breakdown"] = breakdown_by_player.get(row["player_id"])
        row["prob"] = prob_by_player.get(row["player_id"])
        row["opponent_stats"] = opponent_stats_by_player.get(row["player_id"])
        row["points_by_month"] = monthly_by_player.get(row["player_id"])
        row["points_vs_opponent_last_season"] = points_vs_opponent_by_player.get(row["player_id"])
        players.append(row)
    players.sort(key=lambda p: p["xP"], reverse=True)

    return {"run_id": run_id, "gw_start": gw_start, "gw_end": gw_end, "players": players}
