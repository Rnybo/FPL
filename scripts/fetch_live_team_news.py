"""
Live team-news collector -- addresses gap #1 from the combine_xp.py analysis
(no live lineup/team-news signal). See docs/GOTCHAS.md and README for why this
is fundamentally NOT backtestable against our 5 historical seasons: FPL's live
status/news/chance-of-playing fields aren't preserved historically anywhere we
have access to. This only starts accumulating value from whenever we begin
polling -- it's a live-only enhancement layer, not a training feature.

Pulls bootstrap-static/ (current, live) and stores each player's current
availability signal: status code, chance of playing this/next round, and any
news text (injury/suspension updates) -- plus set-piece taker order
(penalties/direct free-kicks/corners & indirect free-kicks -- verified live
against the real API: 1 = primary taker, 2 = backup, NULL if not on duty).
Matches to our stable player_id via name (same identity pattern used
throughout this project for cross-source joins -- see
load_player_gameweeks_to_cache.py).

Run this close to a gameweek deadline for the freshest signal -- these fields
update as team news breaks (press conferences, etc.), unlike the rest of our
pipeline which is fit once per gameweek/season from historical data.
"""
import json
import sqlite3
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

STATUS_MEANING = {
    "a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable",
}


def fetch_bootstrap():
    req = urllib.request.Request(BOOTSTRAP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def match_player_id(conn, web_name, first_name, second_name):
    """Match FPL's current element to our stable player_id via full name --
    same identity pattern as load_player_gameweeks_to_cache.py."""
    full_name = f"{first_name} {second_name}".strip()
    row = conn.execute("SELECT player_id FROM players WHERE name = ?", (full_name,)).fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT player_id FROM players WHERE name = ?", (web_name,)).fetchone()
    return row[0] if row else None


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    data = fetch_bootstrap()
    teams_by_id = {t["id"]: t["name"] for t in data["teams"]}
    captured_at = datetime.now(timezone.utc).isoformat()

    rows = []
    unmatched = 0
    for el in data["elements"]:
        pid = match_player_id(conn, el["web_name"], el["first_name"], el["second_name"])
        if pid is None:
            unmatched += 1
        rows.append((
            pid, el["id"], el["web_name"], teams_by_id.get(el["team"]),
            el["status"], el.get("chance_of_playing_this_round"),
            el.get("chance_of_playing_next_round"), el.get("news") or None,
            el.get("news_added"), captured_at,
            el.get("penalties_order"), el.get("direct_freekicks_order"),
            el.get("corners_and_indirect_freekicks_order"),
        ))

    conn.executemany(
        """INSERT INTO live_player_status
           (player_id, fpl_element_id, web_name, team_name, status,
            chance_of_playing_this_round, chance_of_playing_next_round,
            news, news_added, captured_at, penalties_order,
            direct_freekicks_order, corners_and_indirect_freekicks_order)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    print(f"Captured {len(rows)} players ({unmatched} unmatched to our player_id -- "
          f"new signings not yet in historical data, expected)")

    flagged = [r for r in rows if r[4] != "a" or (r[5] is not None and r[5] < 100)]
    print(f"\n{len(flagged)} players currently flagged (not fully available):")
    for r in sorted(flagged, key=lambda r: (r[5] if r[5] is not None else -1))[:15]:
        _, _, web_name, team, status, chance_this, chance_next, news, _, _, _, _, _ = r
        line = (f"  {web_name:20s} {team:15s} status={STATUS_MEANING.get(status, status):10s} "
                f"chance_next={chance_next}  news={news}")
        print(line.encode("ascii", "replace").decode())

    conn.close()
