"""
Load fixtures.csv + teams.csv (per season, fetched by fetch_historical_fixtures.py)
into fpl_cache.db: teams and fixtures tables.

Resolves each season's numeric team ids (which reset every season) to team names
using that season's teams.csv, so fixtures are stored with stable name-based team
identity across seasons.
"""
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fpl_api"
DB = ROOT / "data" / "fpl_cache.db"

SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]


def season_code(season: str) -> int:
    """'2021-22' -> 202122 -- used as a prefix to keep fixture_id unique across seasons."""
    start, end = season.split("-")
    return int(start) * 100 + int(end)


def load_season(conn, season: str):
    teams = pd.read_csv(RAW / season / "teams.csv")
    fixtures = pd.read_csv(RAW / season / "fixtures.csv")

    conn.execute(
        "INSERT OR IGNORE INTO seasons (season_id, start_date, end_date) VALUES (?, NULL, NULL)",
        (season,),
    )

    id_to_name = dict(zip(teams["id"], teams["name"]))

    for _, row in teams.iterrows():
        conn.execute(
            """INSERT OR REPLACE INTO teams
               (team_id, season_id, name, strength_attack_home, strength_attack_away,
                strength_defence_home, strength_defence_away)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(row["id"]), season, row["name"],
                row.get("strength_attack_home"), row.get("strength_attack_away"),
                row.get("strength_defence_home"), row.get("strength_defence_away"),
            ),
        )

    finished = fixtures[fixtures["finished"] == True]
    for _, row in finished.iterrows():
        conn.execute(
            """INSERT OR REPLACE INTO fixtures
               (fixture_id, season_id, gw, home_team_id, away_team_id, kickoff_time,
                home_difficulty, away_difficulty, home_goals, away_goals, finished)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                season_code(season) * 100000 + int(row["id"]), season,
                row["event"] if pd.notna(row["event"]) else None,
                int(row["team_h"]), int(row["team_a"]), row["kickoff_time"],
                row.get("team_h_difficulty"), row.get("team_a_difficulty"),
                int(row["team_h_score"]), int(row["team_a_score"]),
            ),
        )
    return len(teams), len(finished), id_to_name


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    for season in SEASONS:
        n_teams, n_fixtures, _ = load_season(conn, season)
        print(f"{season}: {n_teams} teams, {n_fixtures} finished fixtures loaded")
    conn.commit()
    conn.close()
