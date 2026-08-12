"""
Backfill defensive stats (tackles, CBI, recoveries, defensive_contribution) for
2025-26 only -- these columns don't exist in FPL's data before that season
(verified empirically, see README/conversation). Other seasons stay NULL,
honestly reflecting that the data doesn't exist rather than faking zeros.
"""
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
SEASON = "2025-26"


def season_code(season: str) -> int:
    start, end = season.split("-")
    return int(start) * 100 + int(end)


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = pd.read_csv(ROOT / "data" / "raw" / "fpl_api" / SEASON / "merged_gw.csv")
    code = season_code(SEASON)

    updates = [
        (
            int(row.tackles), int(row.clearances_blocks_interceptions),
            int(row.recoveries), int(row.defensive_contribution),
            code * 100000 + int(row.fixture),
        )
        for row in df.itertuples(index=False)
        if pd.notna(row.tackles)
    ]

    # player_id isn't in this frame directly -- join via name, same as the original loader
    name_to_id = dict(conn.execute("SELECT name, player_id FROM players").fetchall())

    rows = []
    for row in df.itertuples(index=False):
        if pd.isna(row.tackles):
            continue
        pid = name_to_id.get(row.name)
        if pid is None:
            continue
        fixture_id = code * 100000 + int(row.fixture)
        rows.append((
            int(row.tackles), int(row.clearances_blocks_interceptions),
            int(row.recoveries), int(row.defensive_contribution), pid, fixture_id,
        ))

    conn.executemany(
        """UPDATE player_gameweek_stats
           SET tackles=?, clearances_blocks_interceptions=?, recoveries=?, defensive_contribution=?
           WHERE player_id=? AND fixture_id=?""",
        rows,
    )
    conn.commit()
    print(f"Updated {len(rows)} rows with defensive stats for {SEASON}")
    conn.close()
