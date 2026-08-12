"""
Layer 1 -- Dixon-Coles team goal model (see docs/model-architecture.md).

Fits attack/defence strength per team, a home-advantage term, and the Dixon-Coles
low-score correlation term (rho), using all finished fixtures across the 5 cached
seasons, weighted by recency (older matches count less -- exponential time decay).

Reference: Dixon, M.J. and Coles, S.G. (1997), "Modelling Association Football
Scores and Inefficiencies in the Football Betting Market", J. Royal Stat. Soc.

Model:
    lambda_home = exp(mu + attack_home + defence_away + home_adv)
    lambda_away = exp(mu + attack_away + defence_home)
    P(x, y) = tau(x, y; rho) * Poisson(x; lambda_home) * Poisson(y; lambda_away)

tau is the Dixon-Coles correction that boosts/dampens the probability of low
scorelines (0-0, 1-0, 0-1, 1-1), which independent Poisson underestimates/overestimates.

Team attack/defence parameters are L2-regularized toward 0 (i.e. toward "average"),
which is exactly the shrinkage behaviour we want for newly promoted teams with
little/no data in this window -- they get pulled toward the league-average strength
rather than an unstable estimate from a handful of matches.
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"

XI = 0.0018        # time-decay rate per day (Dixon-Coles literature-typical value)
L2_LAMBDA = 0.01   # regularization strength on attack/defence params


def load_matches(conn) -> pd.DataFrame:
    query = """
        SELECT f.kickoff_time, f.home_goals, f.away_goals,
               th.name AS home_team, ta.name AS away_team
        FROM fixtures f
        JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
        JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
        WHERE f.finished = 1
    """
    df = pd.read_sql_query(query, conn)
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    return df


def tau_vec(x, y, lh, la, rho):
    """Vectorized Dixon-Coles low-score correction over numpy arrays."""
    tau = np.ones_like(lh)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    tau[m00] = 1 - lh[m00] * la[m00] * rho
    tau[m01] = 1 + lh[m01] * rho
    tau[m10] = 1 + la[m10] * rho
    tau[m11] = 1 - rho
    return tau


def neg_log_likelihood(params, home_idx, away_idx, x, y, weights, n):
    """Fully vectorized NLL -- no per-match Python loop, so gradients (finite-diff
    via L-BFGS-B) are cheap enough to fit ~1900 matches / ~85 params interactively."""
    mu, home_adv, rho = params[0], params[1], params[2]
    attack = params[3 : 3 + n]
    defence = params[3 + n : 3 + 2 * n]

    lh = np.exp(mu + attack[home_idx] + defence[away_idx] + home_adv)
    la = np.exp(mu + attack[away_idx] + defence[home_idx])

    tau = tau_vec(x, y, lh, la, rho)
    p = tau * poisson.pmf(x, lh) * poisson.pmf(y, la)
    p = np.clip(p, 1e-10, None)

    ll = np.sum(weights * np.log(p))
    reg = L2_LAMBDA * (np.sum(attack**2) + np.sum(defence**2))
    return -ll + reg


def fit(matches: pd.DataFrame):
    teams = sorted(set(matches["home_team"]) | set(matches["away_team"]))
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    home_idx = matches["home_team"].map(idx).to_numpy()
    away_idx = matches["away_team"].map(idx).to_numpy()
    x = matches["home_goals"].to_numpy(dtype=float)
    y = matches["away_goals"].to_numpy(dtype=float)

    latest = matches["kickoff_time"].max()
    days_ago = (latest - matches["kickoff_time"]).dt.days.values
    weights = np.exp(-XI * days_ago)

    x0 = np.zeros(3 + 2 * n)
    x0[0] = np.log(matches[["home_goals", "away_goals"]].values.mean())  # mu init
    x0[1] = 0.25   # home_adv init
    x0[2] = -0.1   # rho init

    result = minimize(
        neg_log_likelihood, x0, args=(home_idx, away_idx, x, y, weights, n),
        method="L-BFGS-B",
        options={"maxiter": 500},
    )

    mu, home_adv, rho = result.x[0], result.x[1], result.x[2]
    attack = dict(zip(teams, result.x[3 : 3 + n]))
    defence = dict(zip(teams, result.x[3 + n : 3 + 2 * n]))
    return mu, home_adv, rho, attack, defence, latest, result


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    matches = load_matches(conn)
    n_teams = len(set(matches["home_team"]) | set(matches["away_team"]))
    print(f"Loaded {len(matches)} finished matches across {n_teams} distinct teams")

    mu, home_adv, rho, attack, defence, latest, result = fit(matches)

    print(f"\nConverged: {result.success}, NLL: {result.fun:.2f}")
    print(f"mu (baseline log-rate): {mu:.4f}")
    print(f"home_adv: {home_adv:.4f}")
    print(f"rho (low-score correlation): {rho:.4f}")

    ranked = sorted(attack.items(), key=lambda kv: -kv[1])
    print("\nTop 5 attack strength:")
    for t, v in ranked[:5]:
        print(f"  {t:20s} attack={v:+.3f}  defence={defence[t]:+.3f}")
    print("Bottom 5 attack strength:")
    for t, v in ranked[-5:]:
        print(f"  {t:20s} attack={v:+.3f}  defence={defence[t]:+.3f}")

    # Persist to model_runs / model_weights / team_strength
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            "2021-22..2025-26",
            "TEAM",
            "dixon_coles",
            f"xi={XI}, l2_lambda={L2_LAMBDA}, as_of={latest.isoformat()}",
        ),
    )
    run_id = cur.lastrowid

    for name, val in [("mu", mu), ("home_adv", home_adv), ("rho", rho), ("xi", XI)]:
        cur.execute(
            "INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?, ?, ?, ?)",
            (run_id, name, float(val), "GLOBAL"),
        )

    as_of = latest.isoformat()
    for team in attack:
        cur.execute(
            "INSERT INTO team_strength (run_id, team_name, attack, defence, as_of_date) VALUES (?, ?, ?, ?, ?)",
            (run_id, team, float(attack[team]), float(defence[team]), as_of),
        )

    conn.commit()
    conn.close()
    print(f"\nSaved as model_run_id={run_id}")
