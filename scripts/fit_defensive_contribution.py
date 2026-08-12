"""
Layer 4a -- defensive contribution model (see docs/model-architecture.md).

Only 2025-26 has real defensive_contribution data (verified: FPL didn't track
tackles/CBI per-player before that season).

SHRINKAGE FIX: credibility-weighted blend toward position average
(weight = n/(n+K), K learned via within-season split) -- see docs/GOTCHAS.md.
Helped DEF, didn't fully fix MID/FWD; naive still won on LogLoss even after.

NEGATIVE BINOMIAL FIX (this version): diagnosed cause of the remaining gap --
Poisson assumes variance = mean, but defensive-activity counts are likely
over-dispersed (some matches see unusually high tackle/CBI counts, e.g. a
team under sustained pressure). Negative Binomial adds a dispersion parameter
alpha (variance = mean + alpha*mean^2), fit via method-of-moments on the
SAME train split used for K (not re-tuned on the eval data). alpha=0 reduces
to Poisson exactly, so this is a strict generalization, not a different model
family that could do worse by construction.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson, nbinom

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
HALFLIFE_MATCHES = 6
THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}

# RULE FIX (found via backtest_report.py's component calibration check -- see
# docs/GOTCHAS.md): defensive_contribution rates rose substantially over the
# 2025-26 season (DEF +12.0%, MID +9.4%, FWD +22.4%, early vs late season --
# checked directly against real per-gameweek data, a genuine trend, not model
# noise). Plausible real-world cause: 2025-26 is DefCon's FIRST season as a
# scoring category -- players/teams likely adapted tactics once its fantasy
# relevance became clear. A backward-looking EWM necessarily lags a rising
# trend, concentrating the resulting under-prediction on well-established
# players (16+ games, where shrinkage relies almost entirely on the player's
# own historical rate). Learned by inverting the NB survival function to find
# the multiplier on the underlying rate that reproduces the REAL total actual
# hits (1426) from the real total predicted (which implied mu without a
# correction) -- not a naive ratio on the bounded [0,1] probability itself,
# which would be the wrong mechanical fix for a rate-level lag.
# Deliberately a FLAT correction (not trend-shaped): only one season of data
# exists, and assuming the exact same trend SHAPE repeats in 2026-27 would be
# overfitting to a possibly one-time adaptation transient specific to the
# rule's introduction season.
CALIBRATION_MULTIPLIER_MU = 1.0438


def load_data(conn):
    df = pd.read_sql_query(
        """SELECT pgs.player_id, p.name, p.position, pgs.gw, pgs.fixture_id,
                  pgs.minutes, pgs.defensive_contribution,
                  f.kickoff_time
           FROM player_gameweek_stats pgs
           JOIN players p ON pgs.player_id = p.player_id
           JOIN fixtures f ON pgs.fixture_id = f.fixture_id
           WHERE pgs.season_id = '2025-26' AND pgs.defensive_contribution IS NOT NULL
                 AND p.position IN ('DEF','MID','FWD')""",
        conn,
    )
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def add_rate_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def shifted_rate(group):
        dc_shifted = group["defensive_contribution"].shift(1)
        min_shifted = group["minutes"].shift(1)
        ewm_dc = dc_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        ewm_min = min_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        return ewm_dc / (ewm_min / 90).replace(0, np.nan)

    def games_played_before(group):
        return (group["minutes"] > 0).shift(1).fillna(False).cumsum()

    grouped = df.groupby("player_id", group_keys=False)
    df["dc_rate_per90_raw"] = grouped.apply(shifted_rate).values
    df["games_played_before"] = grouped.apply(games_played_before).values
    df["expected_minutes"] = grouped["minutes"].apply(
        lambda s: s.shift(1).ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
    ).values

    pos_avg = df.groupby("position")["dc_rate_per90_raw"].transform("mean")
    overall_avg = df["dc_rate_per90_raw"].mean()
    df["dc_rate_per90_raw"] = df["dc_rate_per90_raw"].fillna(pos_avg)
    df["pos_avg_rate"] = pos_avg.fillna(overall_avg)
    df["expected_minutes"] = df["expected_minutes"].fillna(0)
    return df


def apply_shrinkage(df: pd.DataFrame, K: float) -> pd.Series:
    n = df["games_played_before"]
    weight = n / (n + K) if K > 0 else (n > 0).astype(float)
    return weight * df["dc_rate_per90_raw"] + (1 - weight) * df["pos_avg_rate"]


def get_lambda(df: pd.DataFrame, rate_col: str) -> np.ndarray:
    return (df[rate_col] * (df["expected_minutes"] / 90)).clip(lower=1e-6).to_numpy(dtype=float)


def compute_probability_poisson(df: pd.DataFrame, rate_col: str) -> np.ndarray:
    lam = get_lambda(df, rate_col)
    thresholds = df["position"].map(THRESHOLDS).to_numpy(dtype=int)
    return 1 - poisson.cdf(thresholds - 1, lam)


def fit_alpha_nb(train_df: pd.DataFrame, rate_col: str) -> float:
    """Method-of-moments dispersion: variance = mean + alpha*mean^2, so
    alpha = E[(actual-mean)^2 - mean] / E[mean^2]. Clipped at 0 (no negative
    dispersion -- that would mean under-dispersion, where Poisson is already
    fine or even too spread out; alpha=0 exactly recovers Poisson)."""
    mu = get_lambda(train_df, rate_col)
    actual = train_df["defensive_contribution"].to_numpy(dtype=float)
    residual_sq = (actual - mu) ** 2
    alpha = np.mean(residual_sq - mu) / np.mean(mu ** 2)
    return max(alpha, 0.0)


def compute_probability_nb(df: pd.DataFrame, rate_col: str, alpha: float) -> np.ndarray:
    mu = get_lambda(df, rate_col)
    thresholds = df["position"].map(THRESHOLDS).to_numpy(dtype=int)
    if alpha <= 1e-8:
        return 1 - poisson.cdf(thresholds - 1, mu)  # alpha=0 -> exactly Poisson
    n_param = 1.0 / alpha
    p_param = n_param / (n_param + mu)
    return 1 - nbinom.cdf(thresholds - 1, n_param, p_param)


def brier_and_logloss(p, actual):
    p = np.clip(p, 1e-10, 1 - 1e-10)
    actual = actual.astype(float)
    brier = np.mean((p - actual) ** 2)
    logloss = -np.mean(actual * np.log(p) + (1 - actual) * np.log(1 - p))
    return brier, logloss


def fit_K(train_df: pd.DataFrame) -> float:
    thresholds = train_df["position"].map(THRESHOLDS)
    actual = (train_df["defensive_contribution"] >= thresholds).astype(int)
    candidates = [0, 1, 2, 3, 5, 8, 12, 18, 25, 35, 50]
    losses = []
    for K in candidates:
        rate = apply_shrinkage(train_df, K)
        p = compute_probability_poisson(train_df.assign(_rate=rate), "_rate")
        _, ll = brier_and_logloss(p, actual.values)
        losses.append(ll)
    best_K = candidates[int(np.argmin(losses))]
    return best_K, dict(zip(candidates, losses))


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = load_data(conn)
    df = add_rate_features(df)

    max_gw = df["gw"].max()
    split_gw = max_gw // 2
    train_df = df[df["gw"] <= split_gw].copy()
    print(f"Season has {max_gw} gameweeks. Fitting on GW1-{split_gw}, "
          f"evaluating on GW{split_gw+1}-{max_gw}.\n")

    K, _ = fit_K(train_df)
    train_df["dc_rate_shrunk"] = apply_shrinkage(train_df, K)
    alpha = fit_alpha_nb(train_df, "dc_rate_shrunk")
    print(f"Learned K = {K}, learned NB dispersion alpha = {alpha:.4f}")
    if alpha <= 1e-8:
        print("  (alpha ~ 0 -- data doesn't show meaningful over-dispersion after all; "
              "NB reduces to Poisson, no change expected)\n")
    else:
        print(f"  (alpha > 0 confirms over-dispersion -- NB should help)\n")

    df["dc_rate_shrunk"] = apply_shrinkage(df, K)
    df["p_poisson_noshrink"] = compute_probability_poisson(df, "dc_rate_per90_raw")
    df["p_poisson_shrunk"] = compute_probability_poisson(df, "dc_rate_shrunk")
    df["p_nb_shrunk"] = compute_probability_nb(df, "dc_rate_shrunk", alpha)

    eval_df = df[df["gw"] > split_gw]
    thresholds = eval_df["position"].map(THRESHOLDS)
    actual_hit = (eval_df["defensive_contribution"] >= thresholds).astype(int)

    print(f"Held-out evaluation (GW{split_gw+1}-{max_gw}, {len(eval_df)} rows):")
    for pos in ["DEF", "MID", "FWD"]:
        mask = (eval_df["position"] == pos).values
        results = {}
        for label, col in [("Poisson, no shrink", "p_poisson_noshrink"),
                            ("Poisson, shrunk", "p_poisson_shrunk"),
                            ("NegBinom, shrunk", "p_nb_shrunk")]:
            b, ll = brier_and_logloss(eval_df.loc[mask, col].values, actual_hit[mask].values)
            results[label] = (b, ll)
        naive_p = actual_hit[mask].mean()
        b_naive, ll_naive = brier_and_logloss(np.full(mask.sum(), naive_p), actual_hit[mask].values)

        print(f"\n{pos} (n={mask.sum()}, hit_rate={actual_hit[mask].mean():.3f}):")
        for label, (b, ll) in results.items():
            print(f"  {label:20s} -- Brier: {b:.4f}  LogLoss: {ll:.4f}")
        print(f"  {'naive (flat rate)':20s} -- Brier: {b_naive:.4f}  LogLoss: {ll_naive:.4f}")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2025-26", "DEF/MID/FWD", "defensive_contribution_negbinom",
         f"halflife={HALFLIFE_MATCHES}, K={K}, alpha={alpha:.4f} (both learned), thresholds={THRESHOLDS}"),
    )
    run_id = cur.lastrowid
    for name, val in [("shrinkage_K", K), ("nb_dispersion_alpha", alpha)]:
        cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                    (run_id, name, float(val), "GLOBAL"))
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()
