"""
Load historical odds from football-data.co.uk CSVs (fetched via fetch_odds.py, run
on an unrestricted network -- see docs/odds-sources.md) into fpl_cache.db's
match_odds table.

Joins each odds row to our existing fixtures table via (season, home_team, away_team)
-- unique within a season since each pairing happens exactly once at each venue.
Team names differ slightly between football-data.co.uk and the FPL-API-based naming
already in our teams table; TEAM_NAME_MAP below covers the known mismatches.
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "football_data_co_uk"
DB = ROOT / "data" / "fpl_cache.db"

SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

TEAM_NAME_MAP = {
    "Man United": "Man Utd",
    "Sheffield United": "Sheffield Utd",
    "Tottenham": "Spurs",
}

SOURCE = "football_data_co_uk"


def normalize(team: str) -> str:
    return TEAM_NAME_MAP.get(team, team)


def build_fixture_lookup(conn, season: str) -> dict:
    """(home_name, away_name) -> fixture_id, for one season."""
    rows = conn.execute(
        """SELECT f.fixture_id, th.name, ta.name
           FROM fixtures f
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
           WHERE f.season_id = ?""",
        (season,),
    ).fetchall()
    return {(h, a): fid for fid, h, a in rows}


def load_season(conn, season: str):
    df = pd.read_csv(RAW / f"{season}.csv")
    lookup = build_fixture_lookup(conn, season)

    matched, unmatched = 0, 0
    rows_to_insert = []

    for _, row in df.iterrows():
        home = normalize(row["HomeTeam"])
        away = normalize(row["AwayTeam"])
        fixture_id = lookup.get((home, away))
        if fixture_id is None:
            unmatched += 1
            continue
        matched += 1

        # h2h (1X2), closing average across bookmakers
        for outcome, col in [("H", "AvgCH"), ("D", "AvgCD"), ("A", "AvgCA")]:
            if pd.notna(row.get(col)):
                rows_to_insert.append((fixture_id, SOURCE, "h2h", outcome, float(row[col]), None))

        # totals 2.5 goals, closing average
        for outcome, col in [("over", "AvgC>2.5"), ("under", "AvgC<2.5")]:
            if pd.notna(row.get(col)):
                rows_to_insert.append((fixture_id, SOURCE, "totals_2.5", outcome, float(row[col]), None))

    conn.executemany(
        "INSERT INTO match_odds (fixture_id, source, market, team_or_outcome, price, captured_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows_to_insert,
    )
    return matched, unmatched, len(rows_to_insert)


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    total_rows = 0
    for season in SEASONS:
        matched, unmatched, n_rows = load_season(conn, season)
        total_rows += n_rows
        print(f"{season}: {matched} fixtures matched, {unmatched} unmatched, {n_rows} odds rows inserted")
    conn.commit()
    conn.close()
    print(f"\nTotal odds rows inserted: {total_rows}")
