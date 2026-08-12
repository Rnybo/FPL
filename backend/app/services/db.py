"""Shared SQLite access -- read-only from the API's perspective. Writes only
happen via the existing scripts/ pipeline (fetch_*, fit_*, predict_upcoming),
which the scheduler in scheduler.py triggers -- the API itself never writes
model data, keeping "what changes the model" in one place (the scripts),
not duplicated into API request handlers."""
import sqlite3
import pandas as pd

from app.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)
