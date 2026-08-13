"""
Tests for ensure_schema.py -- the deploy-time migration safety net (see its
own module docstring for why this exists: a real production 500 caused by
the VM's database missing a column that only ever got added locally).
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from ensure_schema import _strip_comments


class TestStripComments:
    def test_removes_trailing_comment(self):
        result = _strip_comments("CREATE TABLE foo (id INTEGER); -- a comment")
        assert "-- a comment" not in result
        assert "CREATE TABLE foo (id INTEGER);" in result

    def test_preserves_semicolons_inside_comments_by_removing_the_whole_comment(self):
        # This is the exact bug found the hard way: a prose comment like
        # "note; something else" was being misread as two SQL statements by
        # a naive split(";") that didn't know about comments at all.
        sql = "CREATE TABLE foo (id INTEGER);\n-- a comment; with a semicolon in it\nALTER TABLE foo ADD COLUMN bar INTEGER;"
        result = _strip_comments(sql)
        assert "with a semicolon" not in result
        statements = [s.strip() for s in result.split(";") if s.strip()]
        assert len(statements) == 2  # exactly the 2 real statements, not 3

    def test_line_with_only_a_comment_becomes_empty(self):
        result = _strip_comments("-- just a comment\nCREATE TABLE foo (id INTEGER);")
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 1


class TestEnsureSchemaIdempotent:
    """Real end-to-end run against a temp DB + temp schema.sql -- verifies
    the actual behavior that matters: running it twice is safe, and it
    correctly distinguishes "already applied" from "newly applied"."""

    def _run(self, db_path: Path, schema_text: str):
        import ensure_schema
        original_db, original_schema = ensure_schema.DB, ensure_schema.SCHEMA
        schema_path = db_path.parent / "schema.sql"
        schema_path.write_text(schema_text)
        ensure_schema.DB, ensure_schema.SCHEMA = db_path, schema_path
        try:
            ensure_schema.main()
        finally:
            ensure_schema.DB, ensure_schema.SCHEMA = original_db, original_schema

    def test_first_run_creates_table_and_column_second_run_is_a_no_op(self, capsys):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "test.db"
            schema = (
                "CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY);\n"
                "ALTER TABLE foo ADD COLUMN bar INTEGER;\n"
            )
            self._run(db_path, schema)
            first_output = capsys.readouterr().out
            assert "1 table(s) ensured" in first_output
            assert "1 column(s) newly added" in first_output

            self._run(db_path, schema)
            second_output = capsys.readouterr().out
            assert "0 column(s) newly added" in second_output
            assert "1 already present" in second_output

    def test_a_genuinely_new_column_added_later_gets_picked_up(self, capsys):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = Path(tmp) / "test.db"
            self._run(db_path, "CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY);\nALTER TABLE foo ADD COLUMN bar INTEGER;\n")
            capsys.readouterr()

            # Simulates exactly what happened in production: schema.sql gains
            # a new column locally, the live DB hasn't seen it yet.
            self._run(db_path, "CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY);\nALTER TABLE foo ADD COLUMN bar INTEGER;\nALTER TABLE foo ADD COLUMN baz TEXT;\n")
            output = capsys.readouterr().out
            assert "1 column(s) newly added" in output  # just baz
            assert "1 already present" in output  # bar, from before

            conn = sqlite3.connect(db_path)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(foo)")]
            assert "baz" in cols
