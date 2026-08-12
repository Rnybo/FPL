"""
Layer 4b -- discrete event models (see docs/model-architecture.md): penalties
missed/saved, cards, own goals, saves. Full 5 seasons available for all of these
(unlike defensive contribution). Same recency-weighted Poisson approach as
Layers 2/4a, applied generically across each event type.

Note: filters to real playing positions only -- FPL's newer "pick a Manager"
novelty pick leaks into this data with position='AM' (confirmed: one such row
was literally Brighton's actual head coach), which isn't a player at all.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
HALFLIFE_MATCHES = 10  # rare events -- longer half-life, more history needed to see any signal

BERNOULLI_EVENTS = ["penalties_missed", "penalties_saved", "yellow_cards", "red_cards", "own_goals"]
POINTS_PER_EVENT = {
    "penalties_missed": -2, "penalties_saved": 5, "yellow_cards": -1,
    "red_cards": -3, "own_goals": -2,
}
ALL_COLUMNS = BERNOULLI_EVENTS + ["saves"]


def load_data(conn):
    cols = ", ".join(f"pgs.{c}" for c in ALL_COLUMNS)
    df = pd.read_sql_query(
        f"""SELECT pgs.player_id, p.name, p.position, pgs.season_id, pgs.gw, pgs.fixture_id,
                   pgs.minutes, {cols}, f.kickoff_time
            FROM player_gameweek_stats pgs
            JOIN players p ON pgs.player_id = p.player_id
            JOIN fixtures f ON pgs.fixture_id = f.fixture_id
            WHERE p.position IN ('GK','DEF','MID','FWD')""",
        conn,
    )
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def add_rate_feature(df: pd.DataFrame, event_col: str) -> pd.Series:
    """Shifted EWMA per-90 rate for one event type -- no lookahead."""
    def shifted_rate(group):
        signal_shifted = group[event_col].shift(1)
        min_shifted = group["minutes"].shift(1)
        ewm_signal = signal_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        ewm_min = min_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        return ewm_signal / (ewm_min / 90).replace(0, np.nan)

    rate = df.groupby("player_id", group_keys=False).apply(shifted_rate)
    rate.index = df.index
    pos_avg = rate.groupby(df["position"]).transform("mean")
    return rate.fillna(pos_avg)


def add_expected_minutes(df: pd.DataFrame) -> pd.Series:
    result = df.groupby("player_id", group_keys=False)["minutes"].apply(
        lambda s: s.shift(1).ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
    )
    result.index = df.index
    return result.fillna(0)


def expected_save_points(lam: np.ndarray, cap: int = 15) -> np.ndarray:
    """E[floor(saves/3)] under Poisson(lam) per row -- exact expectation via the
    pmf grid, not the biased approximation lam/3."""
    ks = np.arange(cap + 1)
    floor_div3 = ks // 3
    pmf = poisson.pmf(ks[:, None], lam[None, :])
    return (floor_div3[:, None] * pmf).sum(axis=0)


def brier_and_logloss(p, actual):
    p = np.clip(p, 1e-10, 1 - 1e-10)
    actual = actual.astype(float)
    brier = np.mean((p - actual) ** 2)
    logloss = -np.mean(actual * np.log(p) + (1 - actual) * np.log(1 - p))
    return brier, logloss


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = load_data(conn)
    df["expected_minutes"] = add_expected_minutes(df)

    print(f"Total rows: {len(df)}\n")
    print("--- Bernoulli events (P(at least one occurrence)) ---")
    for event in BERNOULLI_EVENTS:
        rate = add_rate_feature(df, event)
        lam = (rate * (df["expected_minutes"] / 90)).clip(lower=0)
        p_event = 1 - np.exp(-lam)
        actual = (df[event] > 0).astype(int)

        brier, ll = brier_and_logloss(p_event.values, actual.values)
        hit_rate = actual.mean()
        print(f"{event:20s} hit_rate={hit_rate:.4f}  Brier={brier:.4f}  LogLoss={ll:.4f}  "
              f"pts/event={POINTS_PER_EVENT[event]:+d}")

    print("\n--- Saves (GK only, 1pt per 3 saves -- exact expectation) ---")
    gk = df[df["position"] == "GK"].copy()
    rate = add_rate_feature(df, "saves").loc[gk.index]
    lam = (rate * (gk["expected_minutes"] / 90)).clip(lower=0)
    gk["expected_save_points"] = expected_save_points(lam.values)
    mae = np.mean(np.abs(gk["expected_save_points"] - (gk["saves"] // 3)))
    print(f"GK rows: {len(gk)}  MAE vs actual save-points: {mae:.4f}")
    print(f"Mean expected save points/match: {gk['expected_save_points'].mean():.3f}  "
          f"(actual mean: {(gk['saves']//3).mean():.3f})")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "ALL", "discrete_events_poisson",
         f"halflife_matches={HALFLIFE_MATCHES}, events={BERNOULLI_EVENTS + ['saves']}"),
    )
    run_id = cur.lastrowid
    cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                (run_id, "halflife_matches", float(HALFLIFE_MATCHES), "GLOBAL"))
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()
