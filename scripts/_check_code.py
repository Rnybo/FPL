import sqlite3
conn = sqlite3.connect('data/fpl_cache.db')
cols = conn.execute("PRAGMA table_info(teams)").fetchall()
for c in cols:
    print(c)
print("---")
rows = conn.execute("SELECT team_id, season_id, name, code FROM teams WHERE season_id IN ('2025-26','2026-27') AND (name LIKE '%Leeds%' OR name LIKE '%Hull%' OR name LIKE '%Liverpool%' OR name LIKE '%Leicester%') ORDER BY season_id").fetchall()
for r in rows:
    print(r)
