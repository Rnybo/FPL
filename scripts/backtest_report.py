"""
backtest_report.py -- the diagnostic layer on top of combine_xp.py's walk-forward
predictions. combine_xp.py already validates leave-one-season-out and reports
ONE pooled MAE across all 5 seasons (0.988) -- useful as a headline number, but
it can hide exactly the kind of systematic bias that matters for actually
improving the model: errors in opposite directions cancel out in a pooled
average. This script slices the SAME walk-forward predictions by season,
position, player tier, season-stage, and scoring component to find SPECIFIC,
actionable learnings -- not just confirm the aggregate number again.

Designed to be re-run after every model change: this is the feedback loop the
project asked for ("train on old games, iterate, get smarter"), made concrete
and repeatable rather than a one-off check.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

import combine_xp as cx

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"


def mae_bias_corr(actual, predicted):
    """bias = mean(predicted - actual): positive means we systematically
    OVER-predict, negative means we UNDER-predict. MAE alone can't tell you
    the direction -- this is the number that actually points at a fix."""
    mae = mean_absolute_error(actual, predicted)
    bias = np.mean(predicted - actual)
    corr = np.corrcoef(actual, predicted)[0, 1] if len(actual) > 1 else float("nan")
    return mae, bias, corr


def report_by_group(valid, group_col, label):
    print(f"\n=== By {label} ===")
    rows = []
    for key, g in valid.groupby(group_col):
        mae, bias, corr = mae_bias_corr(g["total_points"], g["xP"])
        rows.append((key, len(g), mae, bias, corr))
    out = pd.DataFrame(rows, columns=[label, "n", "MAE", "bias(pred-actual)", "corr"])
    print(out.to_string(index=False, formatters={
        "MAE": "{:.3f}".format, "bias(pred-actual)": "{:+.3f}".format, "corr": "{:.3f}".format,
    }))
    return out


def report_by_tier(valid, label="season-total-points tier (OUTCOME-based -- see caveat below)"):
    """CAVEAT, found via direct verification (see docs/GOTCHAS.md): tiering by a
    player's OWN realized season-total points is tiering by the OUTCOME, not by
    anything knowable in advance. A controlled test with a PROVABLY unbiased
    predictor (predicts true ability exactly; actual = ability + pure random
    noise) still showed bias +4.0 for the bottom outcome-quartile and -4.1 for
    the top, despite zero overall bias by construction -- this is regression-
    to-the-mean under outcome-based selection, a real statistical property of
    ANY imperfect predictor, not evidence of a fixable model flaw. Kept here
    for comparison against report_by_price_tier (the trustworthy version)
    specifically so this artifact stays visible rather than silently vanishing."""
    season_totals = valid.groupby(["player_id", "season_id"])["total_points"].sum().rename("season_total")
    v = valid.merge(season_totals, on=["player_id", "season_id"])
    v["tier"] = pd.qcut(v["season_total"], 4, labels=["Q1 (fringe)", "Q2", "Q3", "Q4 (stars)"], duplicates="drop")
    return report_by_group(v, "tier", label)


def report_by_price_tier(valid, label="price tier (EX-ANTE -- known before the match, trustworthy)"):
    """The fix: tier by price_at_time instead of realized season points. Price
    is set by FPL based on expected quality and is known BEFORE the match is
    played -- grouping by it can't manufacture the regression-to-the-mean
    artifact report_by_tier is vulnerable to, since it doesn't condition on
    the very outcome being evaluated. If a real bias by player quality
    exists, THIS is the check that would actually show it credibly."""
    v = valid.copy()
    v["tier"] = pd.qcut(v["price_at_time"], 4, labels=["Q1 (cheapest)", "Q2", "Q3", "Q4 (priciest)"], duplicates="drop")
    return report_by_group(v, "tier", label)


def report_by_season_stage(valid):
    """Early (GW1-10) vs mid (GW11-28) vs late (GW29-38) season -- tests
    whether accuracy improves as more in-season data becomes available, and
    specifically how bad the EARLY-season case is, since that's the hardest,
    most-current-to-our-actual-situation scenario (predicting 2026-27 with
    zero in-season data is exactly an 'early season' prediction)."""
    v = valid.copy()
    v["stage"] = pd.cut(v["gw"], bins=[0, 10, 28, 38], labels=["Early (GW1-10)", "Mid (GW11-28)", "Late (GW29-38)"])
    return report_by_group(v, "stage", "season stage")


def report_component_calibration(df, conn):
    """Sums PREDICTED vs ACTUAL for each individual countable event across the
    whole dataset -- catches systematic over/under-prediction at the
    component level even when it's invisible in the pooled xP MAE (offsetting
    errors in different components can cancel out in the total)."""
    print("\n=== Component-level calibration (total predicted vs total actual) ===")

    # Actual clean sheet needs the REAL match score, not team_lambda_against
    # (a PREDICTED value -- comparing it to itself would be meaningless).
    scores = pd.read_sql_query("SELECT fixture_id, home_goals, away_goals FROM fixtures", conn)
    d = df.merge(scores, on="fixture_id", how="left")
    opponent_goals = np.where(d["was_home"] == 1, d["away_goals"], d["home_goals"])
    d["actual_clean_sheet"] = (opponent_goals == 0).astype(float)
    d["actual_defcon_hit"] = 0.0
    for pos, threshold in cx.DEFCON_THRESHOLDS.items():
        m = d["position"] == pos
        d.loc[m, "actual_defcon_hit"] = (d.loc[m, "defensive_contribution"] >= threshold).astype(float)

    # RULE FIX (found via user-prompted iteration -- see docs/GOTCHAS.md): the real
    # cs_pts formula in combine_xp.py is p_clean_sheet * points * p_60plus (a player
    # only banks clean-sheet points if they played 60+ minutes). Checking p_clean_sheet
    # alone against actual_clean_sheet alone measures a DIFFERENT quantity than what
    # actually drives predicted points -- showed +4.7% that way, but the real driver
    # (the product, matching the actual formula) is only +2.2%. Multiplying both sides
    # by p_60plus/actual_60plus here so this check matches what the model actually predicts.
    d["p_60plus"] = d["layer3_p_played"] * d["layer3_p_60plus_given_played"]
    d["actual_60plus"] = (d["minutes"] >= 60).astype(float)
    checks = [
        ("Goals", d["lambda_goal"], d["goals"]),
        ("Assists", d["lambda_assist"], d["assists"]),
        ("Clean sheets (points-relevant: requires 60+ mins)",
         d["p_clean_sheet"] * d["p_60plus"], d["actual_clean_sheet"] * d["actual_60plus"]),
        ("Def. contribution hit", d["expected_defcon_points"] / cx.DEFCON_POINTS, d["actual_defcon_hit"]),
        ("Bonus points", d["expected_bonus"], d["bonus"]),
    ]
    rows = []
    for name, pred, actual in checks:
        valid_mask = pred.notna() & actual.notna()
        p_sum, a_sum = pred[valid_mask].sum(), actual[valid_mask].sum()
        rows.append((name, p_sum, a_sum, (p_sum - a_sum) / a_sum * 100 if a_sum else float("nan")))
    out = pd.DataFrame(rows, columns=["Component", "Total predicted", "Total actual", "% over/under"])
    print(out.to_string(index=False, formatters={
        "Total predicted": "{:.1f}".format, "Total actual": "{:.1f}".format, "% over/under": "{:+.1f}%".format,
    }))


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    print("Building walk-forward xP predictions (leave-one-season-out, same as combine_xp.py)...")
    df = cx.build_combined_xp_dataframe(conn)
    valid = df.dropna(subset=["xP"])

    overall_mae, overall_bias, overall_corr = mae_bias_corr(valid["total_points"], valid["xP"])
    print(f"\n=== Overall (pooled across all seasons -- the headline number) ===")
    print(f"MAE={overall_mae:.3f}  bias={overall_bias:+.3f}  corr={overall_corr:.3f}  n={len(valid)}")

    report_by_group(valid, "season_id", "season")
    report_by_group(valid, "position", "position")
    report_by_tier(valid)
    report_by_price_tier(valid)
    report_by_season_stage(valid)
    report_component_calibration(df, conn)

    conn.close()
