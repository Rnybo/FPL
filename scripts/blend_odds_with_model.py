"""
Layer 1b -- blend Dixon-Coles model probabilities with market-implied probabilities
(see docs/model-architecture.md). Learns the blend weight alpha from data rather
than assuming a split, and validates that blending actually beats either input
alone on a held-out season (walk-forward, not a random split).

Steps:
1. Build model-implied score grid per fixture from the fitted Dixon-Coles params.
2. De-vig market odds (h2h + totals 2.5), then fit a matching (lambda_home,
   lambda_away) per fixture so the market's own score grid is internally
   consistent -- this gives market-implied clean-sheet probabilities too, not
   just match-result probabilities.
3. Fit alpha (blend weight) on seasons 2021-22..2024-25 by maximizing the
   log-likelihood of actual results (H/D/A + both teams' clean sheets).
4. Evaluate model-only vs market-only vs blend on the held-out 2025-26 season.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
MAX_GOALS = 10
TRAIN_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25"]
HOLDOUT_SEASON = "2025-26"


def score_grid(lh: float, la: float, rho: float, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Full P(home_goals=x, away_goals=y) grid with the Dixon-Coles tau correction."""
    xs = np.arange(max_goals + 1)
    ph = poisson.pmf(xs, lh)
    pa = poisson.pmf(xs, la)
    grid = np.outer(ph, pa)
    # Dixon-Coles low-score correction on the four cells it affects
    grid[0, 0] *= 1 - lh * la * rho
    grid[0, 1] *= 1 + lh * rho
    grid[1, 0] *= 1 + la * rho
    grid[1, 1] *= 1 - rho
    grid = np.clip(grid, 0, None)
    return grid / grid.sum()


def grid_to_outcomes(grid: np.ndarray) -> dict:
    n = grid.shape[0]
    xs = np.arange(n)
    home_win = np.tril(grid, -1).sum()
    draw = np.trace(grid)
    away_win = np.triu(grid, 1).sum()
    over25 = grid[np.add.outer(xs, xs) >= 3].sum()
    home_cs = grid[:, 0].sum()   # away scores 0
    away_cs = grid[0, :].sum()   # home scores 0
    return dict(home_win=home_win, draw=draw, away_win=away_win,
                over25=over25, under25=1 - over25,
                home_cs=home_cs, away_cs=away_cs)


def devig(probs: np.ndarray) -> np.ndarray:
    """Normalize raw 1/odds implied probabilities to remove bookmaker overround."""
    return probs / probs.sum()


def load_dixon_coles_params(conn):
    """Load the most recent dixon_coles run's fitted parameters."""
    run_id = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='dixon_coles' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()[0]
    weights = dict(conn.execute(
        "SELECT feature_name, weight FROM model_weights WHERE run_id=?", (run_id,)
    ).fetchall())
    strength = pd.read_sql_query(
        "SELECT team_name, attack, defence FROM team_strength WHERE run_id=?", conn, params=(run_id,)
    ).set_index("team_name")
    return weights["mu"], weights["home_adv"], weights["rho"], strength


def load_fixtures_with_odds(conn, seasons):
    fixtures = pd.read_sql_query(
        """SELECT f.fixture_id, f.season_id, th.name AS home_team, ta.name AS away_team,
                  f.home_goals, f.away_goals
           FROM fixtures f
           JOIN teams th ON f.home_team_id=th.team_id AND f.season_id=th.season_id
           JOIN teams ta ON f.away_team_id=ta.team_id AND f.season_id=ta.season_id
           WHERE f.season_id IN ({})""".format(",".join("?" * len(seasons))),
        conn, params=seasons,
    )
    odds = pd.read_sql_query(
        "SELECT fixture_id, market, team_or_outcome, price FROM match_odds", conn
    )
    return fixtures, odds


def market_targets_for_fixture(odds: pd.DataFrame, fixture_id: int):
    """De-vigged market probabilities for one fixture, or None if odds missing."""
    sub = odds[odds["fixture_id"] == fixture_id]
    h2h = sub[sub["market"] == "h2h"].set_index("team_or_outcome")["price"]
    tot = sub[sub["market"] == "totals_2.5"].set_index("team_or_outcome")["price"]
    if not {"H", "D", "A"}.issubset(h2h.index) or not {"over", "under"}.issubset(tot.index):
        return None
    raw_hda = devig(1.0 / h2h[["H", "D", "A"]].to_numpy(dtype=float))
    raw_ou = devig(1.0 / tot[["over", "under"]].to_numpy(dtype=float))
    return dict(home_win=raw_hda[0], draw=raw_hda[1], away_win=raw_hda[2],
                over25=raw_ou[0], under25=raw_ou[1])


def fit_market_lambdas(target: dict, rho: float, init_lh: float, init_la: float):
    """Solve for (lambda_home, lambda_away) so the resulting score grid matches
    the market's own de-vigged H/D/A + over/under-2.5 probabilities as closely
    as possible (4 targets, 2 unknowns -- least squares, slightly overdetermined
    by design so noise in the odds doesn't overfit two free parameters)."""

    def residuals(params):
        lh, la = np.exp(params)  # optimize in log-space to keep lambdas positive
        out = grid_to_outcomes(score_grid(lh, la, rho))
        return np.array([
            out["home_win"] - target["home_win"],
            out["draw"] - target["draw"],
            out["away_win"] - target["away_win"],
            out["over25"] - target["over25"],
        ])

    x0 = np.log([max(init_lh, 0.1), max(init_la, 0.1)])
    result = least_squares(residuals, x0)
    lh, la = np.exp(result.x)
    return lh, la


