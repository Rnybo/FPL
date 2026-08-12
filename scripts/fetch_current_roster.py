"""
Loads current-season (2026-27) player rosters -- who's on which team right
now -- from bootstrap-static's elements array. Needed before predict_upcoming.py
can know which team a player belongs to this season (summer transfers moved
plenty of players since 2025-26's data was loaded).

PLAYER IDENTITY (rewritten -- see docs/GOTCHAS.md): used to match by full NAME
alone, which broke TWICE this session in two different ways -- accent-encoding
differences ("Martin" vs "Martin" with a diacritic) and dropped middle names
("Bruno Miguel Borges Fernandes" vs "Bruno Borges Fernandes"), each silently
fragmenting one real person's history across multiple player_id rows. Name
strings are fundamentally unreliable as an identity key: they can format
differently between sources, AND two genuinely different real people can
share an identical name (a namesake collision no name-matching heuristic can
safely rule out).

FPL's own data already solves this: elements have a `code` field -- a stable,
Opta-assigned per-person identifier that never changes across seasons, name
formatting, or transfers (confirmed present in both the live bootstrap-static
API and the historical players_raw.csv snapshots). This is the SAME pattern
already used for team shirt codes (see PlayerShirt.tsx). Now used as the
PRIMARY match key -- name is stored purely for display and is free to update
without ever being treated as identity. Falls back to name-matching only for
rows that predate this fix and don't have a code yet (a one-time bridge, not
a permanent reliance on name matching).
"""
import sqlite3
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
CURRENT_SEASON = "2026-27"

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def fetch_bootstrap():
    req = urllib.request.Request(BOOTSTRAP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def get_or_create_player(conn, code, name, position, cache):
    """code is the PRIMARY identity key -- see module docstring. name-matching
    is only a fallback for pre-existing rows that don't have a code yet."""
    if code in cache:
        return cache[code]

    row = conn.execute("SELECT player_id, code FROM players WHERE code = ?", (code,)).fetchone()
    if row:
        cache[code] = row[0]
        return row[0]

    # Fallback for rows created before this fix (no code stored yet) -- match
    # by name ONE more time, then backfill their code so this fallback is
    # never needed for that row again.
    row = conn.execute("SELECT player_id FROM players WHERE name = ? AND code IS NULL", (name,)).fetchone()
    if row:
        conn.execute("UPDATE players SET code = ? WHERE player_id = ?", (code, row[0]))
        cache[code] = row[0]
        return row[0]

    cur = conn.execute(
        "INSERT INTO players (name, position, current_team_id, code) VALUES (?, ?, NULL, ?)",
        (name, position, code),
    )
    cache[code] = cur.lastrowid
    return cur.lastrowid


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    data = fetch_bootstrap()
    team_names = {t["id"]: t["name"] for t in data["teams"]}
    cache = {}

    new_players, updated = 0, 0
    for el in data["elements"]:
        full_name = f"{el['first_name']} {el['second_name']}".strip()
        code = el["code"]
        position = POSITION_MAP.get(el["element_type"])
        if position is None:
            continue  # skip the "Manager" novelty pick type -- see docs/GOTCHAS.md

        # RULE FIX: this must check the SAME resolution path get_or_create_player
        # uses (code, falling back to name) -- checking code alone gave a false
        # "577 newly seen" on the first run after this fix, since code was NULL
        # for everyone before that run even though every one of them correctly
        # matched via the name fallback.
        existed = conn.execute(
            "SELECT 1 FROM players WHERE code = ? OR (name = ? AND code IS NULL)", (code, full_name)
        ).fetchone()
        pid = get_or_create_player(conn, code, full_name, position, cache)
        new_players += 0 if existed else 1

        # Position AND name are refreshed every run regardless of whether this
        # player already existed -- position can be reclassified season to
        # season (see the earlier Semenyo fix), and name can improve in
        # formatting over time; neither should ever be "sticky" from creation.
        conn.execute("UPDATE players SET position = ?, current_team_id = ?, name = ? WHERE player_id = ?",
                     (position, el["team"], full_name, pid))

        team_id = el["team"]
        price = el["now_cost"] / 10.0
        conn.execute(
            "INSERT OR REPLACE INTO player_season (player_id, season_id, team_id, price_start, price_end) "
            "VALUES (?, ?, ?, COALESCE((SELECT price_start FROM player_season WHERE player_id=? AND season_id=?), ?), ?)",
            (pid, CURRENT_SEASON, team_id, pid, CURRENT_SEASON, price, price),
        )
        updated += 1

    # Safety net: a code mapping to more than one player_id would mean a fresh
    # duplicate slipped in despite the fix above -- surface it immediately
    # instead of waiting for someone to notice broken predictions again.
    dupes = conn.execute("""
        SELECT code, COUNT(DISTINCT player_id) as n FROM players
        WHERE code IS NOT NULL GROUP BY code HAVING n > 1
    """).fetchall()
    if dupes:
        print(f"\nWARNING: {len(dupes)} code(s) map to multiple player_ids -- investigate before trusting predictions:")
        for code, n in dupes:
            print(f"  code={code}: {n} player_ids")

    conn.commit()
    print(f"Rosters loaded for {CURRENT_SEASON}: {updated} players, {new_players} newly seen "
          f"(summer signings / promoted-club players with no prior PL history -- expected)")
    conn.close()
