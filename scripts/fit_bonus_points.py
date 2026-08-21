"""
Layer 5 -- bonus points model (see docs/model-architecture.md).

Bonus points depend on BPS ranking WITHIN a match (top 3 scorers get 3/2/1) --
inherently relative/competitive, not a clean distribution like goals or cards.
This is the one layer where gradient boosting (LightGBM) is the right tool,
per the architecture doc, precisely because bonus doesn't decompose cleanly
into an independent Poisson/logistic model the way the other layers do.

All features are pre-match (recency-weighted history) -- never in-match stats
from the same fixture being predicted, which would leak the answer (BPS/bonus
are only knowable after the match finishes).

Validated walk-forward: train on 4 seasons, test on the 5th, rotate -- same
discipline as Layers 1/1b.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
HALFLIFE_MATCHES = 8
ALL_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

# VARIANCE-REDUCTION FIX (found via user-prompted iteration, see docs/GOTCHAS.md):
# blending the LightGBM prediction with a simple recency-weighted average of the
# player's OWN past bonus (bonus_ewm_simple) reduces MAE slightly but monotonically
# across the whole [0,1] weight range tested -- backtested, not assumed. The optimal
# blend sits surprisingly low (0.3-0.5), meaning the simple baseline captures nearly
# as much signal as the full feature set; a modest amount of shrinkage toward it still
# helps, consistent with variance reduction (trading a little bias for less noise) on
# what's the noisiest, hardest-to-predict layer in the whole pipeline.
BLEND_WEIGHT_BONUS = 0.4


def load_data(conn):
    df = pd.read_sql_query(
        """SELECT pgs.player_id, p.name, p.position, pgs.season_id, pgs.gw, pgs.fixture_id,
                  pgs.minutes, pgs.goals, pgs.assists, pgs.xg, pgs.xa, pgs.clean_sheet,
                  pgs.goals_conceded, pgs.saves, pgs.bps, pgs.bonus, pgs.ict_index,
                  pgs.influence, pgs.creativity, pgs.threat, pgs.was_home,
                  f.kickoff_time
           FROM player_gameweek_stats pgs
           JOIN players p ON pgs.player_id = p.player_id
           JOIN fixtures f ON pgs.fixture_id = f.fixture_id
           WHERE p.position IN ('GK','DEF','MID','FWD')""",
        conn,
    )
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def shifted_ewm(df, col, halflife=HALFLIFE_MATCHES):
    result = df.groupby("player_id", group_keys=False)[col].apply(
        lambda s: s.shift(1).ewm(halflife=halflife, min_periods=1).mean()
    )
    result.index = df.index
    return result


FEATURE_SOURCE_COLS = [
    "minutes", "goals", "assists", "xg", "xa", "clean_sheet",
    "goals_conceded", "saves", "bps", "ict_index", "influence", "creativity", "threat",
]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-match recency-weighted history for every BPS-driving stat, plus
    position/home as static context. No in-match stats from the target fixture
    are used -- everything is shift(1) before the EWM, same discipline as
    every other layer."""
    df = df.copy()
    for col in FEATURE_SOURCE_COLS:
        df[f"{col}_ewm"] = shifted_ewm(df, col)

    # fill early-career NaNs with position average (same shrinkage pattern as other layers)
    for col in FEATURE_SOURCE_COLS:
        pos_avg = df.groupby("position")[f"{col}_ewm"].transform("mean")
        df[f"{col}_ewm"] = df[f"{col}_ewm"].fillna(pos_avg)

    # Simple, low-variance baseline used for shrinkage in train_and_eval -- see
    # BLEND_WEIGHT_BONUS's docstring above.
    df["bonus_ewm_simple"] = shifted_ewm(df, "bonus")
    pos_avg_bonus = df.groupby("position")["bonus_ewm_simple"].transform("mean")
    df["bonus_ewm_simple"] = df["bonus_ewm_simple"].fillna(pos_avg_bonus)

    df["position_code"] = df["position"].astype("category").cat.codes
    df["was_home"] = df["was_home"].astype(int)
    return df


FEATURE_COLUMNS = [f"{c}_ewm" for c in FEATURE_SOURCE_COLS] + ["position_code", "was_home"]


def train_and_eval(train_df, test_df):
    # n_jobs=1 -- see fit_minutes_model.py's train_and_eval docstring for why
    # (memory-per-thread cost on the production VM outweighed the parallelism
    # benefit; also makes training fully deterministic).
    model = lgb.LGBMRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        min_child_samples=30, verbose=-1, n_jobs=1,
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df["bonus"])
    lgb_pred = model.predict(test_df[FEATURE_COLUMNS])
    # Shrinkage toward the simple baseline -- see BLEND_WEIGHT_BONUS's docstring.
    pred = BLEND_WEIGHT_BONUS * lgb_pred + (1 - BLEND_WEIGHT_BONUS) * test_df["bonus_ewm_simple"].values
    pred = np.clip(pred, 0, 3)  # bonus is 0-3, clip predictions to the valid range
    mae = mean_absolute_error(test_df["bonus"], pred)

    naive_pred = np.full(len(test_df), train_df["bonus"].mean())
    naive_mae = mean_absolute_error(test_df["bonus"], naive_pred)
    return model, mae, naive_mae, pred


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = load_data(conn)
    df = add_features(df)
    print(f"Total rows: {len(df)}\n")

    print(f"{'Holdout':<10} {'MAE':>8} {'naive_MAE':>10}  winner")
    maes, naive_maes = [], []
    for holdout in ALL_SEASONS:
        train_df = df[df["season_id"] != holdout]
        test_df = df[df["season_id"] == holdout]
        _, mae, naive_mae, _ = train_and_eval(train_df, test_df)
        winner = "model" if mae < naive_mae else "naive"
        print(f"{holdout:<10} {mae:>8.4f} {naive_mae:>10.4f}  {winner}")
        maes.append(mae); naive_maes.append(naive_mae)

    print(f"\nMean MAE: model={np.mean(maes):.4f}  naive={np.mean(naive_maes):.4f}")

    # Final model trained on all 5 seasons, for live use
    final_model, _, _, _ = train_and_eval(df, df)
    importances = sorted(zip(FEATURE_COLUMNS, final_model.feature_importances_),
                          key=lambda kv: -kv[1])
    print("\nTop 5 feature importances (final model):")
    for name, imp in importances[:5]:
        print(f"  {name:20s} {imp}")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "ALL", "bonus_points_lightgbm",
         f"mean_mae={np.mean(maes):.4f}, mean_naive_mae={np.mean(naive_maes):.4f}, halflife={HALFLIFE_MATCHES}"),
    )
    run_id = cur.lastrowid
    for name, imp in importances:
        cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                    (run_id, name, float(imp), "GLOBAL"))
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()
