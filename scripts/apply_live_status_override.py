"""
Wires live_player_status (fetch_live_team_news.py) into Layer 3's minutes
prediction. See docs/GOTCHAS.md-style reasoning below for the override rule.

Override rule (applied to the model's own P(plays), never to E[minutes|plays] --
live status tells us WHETHER they play, not how long if they do):
  - status in (injured, suspended, unavailable): P(plays) forced to 0,
    regardless of what historical pattern says. A player who was a nailed
    starter last week but has since picked up an injury has a historical rate
    that is now stale in exactly the way this override exists to fix.
  - status == doubtful, with a chance_of_playing_next_round percentage given:
    P(plays) REPLACED (not blended) with that percentage. FPL's own number is
    a doctor-informed estimate for this specific injury -- more authoritative
    than anything a historical model can know, since the model has no way to
    observe an injury at all.
  - status == available (or doubtful with no percentage given): no override,
    use the model's own historical-pattern estimate as-is.

This is NOT backtestable (see docs/multi-gameweek-forecasting.md and the live
collector's own docstring) -- demonstrated here against the REAL current live
snapshot, not a historical test set.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import fit_minutes_model as l3

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"

UNAVAILABLE_STATUSES = {"i", "s", "u"}

# Human-readable labels for the raw single-letter status codes -- used
# wherever status is surfaced to the person (Player Scout, Player
# Performance, Squad Builder, My Team), not just fed into the model.
STATUS_LABELS = {
    "a": "Available",
    "d": "Doubtful",
    "i": "Injured",
    "s": "Suspended",
    "u": "Unavailable",
}


def apply_override(p_played_model: float, status: str, chance_next: float | None) -> float:
    if status in UNAVAILABLE_STATUSES:
        return 0.0
    if status == "d" and chance_next is not None:
        return chance_next / 100.0
    return p_played_model


def load_live_status(conn) -> pd.DataFrame:
    # `news` for display; set-piece order columns added for the same
    # reason -- existing callers that .merge() this or select a specific
    # column subset are unaffected by extra columns.
    return pd.read_sql_query(
        """SELECT player_id, web_name, status, chance_of_playing_next_round, news,
                  penalties_order, direct_freekicks_order, corners_and_indirect_freekicks_order
           FROM live_player_status
           WHERE captured_at = (SELECT MAX(captured_at) FROM live_player_status)
           AND player_id IS NOT NULL""",
        conn,
    )


# Short display codes for set-piece duty, in a fixed display order (pens,
# then direct free-kicks, then corners/indirect free-kicks) -- matches
# exactly what was asked for: "Pen1, Pen2, DF1, DF2, C/IF1, C/IF2". Any order
# number beyond 2 still formats correctly (e.g. "Pen3"), just less common.
SET_PIECE_LABELS = [
    ("penalties_order", "Pen"),
    ("direct_freekicks_order", "DF"),
    ("corners_and_indirect_freekicks_order", "C/IF"),
]


def set_piece_roles(row) -> list[str]:
    """row: a dict/Series-like with the three *_order keys (from
    load_live_status). Returns e.g. ["Pen1", "DF2"] -- only the duties this
    player actually has (non-null order), skipping the rest entirely rather
    than showing a placeholder for "not on this duty"."""
    roles = []
    for col, prefix in SET_PIECE_LABELS:
        order = row.get(col) if hasattr(row, "get") else row[col]
        if order is not None and not pd.isna(order):
            roles.append(f"{prefix}{int(order)}")
    return roles


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    raw = l3.load_data(conn)

    print("Training final Layer 3 model on all 5 seasons...")
    train_df = l3.add_features(raw.copy())
    result = l3.train_and_eval(train_df, train_df)  # final model, not a holdout eval

    print("Computing each player's current state (as of their most recent match)...")
    current = l3.current_state_features(raw.copy())
    current["p_played_model"] = result["clf"].predict_proba(current[l3.FEATURE_COLUMNS])[:, 1]
    current["e_minutes_given_played"] = result["reg"].predict(current[l3.FEATURE_COLUMNS])
    current["expected_minutes_model"] = np.clip(
        current["p_played_model"] * current["e_minutes_given_played"], 0, 95
    )

    live = load_live_status(conn)
    merged = current.merge(live, on="player_id", how="left")
    merged["status"] = merged["status"].fillna("a")  # no live row = assume available

    merged["p_played_final"] = merged.apply(
        lambda r: apply_override(r["p_played_model"], r["status"], r["chance_of_playing_next_round"]),
        axis=1,
    )
    merged["expected_minutes_final"] = np.clip(
        merged["p_played_final"] * merged["e_minutes_given_played"], 0, 95
    )
    merged["overridden"] = (merged["p_played_final"] - merged["p_played_model"]).abs() > 0.01

    n_overridden = merged["overridden"].sum()
    print(f"\n{n_overridden} of {len(merged)} players had their prediction changed by live status\n")

    show_cols = ["web_name", "status", "chance_of_playing_next_round",
                 "p_played_model", "p_played_final", "expected_minutes_model", "expected_minutes_final"]
    overridden = merged[merged["overridden"]].sort_values("expected_minutes_model", ascending=False)
    print("Sample of overridden players (model thought they'd play a lot, live status says otherwise):")
    print(overridden[show_cols].head(15).to_string(
        index=False,
        formatters={"p_played_model": "{:.2f}".format, "p_played_final": "{:.2f}".format,
                    "expected_minutes_model": "{:.1f}".format, "expected_minutes_final": "{:.1f}".format},
    ).encode("ascii", "replace").decode())

    conn.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "live", "ALL", "layer3_live_status_override",
         f"n_players={len(merged)}, n_overridden={int(n_overridden)}"),
    )
    conn.commit()
    print(f"\nLogged run. {int(n_overridden)} live overrides applied out of {len(merged)} players.")
    conn.close()
