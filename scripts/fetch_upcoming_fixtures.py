"""
Load the current/upcoming season's fixtures into fpl_cache.db -- the piece
docs/multi-gameweek-forecasting.md identified as missing. FPL publishes the
full season schedule upfront (not just the next match), so this pulls
everything at once: played fixtures get real scores, unplayed ones get
finished=0 and null scores, ready for Layers 1/1b/2/3 to predict onto instead
of only backtest against.

Uses the SAME schema and ID scheme as the historical loader
(load_fixtures_to_cache.py) -- fixture_id = season_code*100000 + fpl_id -- so
combine_xp.py and friends work on these rows without any special-casing.
"""
import sqlite3
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

CURRENT_SEASON = "2026-27"  # update each year -- FPL doesn't label seasons in its API


def season_code(season: str) -> int:
    start, end = season.split("-")
    return int(start) * 100 + int(end)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    code = season_code(CURRENT_SEASON)

    print(f"Fetching bootstrap-static for {CURRENT_SEASON}...")
    bootstrap = fetch_json(BOOTSTRAP_URL)
    conn.execute(
        "INSERT OR IGNORE INTO seasons (season_id, start_date, end_date) VALUES (?, NULL, NULL)",
        (CURRENT_SEASON,),
    )
    for t in bootstrap["teams"]:
        conn.execute(
            """INSERT OR REPLACE INTO teams
               (team_id, season_id, name, code, strength_attack_home, strength_attack_away,
                strength_defence_home, strength_defence_away)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (t["id"], CURRENT_SEASON, t["name"], t["code"], t.get("strength_attack_home"),
             t.get("strength_attack_away"), t.get("strength_defence_home"), t.get("strength_defence_away")),
        )
    print(f"  {len(bootstrap['teams'])} teams loaded")

    print("Fetching fixtures/...")
    fixtures = fetch_json(FIXTURES_URL)
    n_finished, n_upcoming = 0, 0
    for f in fixtures:
        if f["event"] is None:
            continue  # unscheduled (rare edge case, e.g. postponed with no new date yet)
        finished = 1 if f["finished"] else 0
        n_finished += finished
        n_upcoming += 1 - finished
        conn.execute(
            """INSERT OR REPLACE INTO fixtures
               (fixture_id, season_id, gw, home_team_id, away_team_id, kickoff_time,
                home_difficulty, away_difficulty, home_goals, away_goals, finished)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code * 100000 + f["id"], CURRENT_SEASON, f["event"], f["team_h"], f["team_a"],
             f["kickoff_time"], f.get("team_h_difficulty"), f.get("team_a_difficulty"),
             f["team_h_score"], f["team_a_score"], finished),
        )
    conn.commit()
    print(f"  {n_finished} finished, {n_upcoming} upcoming fixtures loaded for {CURRENT_SEASON}")
    conn.close()