def compute_fixture_probabilities(fixtures, odds, mu, home_adv, rho, strength):
    league_avg_attack, league_avg_defence = 0.0, 0.0
    rows = []
    for row in fixtures.itertuples(index=False):
        a_home = strength["attack"].get(row.home_team, league_avg_attack)
        d_home = strength["defence"].get(row.home_team, league_avg_defence)
        a_away = strength["attack"].get(row.away_team, league_avg_attack)
        d_away = strength["defence"].get(row.away_team, league_avg_defence)

        lh_model = np.exp(mu + a_home + d_away + home_adv)
        la_model = np.exp(mu + a_away + d_home)
        model_out = grid_to_outcomes(score_grid(lh_model, la_model, rho))

        target = market_targets_for_fixture(odds, row.fixture_id)
        if target is None:
            market_out = None
        else:
            lh_mkt, la_mkt = fit_market_lambdas(target, rho, lh_model, la_model)
            market_out = grid_to_outcomes(score_grid(lh_mkt, la_mkt, rho))

        actual_home_cs = int(row.away_goals == 0)
        actual_away_cs = int(row.home_goals == 0)
        if row.home_goals > row.away_goals:
            actual_result = "H"
        elif row.home_goals == row.away_goals:
            actual_result = "D"
        else:
            actual_result = "A"

        rows.append(dict(
            fixture_id=row.fixture_id, season=row.season_id,
            model=model_out, market=market_out,
            actual_result=actual_result, actual_home_cs=actual_home_cs, actual_away_cs=actual_away_cs,
        ))
    return rows


def log_loss_for_alpha(alpha: float, rows: list) -> float:
    """Negative log-likelihood of actual outcomes under the alpha-blend,
    lower is better. Combines match-result (H/D/A) and both clean-sheet
    Bernoulli terms into one joint objective."""
    eps = 1e-10
    total = 0.0
    n = 0
    for r in rows:
        if r["market"] is None:
            continue  # can't blend without a market probability for this fixture
        m, k = r["model"], r["market"]
        p_result = alpha * k[{"H": "home_win", "D": "draw", "A": "away_win"}[r["actual_result"]]] \
                 + (1 - alpha) * m[{"H": "home_win", "D": "draw", "A": "away_win"}[r["actual_result"]]]
        p_home_cs = alpha * k["home_cs"] + (1 - alpha) * m["home_cs"]
        p_away_cs = alpha * k["away_cs"] + (1 - alpha) * m["away_cs"]
        p_home_cs_term = p_home_cs if r["actual_home_cs"] else (1 - p_home_cs)
        p_away_cs_term = p_away_cs if r["actual_away_cs"] else (1 - p_away_cs)
        total += -np.log(max(p_result, eps)) - np.log(max(p_home_cs_term, eps)) - np.log(max(p_away_cs_term, eps))
        n += 1
    return total / max(n, 1)


def fit_alpha(rows: list) -> float:
    alphas = np.linspace(0, 1, 101)
    losses = [log_loss_for_alpha(a, rows) for a in alphas]
    best = alphas[int(np.argmin(losses))]
    return best, dict(zip(alphas.round(2), losses))


ALL_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    mu, home_adv, rho, strength = load_dixon_coles_params(conn)
    print(f"Loaded Dixon-Coles params: mu={mu:.4f}, home_adv={home_adv:.4f}, rho={rho:.4f}\n")

    all_fixtures, odds = load_fixtures_with_odds(conn, ALL_SEASONS)
    rows_by_season = {}
    for season in ALL_SEASONS:
        season_fixtures = all_fixtures[all_fixtures["season_id"] == season]
        rows_by_season[season] = compute_fixture_probabilities(
            season_fixtures, odds, mu, home_adv, rho, strength
        )

    print(f"{'Holdout':<10} {'alpha':>6} {'model':>8} {'blend':>8} {'market':>8}  winner")
    alphas, model_losses, blend_losses, market_losses = [], [], [], []
    for holdout in ALL_SEASONS:
        train_rows = [r for s in ALL_SEASONS if s != holdout for r in rows_by_season[s]]
        alpha, _ = fit_alpha(train_rows)
        holdout_rows = rows_by_season[holdout]

        l_model = log_loss_for_alpha(0.0, holdout_rows)
        l_blend = log_loss_for_alpha(alpha, holdout_rows)
        l_market = log_loss_for_alpha(1.0, holdout_rows)
        winner = min([("model", l_model), ("blend", l_blend), ("market", l_market)], key=lambda kv: kv[1])[0]

        print(f"{holdout:<10} {alpha:>6.2f} {l_model:>8.4f} {l_blend:>8.4f} {l_market:>8.4f}  {winner}")
        alphas.append(alpha); model_losses.append(l_model)
        blend_losses.append(l_blend); market_losses.append(l_market)

    print(f"\nMean across 5 folds: alpha={np.mean(alphas):.2f} (std {np.std(alphas):.2f})  "
          f"model={np.mean(model_losses):.4f}  blend={np.mean(blend_losses):.4f}  market={np.mean(market_losses):.4f}")

    all_rows = [r for s in ALL_SEASONS for r in rows_by_season[s]]
    final_alpha, _ = fit_alpha(all_rows)
    print(f"\nFinal alpha (fit on all 5 seasons, for live use): {final_alpha:.2f}")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "TEAM", "dixon_coles_market_blend",
         f"alpha={final_alpha:.3f}, leave-one-season-out mean_alpha={np.mean(alphas):.2f}"),
    )
    run_id = cur.lastrowid
    cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                (run_id, "alpha", float(final_alpha), "GLOBAL"))
    conn.commit()
    print(f"Saved as model_run_id={run_id}")
    conn.close()
