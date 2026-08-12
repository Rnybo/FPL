"""
One-time (well, twice-now) data fix: merges duplicate player records caused by
name mismatches between the historical bootstrap import and the newer
live-fetch pipeline (see docs/GOTCHAS.md).

ROUND 1 (earlier): accent-encoding mismatches -- "David Raya Martin" (plain)
vs "David Raya Martin" (proper UTF-8), 28 confirmed pairs, already merged.

ROUND 2 (this version): found via a user's external-tool comparison question,
which surfaced Bruno Fernandes showing exactly 0.00 predicted points --
traced to his history being split by a DROPPED MIDDLE NAME, not an accent:
"Bruno Miguel Borges Fernandes" (historical, 2021-22 only) vs "Bruno Borges
Fernandes" (current live-fetch source, 2022-23 onward + the live 2026-27
roster link). Round 1's exact-name-after-stripping-accents match couldn't
catch this since it's not an accent difference -- an entire token is missing.
37 confirmed groups this round, including several significant players (Rodri,
Alisson, Gabriel Magalhaes, Martinelli, Idrissa Gueye, Matheus Nunes, Antony)
and at least one 3-way split (Joao Cancelo across 3 ids). Matching key is now
(first token, last token) with accents stripped from both -- catches dropped
middle names AND the original accent case in one pass, and generalizes to
GROUPS of any size, not just pairs, for the 3-way split case.
"""
import sqlite3
import unicodedata

DB = r"C:\Users\rnf\Projects\FPL\data\fpl_cache.db"
CURRENT_SEASON = "2026-27"
TABLES_WITH_PLAYER_ID = [
    "player_season", "player_gameweek_stats", "player_odds",
    "model_predictions", "live_player_status", "xp_breakdown",
]


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def name_key(name):
    tokens = name.split()
    if len(tokens) < 2:
        return None
    return (strip_accents(tokens[0]).lower(), strip_accents(tokens[-1]).lower())


def find_duplicate_groups(conn):
    rows = conn.execute("SELECT player_id, name FROM players").fetchall()
    by_key = {}
    for pid, name in rows:
        key = name_key(name)
        if key is None:
            continue
        by_key.setdefault(key, []).append((pid, name))

    groups = []
    for key, entries in by_key.items():
        if len(entries) < 2:
            continue
        seasons_per_id = {}
        for pid, name in entries:
            seasons = [s[0] for s in conn.execute(
                "SELECT DISTINCT season_id FROM player_gameweek_stats WHERE player_id=?", (pid,))]
            seasons_per_id[pid] = sorted(seasons)
        all_seasons = [s for seasons in seasons_per_id.values() for s in seasons]
        # Confirmed non-overlapping -- genuine fragmentation of one real person,
        # not a coincidental name collision between two different real players.
        if len(all_seasons) == len(set(all_seasons)) and any(seasons_per_id.values()):
            groups.append((entries, seasons_per_id))
    return groups


def pick_canonical(conn, entries):
    """Prefer the id with a player_season row for CURRENT_SEASON -- that's the
    id the live pipeline actually queries. Falls back to the id with the most
    recent season data if none/multiple match (shouldn't happen if the
    non-overlapping check above passed, but defensive either way)."""
    for pid, name in entries:
        has_current = conn.execute(
            "SELECT 1 FROM player_season WHERE player_id=? AND season_id=?", (pid, CURRENT_SEASON)
        ).fetchone()
        if has_current:
            others = [p for p, _ in entries if p != pid]
            return pid, others
    latest = [(pid, max([s[0] for s in conn.execute(
        "SELECT season_id FROM player_gameweek_stats WHERE player_id=?", (pid,))], default=""))
        for pid, _ in entries]
    latest.sort(key=lambda x: x[1], reverse=True)
    canonical = latest[0][0]
    return canonical, [pid for pid, _ in entries if pid != canonical]


def merge_group(conn, canonical_id, duplicate_ids, dry_run=True):
    moved = {}
    for dup_id in duplicate_ids:
        for table in TABLES_WITH_PLAYER_ID:
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE player_id=?", (dup_id,)).fetchone()[0]
            moved[(dup_id, table)] = count
            if not dry_run and count:
                conn.execute(f"UPDATE {table} SET player_id=? WHERE player_id=?", (canonical_id, dup_id))
        if not dry_run:
            conn.execute("DELETE FROM players WHERE player_id=?", (dup_id,))
    return moved


if __name__ == "__main__":
    import sys
    apply_changes = "--apply" in sys.argv

    conn = sqlite3.connect(DB)
    groups = find_duplicate_groups(conn)
    print(f"Found {len(groups)} confirmed duplicate groups (non-overlapping season fragments)\n")

    safe = lambda s: s.encode("ascii", "replace").decode()
    for entries, seasons_per_id in groups:
        canonical_id, duplicate_ids = pick_canonical(conn, entries)
        canonical_name = dict(entries)[canonical_id]
        moved = merge_group(conn, canonical_id, duplicate_ids, dry_run=not apply_changes)
        total_moved = sum(moved.values())
        dup_desc = ", ".join(
            f"{safe(dict(entries)[d])} (id={d}, seasons={seasons_per_id[d]})" for d in duplicate_ids
        )
        print(f"  {dup_desc}\n    -> merge into {safe(canonical_name)} (id={canonical_id}, "
              f"seasons={seasons_per_id[canonical_id]}) [{total_moved} rows moved]")

    if apply_changes:
        conn.commit()
        print("\nAPPLIED -- changes committed.")
    else:
        conn.rollback()
        print("\nDRY RUN ONLY -- no changes made. Re-run with --apply to commit.")
    conn.close()
