"""
Idempotent schema migration -- reads schema.sql (the DEFINITION, which IS in
git) and applies anything the live .db (which is NOT in git -- data/*.db is
gitignored) is missing. Safe to run on every deploy.

Why this exists: a schema change made locally (e.g. adding the `starts`
column earlier this session) has no automatic path to the VM's live
database -- `git pull` only updates code, and the actual .db file is a
one-time copy from initial deployment. That gap caused a real production
500 (captain_simulation.py querying a column that didn't exist on the VM)
that needed manual SSH surgery to fix. This closes the gap going forward.

CREATE TABLE IF NOT EXISTS statements are already naturally idempotent, just
re-run them. ALTER TABLE ... ADD COLUMN has no "IF NOT EXISTS" in SQLite, so
those are wrapped individually -- a "duplicate column" error IS the success
case (means it was already applied), anything else re-raises.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
SCHEMA = ROOT / "data" / "schema.sql"


def _strip_comments(sql: str) -> str:
    """Removes `-- comment` to end of line from every line first -- schema.sql's
    comments are full prose and routinely contain semicolons as normal
    punctuation, which would otherwise get misread as statement terminators
    by a naive split on ";" (found this the hard way: it is exactly what
    broke on the first attempt here)."""
    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(lines)


def main():
    schema_sql = _strip_comments(SCHEMA.read_text())
    statements = [s.strip() + ";" for s in schema_sql.split(";") if s.strip()]
    conn = sqlite3.connect(DB)
    created = altered = skipped = 0
    for stmt in statements:
        upper = stmt.upper()
        if "CREATE TABLE" in upper:
            conn.execute(stmt)
            created += 1
        elif "ALTER TABLE" in upper:
            try:
                conn.execute(stmt)
                altered += 1
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    skipped += 1
                else:
                    raise
        # else: a trailing comment-only chunk after the last real statement -- skip
    conn.commit()
    conn.close()
    print(f"{created} table(s) ensured, {altered} column(s) newly added, {skipped} already present.")


if __name__ == "__main__":
    main()
