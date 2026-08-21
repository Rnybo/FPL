"""
Scrapes fantasyfootballscout.co.uk/team-news for each club's PREDICTED
starting XI ahead of their next fixture -- genuinely new information our own
model can't see: not injury/suspension (already covered by
fetch_live_team_news.py's status field), but rotation risk for players who
are otherwise fully fit. Fills the gap flagged in docs/model-architecture.md.

No public JSON API for this page, but it's fully server-rendered (verified:
all 20 team-news-item blocks present in one GET, no JS/login needed) and
robots.txt allows it. Parsed with plain regex rather than adding a new HTML
dependency -- stable WordPress theme markup, and we only need one thing out
of it: which player codes appear in the predicted-XI pitch graphic.

Player identity: each predicted-XI player's photo URL embeds their official
Premier League `code` (e.g. .../players/110x140/154561.png) -- the SAME
`code` field bootstrap-static exposes per element, so matching is an exact
int join, not fuzzy name matching (verified directly against a real
bootstrap-static pull). Out/Doubt/Banned lists have no photo/code, so
they're not captured here -- largely redundant with live_player_status anyway.

NOT backtestable (see predicted_lineups' own schema comment) -- only starts
accumulating value from whenever we begin polling. Re-running before a
deadline is expected and safe: each run just adds a fresh captured_at
snapshot, same accumulate-don't-upsert pattern as live_player_status.
"""
import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
TEAM_NEWS_URL = "https://www.fantasyfootballscout.co.uk/team-news"
CURRENT_SEASON = "2026-27"

TEAM_BLOCK_RE = re.compile(r'<li class="team-news-item" data-team-code="(\w+)">')
LINEUP_END_RE = re.compile(r'class="story-parts"')
PLAYER_CODE_RE = re.compile(r'/players/110x140/(\d+)\.png')


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def code_to_player_id_map(conn, elements):
    """FPL element `code` -> our stable player_id, via name (same identity
    pattern as fetch_live_team_news.py/fetch_live_gameweek_stats.py)."""
    players_by_name = dict(conn.execute("SELECT name, player_id FROM players").fetchall())
    mapping = {}
    for el in elements:
        full_name = f"{el['first_name']} {el['second_name']}".strip()
        pid = players_by_name.get(full_name)
        if pid is not None:
            mapping[el["code"]] = pid
    return mapping


def team_id_map(conn, teams):
    """FFS's data-team-code (FPL short_name, lowercased) -> our team_id."""
    rows = conn.execute(
        "SELECT team_id, name FROM teams WHERE season_id=?", (CURRENT_SEASON,)
    ).fetchall()
    name_to_id = {name: tid for tid, name in rows}
    short_to_id = {}
    for t in teams:
        tid = name_to_id.get(t["name"])
        if tid is not None:
            short_to_id[t["short_name"].lower()] = tid
    return short_to_id


def next_fixture_id(conn, team_id):
    row = conn.execute(
        """SELECT fixture_id FROM fixtures
           WHERE season_id=? AND finished=0 AND (home_team_id=? OR away_team_id=?)
           ORDER BY gw ASC LIMIT 1""",
        (CURRENT_SEASON, team_id, team_id),
    ).fetchone()
    return row[0] if row else None


def parse_team_blocks(html):
    """Yields (team_code, predicted_codes) for each team-news-item block."""
    matches = list(TEAM_BLOCK_RE.finditer(html))
    for i, m in enumerate(matches):
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        block = html[block_start:block_end]
        lineup_end = LINEUP_END_RE.search(block)
        lineup_html = block[:lineup_end.start()] if lineup_end else block
        codes = [int(c) for c in PLAYER_CODE_RE.findall(lineup_html)]
        yield m.group(1), codes


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    bootstrap = json.loads(fetch_url(BOOTSTRAP_URL))
    code_map = code_to_player_id_map(conn, bootstrap["elements"])
    team_map = team_id_map(conn, bootstrap["teams"])

    html = fetch_url(TEAM_NEWS_URL)
    captured_at = datetime.now(timezone.utc).isoformat()

    rows = []
    n_teams = n_unmatched_players = n_unmatched_teams = 0
    for team_code, player_codes in parse_team_blocks(html):
        team_id = team_map.get(team_code)
        if team_id is None:
            n_unmatched_teams += 1
            continue
        n_teams += 1
        fixture_id = next_fixture_id(conn, team_id)
        if len(player_codes) != 11:
            print(f"  [warn] {team_code}: parsed {len(player_codes)} predicted starters, expected 11")
        for code in player_codes:
            pid = code_map.get(code)
            if pid is None:
                n_unmatched_players += 1
                continue
            rows.append((pid, team_id, fixture_id, 1, "ffscout", captured_at))

    conn.executemany(
        """INSERT INTO predicted_lineups (player_id, team_id, fixture_id, predicted_start, source, captured_at)
           VALUES (?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    print(f"Parsed {n_teams} teams, {n_unmatched_teams} unmatched team codes, "
          f"{len(rows)} predicted starters stored ({n_unmatched_players} players unmatched to player_id)")
    conn.close()
