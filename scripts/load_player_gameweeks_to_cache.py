"""
Load player gameweek stats (merged_gw.csv per season) into fpl_cache.db:
players, player_season, player_gameweek_stats.

Player identity: currently matches by NAME (merged_gw.csv doesn't carry FPL's
stable `code` field, only players_raw.csv does -- confirmed by checking the
raw source directly). This is the SAME fragile pattern that caused two
separate rounds of duplicate-player bugs this session (accent differences,
then dropped middle names -- see docs/GOTCHAS.md). fetch_current_roster.py
(the live pipeline) has since been fixed to key identity by `code`, with a
name-matching fallback used only to bridge to pre-existing rows.

TODO before this script is ever re-run (e.g. a future full historical
reload): fetch players_raw.csv for each season alongside merged_gw.csv,
build an `element -> code` mapping from it (merged_gw.csv's own `element`
column matches players_raw.csv's `id`), and key get_or_create_player by code
the same way fetch_current_roster.py now does. Left as name-matching for now
because this script hasn't needed to run again since the original 5-season
load, and the live pipeline's ongoing code-backfill (see its own docstring)
already covers anyone who's currently rostered -- but don't reintroduce the
old fragile pattern if this ever gets re-run for a full reload.

fixture linkage: merged_gw's 'fixture' column matches that season's
fixtures.csv 'id' directly (verified), so fixture_id = season_code(season) *
100000 + fixture -- same formula used in load_fixtures_to_cache.py.

Note: 2021-22 has no expected_goals/expected_assists columns (FPL added xG/xA
later) -- handled by storing NULL for that season rather than crashing.
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "fpl_api"
DB = ROOT / "data" / "fpl_cache.db"
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]


def season_code(season: str) -> int:
    start, end = season.split("-")
    return int(start) * 100 + int(end)


def get_or_create_player(conn, name: str, position: str, player_cache: dict) -> int:
    if name in player_cache:
        return player_cache[name]
    row = conn.execute("SELECT player_id FROM players WHERE name = ?", (name,)).fetchone()
    if row:
        player_cache[name] = row[0]
        return row[0]
    cur = conn.execute(
        "INSERT INTO players (name, position, current_team_id) VALUES (?, ?, NULL)", (name, position)
    )
    player_cache[name] = cur.lastrowid
    return cur.lastrowid


def team_id_lookup(conn, season: str) -> dict:
    rows = conn.execute("SELECT team_id, name FROM teams WHERE season_id=?", (season,)).fetchall()
    return {name: tid for tid, name in rows}


def load_season(conn, season: str, player_cache: dict):
    df = pd.read_csv(RAW / season / "merged_gw.csv")
    team_ids = team_id_lookup(conn, season)
    code = season_code(season)
    has_xg = "expected_goals" in df.columns

    gw_rows = []
    season_prices = {}  # player_id -> [first_value, last_value]

    for row in df.itertuples(index=False):
        pid = get_or_create_player(conn, row.name, row.position, player_cache)
        fixture_id = code * 100000 + int(row.fixture)
        value = row.value / 10.0 if pd.notna(row.value) else None
        xg = float(row.expected_goals) if has_xg and pd.notna(row.expected_goals) else None
        xa = float(row.expected_assists) if has_xg and pd.notna(row.expected_assists) else None

        gw_rows.append((
            pid, fixture_id, season, int(row.GW), int(row.minutes),
            int(row.goals_scored), int(row.assists), xg, xa,
            int(row.clean_sheets), int(row.goals_conceded), int(row.saves),
            int(row.penalties_saved), int(row.penalties_missed),
            int(row.yellow_cards), int(row.red_cards), int(row.own_goals),
            int(row.bonus), int(row.bps), int(row.total_points),
            float(row.ict_index), float(row.influence), float(row.creativity), float(row.threat),
            int(bool(row.was_home)), value,
        ))

        season_prices.setdefault(pid, [value, value])
        season_prices[pid][1] = value

        team_id = team_ids.get(row.team)
        if team_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO player_season (player_id, season_id, team_id, price_start, price_end) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, season, team_id, value, value),
            )

    conn.executemany(
        """INSERT OR REPLACE INTO player_gameweek_stats
           (player_id, fixture_id, season_id, gw, minutes, goals, assists, xg, xa,
            clean_sheet, goals_conceded, saves, penalties_saved, penalties_missed,
            yellow_cards, red_cards, own_goals, bonus, bps, total_points,
            ict_index, influence, creativity, threat, was_home, price_at_time)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        gw_rows,
    )

    for pid, (p_start, p_end) in season_prices.items():
        conn.execute(
            "UPDATE player_season SET price_start=?, price_end=? WHERE player_id=? AND season_id=?",
            (p_start, p_end, pid, season),
        )

    return df["name"].nunique(), len(gw_rows)


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    player_cache = {}
    for season in SEASONS:
        n_players, n_rows = load_season(conn, season, player_cache)
        conn.commit()
        print(f"{season}: {n_players} players, {n_rows} gameweek rows loaded")
    print(f"\nTotal distinct players across all seasons: {len(player_cache)}")
    conn.close()
