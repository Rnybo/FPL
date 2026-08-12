"""
Pulls ACTUAL results for finished current-season gameweeks and appends them to
player_gameweek_stats -- this is what makes the dataset evolve through the
season instead of staying frozen at the pre-season roster/fixture snapshot.

Uses event/{id}/live/ per finished gameweek, which gives each player's stats
via an 'explain' breakdown keyed by fixture -- this handles double-gameweeks
correctly (one row per fixture, not one blended row per gameweek label), same
granularity as the historical merged_gw.csv data.

Idempotent: skips any (player, fixture) combo already in the table, so this
can be re-run safely (e.g. daily) without duplicating rows -- it only ever
picks up gameweeks that finished since the last run.
"""
import sqlite3
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
LIVE_URL = "https://fantasy.premierleague.com/api/event/{gw}/live/"
CURRENT_SEASON = "2026-27"

STAT_MAP = {
    "minutes": "minutes", "goals_scored": "goals", "assists": "assists",
    "expected_goals": "xg", "expected_assists": "xa", "clean_sheets": "clean_sheet",
    "goals_conceded": "goals_conceded", "saves": "saves",
    "penalties_saved": "penalties_saved", "penalties_missed": "penalties_missed",
    "yellow_cards": "yellow_cards", "red_cards": "red_cards", "own_goals": "own_goals",
    "bonus": "bonus", "bps": "bps", "total_points": "total_points",
    "ict_index": "ict_index", "influence": "influence", "creativity": "creativity",
    "threat": "threat", "tackles": "tackles",
    "clearances_blocks_interceptions": "clearances_blocks_interceptions",
    "recoveries": "recoveries", "defensive_contribution": "defensive_contribution",
}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def season_code(season: str) -> int:
    start, end = season.split("-")
    return int(start) * 100 + int(end)


def already_loaded_gws(conn, season):
    rows = conn.execute(
        "SELECT DISTINCT gw FROM player_gameweek_stats WHERE season_id = ?", (season,)
    ).fetchall()
    return {r[0] for r in rows}


def element_id_to_player_id(conn, elements, cache):
    """Map FPL's current element id -> our stable player_id, via name."""
    mapping = {}
    for el in elements:
        name = f"{el['first_name']} {el['second_name']}".strip()
        if name in cache:
            mapping[el["id"]] = cache[name]
            continue
        row = conn.execute("SELECT player_id FROM players WHERE name = ?", (name,)).fetchone()
        if row:
            cache[name] = row[0]
            mapping[el["id"]] = row[0]
    return mapping


def build_row(player_id, fixture_id, season, gw, stats_by_identifier, was_home, price):
    d = {STAT_MAP[k]: v for k, v in stats_by_identifier.items() if k in STAT_MAP}
    return (
        player_id, fixture_id, season, gw,
        d.get("minutes", 0), d.get("goals", 0), d.get("assists", 0),
        d.get("xg"), d.get("xa"), d.get("clean_sheet", 0), d.get("goals_conceded", 0),
        d.get("saves", 0), d.get("penalties_saved", 0), d.get("penalties_missed", 0),
        d.get("yellow_cards", 0), d.get("red_cards", 0), d.get("own_goals", 0),
        d.get("bonus", 0), d.get("bps", 0), d.get("total_points", 0),
        d.get("ict_index"), d.get("influence"), d.get("creativity"), d.get("threat"),
        int(was_home), price,
        d.get("tackles"), d.get("clearances_blocks_interceptions"),
        d.get("recoveries"), d.get("defensive_contribution"),
    )


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    bootstrap = fetch_json(BOOTSTRAP_URL)
    code = season_code(CURRENT_SEASON)
    cache = {}
    price_lookup = {el["id"]: el["now_cost"] / 10.0 for el in bootstrap["elements"]}
    id_map = element_id_to_player_id(conn, bootstrap["elements"], cache)

    finished_gws = [e["id"] for e in bootstrap["events"] if e["finished"]]
    loaded_gws = already_loaded_gws(conn, CURRENT_SEASON)
    to_fetch = [gw for gw in finished_gws if gw not in loaded_gws]

    if not to_fetch:
        print(f"No new finished gameweeks for {CURRENT_SEASON} -- already up to date "
              f"(loaded: {sorted(loaded_gws)}, finished per FPL: {finished_gws})")
    else:
        print(f"Fetching {len(to_fetch)} new finished gameweek(s): {to_fetch}")

    total_rows = 0
    for gw in to_fetch:
        live = fetch_json(LIVE_URL.format(gw=gw))
        rows = []
        for el in live["elements"]:
            pid = id_map.get(el["id"])
            if pid is None:
                continue  # shouldn't happen post-roster-load, but don't crash if it does
            for entry in el.get("explain", []):
                fixture_id = code * 100000 + entry["fixture"]
                stats_dict = {s["identifier"]: s["value"] for s in entry["stats"]}
                was_home = conn.execute(
                    "SELECT home_team_id FROM fixtures WHERE fixture_id=?", (fixture_id,)
                ).fetchone()
                fixture_row = conn.execute(
                    "SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id=?", (fixture_id,)
                ).fetchone()
                player_team = conn.execute(
                    "SELECT team_id FROM player_season WHERE player_id=? AND season_id=?",
                    (pid, CURRENT_SEASON),
                ).fetchone()
                was_home_flag = (fixture_row and player_team and fixture_row[0] == player_team[0])
                rows.append(build_row(pid, fixture_id, CURRENT_SEASON, gw, stats_dict,
                                       was_home_flag, price_lookup.get(el["id"])))

        conn.executemany(
            """INSERT OR REPLACE INTO player_gameweek_stats
               (player_id, fixture_id, season_id, gw, minutes, goals, assists, xg, xa,
                clean_sheet, goals_conceded, saves, penalties_saved, penalties_missed,
                yellow_cards, red_cards, own_goals, bonus, bps, total_points,
                ict_index, influence, creativity, threat, was_home, price_at_time,
                tackles, clearances_blocks_interceptions, recoveries, defensive_contribution)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
        print(f"  GW{gw}: {len(rows)} player-fixture rows loaded")
        total_rows += len(rows)

    print(f"\nTotal new rows: {total_rows}")
    conn.close()
