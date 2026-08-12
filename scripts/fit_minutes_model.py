"""
Layer 3 -- minutes/rotation model (see docs/model-architecture.md).

Two-stage "hurdle" model, standard approach for bimodal minutes data (played
0 vs. played a large chunk vs. played a sub cameo):
  Stage A: P(plays at all this gameweek)      -- LightGBM classifier
  Stage B: E[minutes | plays]                 -- LightGBM regressor, fit only
                                                  on rows where the player played
  Combined: expected_minutes = P(plays) * E[minutes | plays]

This REPLACES the placeholder used in Layer 2 (fit_player_involvement.py),
which just used each player's unconditional recency-weighted average minutes.
Validated here against exactly that placeholder as the baseline.

No lookahead: every feature is built from strictly prior matches (shift(1)
before any EWM/aggregation).
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, log_loss, brier_score_loss

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"
HALFLIFE_MATCHES = 6
ALL_SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]


def load_data(conn):
    df = pd.read_sql_query(
        """SELECT pgs.player_id, p.name, p.position, pgs.season_id, pgs.gw, pgs.fixture_id,
                  pgs.minutes, pgs.price_at_time, pgs.was_home, f.kickoff_time,
                  f.home_team_id, f.away_team_id
           FROM player_gameweek_stats pgs
           JOIN players p ON pgs.player_id = p.player_id
           JOIN fixtures f ON pgs.fixture_id = f.fixture_id
           WHERE p.position IN ('GK','DEF','MID','FWD')""",
        conn,
    )
    # team_id per row -- needed for is_transfer (see add_features). Same
    # was_home-based reconstruction pattern used in fit_player_involvement.py.
    df["team_id"] = np.where(df["was_home"] == 1, df["home_team_id"], df["away_team_id"])
    df["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True)
    df["played"] = (df["minutes"] > 0).astype(int)
    return df.sort_values(["player_id", "kickoff_time"]).reset_index(drop=True)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def per_player(group):
        played_shifted = group["played"].shift(1)
        minutes_shifted = group["minutes"].shift(1)

        # unconditional recency-weighted average minutes (the OLD Layer 2 placeholder)
        ewm_minutes_unconditional = minutes_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()

        # recency-weighted play RATE (fraction of recent matches they featured at all)
        ewm_play_rate = played_shifted.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()

        # minutes conditional on having played -- ewm over only the played subsequence,
        # then forward-filled back onto every row (recency measured in "matches played")
        played_minutes_only = minutes_shifted.where(played_shifted == 1)
        ewm_minutes_conditional = played_minutes_only.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean().ffill()

        last_match_minutes = minutes_shifted
        price_shifted = group["price_at_time"].shift(1)

        # NEW: gap in days since the previous match, as of THIS match's kickoff. Directly
        # targets a real bug found via user investigation (see docs/GOTCHAS.md): the model
        # was trusting last_match_minutes==0 as strongly at a season boundary (a summer-long
        # gap, often a meaningless end-of-season rest) as it does mid-season (where 0 minutes
        # usually means injury/dropped -- a genuinely strong signal there). Adding the gap
        # itself as a feature lets the model LEARN to discount last_match_minutes when the
        # gap is large, rather than hardcoding a rule at inference time only (which would
        # create a train/inference mismatch -- the model never saw that rule during training).
        kickoff_shifted = group["kickoff_time"].shift(1)
        days_since_last_match = (group["kickoff_time"] - kickoff_shifted).dt.days

        # FOLLOW-UP FIX (see docs/GOTCHAS.md): days_since_last_match alone wasn't enough --
        # checked directly and found the tree ensemble still under-uses it, most likely
        # because the specific "reliable starter rests OR rare backup gets a runout right at
        # a season boundary" pattern only has ~20-1000 clean historical examples to learn
        # from, too few for trees to isolate this three-way interaction reliably from raw
        # features. Engineering the interaction directly as its own feature gives the model
        # a much stronger prior without hardcoding the OUTPUT rule -- how much to trust this
        # feature vs. the others is still learned, not assumed. A 30-day decay scale keeps a
        # normal 7-day gap's signal mostly intact (~0.79x) while crushing a ~80-day
        # off-season gap's signal toward zero (~0.07x).
        decayed_last_match_signal = last_match_minutes * np.exp(-days_since_last_match / 30)

        # games since last appearance -- counts consecutive zero-minute matches immediately before this one
        zero_run = (played_shifted == 0).astype(int)
        games_since_last = zero_run.groupby((zero_run != zero_run.shift()).cumsum()).cumsum()
        games_since_last = games_since_last.where(zero_run == 1, 0)

        # NEW (found via user-prompted investigation into an external-tool
        # comparison -- see docs/GOTCHAS.md): ewm_play_rate has NO season-
        # boundary protection of its own, unlike last_match_minutes (which
        # gets decayed_last_match_signal). A player who was an undisputed
        # starter all season but rested once at a dead-rubber season finale
        # (extremely common, not unique to any one player) sees ewm_play_rate
        # drop sharply from that single benign zero, even though it's not a
        # genuine rotation-risk signal -- confirmed directly for David Raya:
        # ewm_play_rate reads 0.891 heading into 2026-27 despite 12/12 real
        # 90-minute appearances before that one end-of-season rest (true
        # underlying reliability is essentially 1.0). ewm_one_earlier captures
        # the play-rate as it stood BEFORE that last, ambiguous observation --
        # letting the model see both the "including" and "excluding" view
        # rather than only the (possibly corrupted) current one. Backtested
        # honestly: closes roughly a quarter of the real ~2pp GK-specific
        # under-confidence for this exact pattern, no measurable cost to
        # overall LogLoss/Brier -- modest, not a full fix, but a genuine,
        # validated improvement with no downside.
        ewm_one_earlier = ewm_play_rate.shift(1)

        # NEW (user pushed back on the earlier "minutes is well-calibrated"
        # conclusion, correctly -- see docs/GOTCHAS.md): checked whether a
        # transfer specifically (different club than the player's previous
        # match) is a real blind spot. Confirmed directly via backtest: for
        # transfer rows specifically, p_played is under-predicted by ~3.2pp
        # and expected_minutes by ~2 minutes on average, vs essentially zero
        # bias for non-transfers. Makes sense mechanically: every EWM feature
        # here is built from the player's OWN history, which for a transfer
        # reflects their OLD club's context (competition for their position,
        # tactical fit, manager trust) -- info that doesn't carry over, while
        # a new club's transfer fee/role is a genuinely new signal our
        # historical-EWM features can't see. Only ~0.87% of rows, but this is
        # exactly the situation concentrated hardest at THIS moment: pre-
        # season, when every summer transfer hits it simultaneously.
        team_shifted = group["team_id"].shift(1)
        is_transfer = (team_shifted.notna() & (team_shifted != group["team_id"])).astype(int)

        return pd.DataFrame({
            "ewm_minutes_unconditional": ewm_minutes_unconditional,
            "ewm_play_rate": ewm_play_rate,
            "ewm_one_earlier": ewm_one_earlier,
            "ewm_minutes_conditional": ewm_minutes_conditional,
            "last_match_minutes": last_match_minutes,
            "days_since_last_match": days_since_last_match,
            "decayed_last_match_signal": decayed_last_match_signal,
            "price_shifted": price_shifted,
            "games_since_last": games_since_last,
            "is_transfer": is_transfer,
        }, index=group.index)

    features = df.groupby("player_id", group_keys=False).apply(per_player)
    features.index = df.index
    df = pd.concat([df, features], axis=1)

    for col in ["ewm_minutes_unconditional", "ewm_play_rate", "ewm_minutes_conditional",
                "last_match_minutes", "price_shifted"]:
        pos_avg = df.groupby("position")[col].transform("mean")
        df[col] = df[col].fillna(pos_avg)
    df["days_since_last_match"] = df["days_since_last_match"].fillna(365)  # no prior match -> treat as a long gap
    df["decayed_last_match_signal"] = df["last_match_minutes"] * np.exp(-df["days_since_last_match"] / 30)
    df["games_since_last"] = df["games_since_last"].fillna(0)
    df["ewm_one_earlier"] = df["ewm_one_earlier"].fillna(df["ewm_play_rate"])
    df["is_transfer"] = df["is_transfer"].fillna(0).astype(int)
    df["position_code"] = df["position"].astype("category").cat.codes
    return df


FEATURE_COLUMNS = ["ewm_play_rate", "ewm_one_earlier", "ewm_minutes_conditional", "last_match_minutes",
                    "days_since_last_match", "decayed_last_match_signal",
                    "price_shifted", "games_since_last", "position_code", "is_transfer"]

# Sample weighting -- transfer rows are ~0.87% of data, even rarer than the
# boundary pattern (~3.4%), so the loss function won't prioritize them without
# an explicit boost. Same rationale as BOUNDARY_SAMPLE_WEIGHT.
TRANSFER_SAMPLE_WEIGHT = 15

# Sample weighting for the P(plays) classifier -- see docs/GOTCHAS.md: the season-boundary
# pattern (rested reliable starters, backup runouts) is only ~3.4% of rows, too rare for the
# loss function to prioritize even with the right features engineered. Weighting these rows
# up cuts the "reliable starter rested" miscalibration roughly in half (checked directly via
# backtest) for a small, deliberate cost (~0.001-0.002 LogLoss) on the other 96.6% of rows.
BOUNDARY_DAYS_THRESHOLD = 30
BOUNDARY_SAMPLE_WEIGHT = 15


def _boundary_weights(frame):
    is_boundary = (frame["days_since_last_match"] > BOUNDARY_DAYS_THRESHOLD).astype(float)
    is_transfer = frame["is_transfer"].astype(float) if "is_transfer" in frame.columns else 0.0
    return 1 + (BOUNDARY_SAMPLE_WEIGHT - 1) * is_boundary + (TRANSFER_SAMPLE_WEIGHT - 1) * is_transfer


def train_and_eval(train_df, test_df):
    weights = _boundary_weights(train_df)
    clf = lgb.LGBMClassifier(n_estimators=150, max_depth=4, learning_rate=0.05,
                              min_child_samples=30, verbose=-1)
    clf.fit(train_df[FEATURE_COLUMNS], train_df["played"], sample_weight=weights)
    p_played_test = clf.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]

    reg = lgb.LGBMRegressor(n_estimators=150, max_depth=4, learning_rate=0.05,
                             min_child_samples=30, verbose=-1)
    played_train = train_df[train_df["played"] == 1]
    reg.fit(played_train[FEATURE_COLUMNS], played_train["minutes"])
    e_minutes_given_played_test = reg.predict(test_df[FEATURE_COLUMNS])

    played_train = played_train.copy()
    played_train["played_60plus"] = (played_train["minutes"] >= 60).astype(int)
    clf60_weights = _boundary_weights(played_train)
    clf60 = lgb.LGBMClassifier(n_estimators=150, max_depth=4, learning_rate=0.05,
                                min_child_samples=30, verbose=-1)
    clf60.fit(played_train[FEATURE_COLUMNS], played_train["played_60plus"], sample_weight=clf60_weights)
    p_60plus_given_played_test = clf60.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]

    expected_minutes = p_played_test * e_minutes_given_played_test
    expected_minutes = np.clip(expected_minutes, 0, 95)

    mae_model = mean_absolute_error(test_df["minutes"], expected_minutes)
    mae_naive = mean_absolute_error(test_df["minutes"], test_df["ewm_minutes_unconditional"])

    ll = log_loss(test_df["played"], p_played_test, labels=[0, 1])
    brier = brier_score_loss(test_df["played"], p_played_test)

    return dict(mae_model=mae_model, mae_naive=mae_naive, logloss=ll, brier=brier,
                clf=clf, reg=reg, clf60=clf60,
                p_played=p_played_test, e_minutes_given_played=e_minutes_given_played_test,
                p_60plus_given_played=p_60plus_given_played_test)


if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    df = load_data(conn)
    df = add_features(df)
    print(f"Total rows: {len(df)}  (played rate: {df['played'].mean():.3f})\n")

    print(f"{'Holdout':<10} {'MAE_model':>10} {'MAE_naive':>10} {'LogLoss':>8} {'Brier':>7}  winner")
    results = []
    for holdout in ALL_SEASONS:
        train_df = df[df["season_id"] != holdout]
        test_df = df[df["season_id"] == holdout]
        r = train_and_eval(train_df, test_df)
        winner = "model" if r["mae_model"] < r["mae_naive"] else "naive"
        print(f"{holdout:<10} {r['mae_model']:>10.3f} {r['mae_naive']:>10.3f} "
              f"{r['logloss']:>8.4f} {r['brier']:>7.4f}  {winner}")
        results.append(r)

    mean_mae_model = np.mean([r["mae_model"] for r in results])
    mean_mae_naive = np.mean([r["mae_naive"] for r in results])
    print(f"\nMean MAE: model={mean_mae_model:.3f}  naive={mean_mae_naive:.3f}")

    # Final model trained on all 5 seasons, for live use
    final = train_and_eval(df, df)
    importances_clf = sorted(zip(FEATURE_COLUMNS, final["clf"].feature_importances_), key=lambda kv: -kv[1])
    print("\nFeature importances (P(plays) classifier):")
    for name, imp in importances_clf:
        print(f"  {name:24s} {imp}")

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO model_runs (trained_at, season_range, position_group, model_type, notes) VALUES (?,?,?,?,?)",
        (pd.Timestamp.now("UTC").isoformat(), "2021-22..2025-26", "ALL", "minutes_hurdle_lightgbm",
         f"mean_mae_model={mean_mae_model:.3f}, mean_mae_naive={mean_mae_naive:.3f}, halflife={HALFLIFE_MATCHES}"),
    )
    run_id = cur.lastrowid
    for name, imp in importances_clf:
        cur.execute("INSERT INTO model_weights (run_id, feature_name, weight, position_group) VALUES (?,?,?,?)",
                    (run_id, name, float(imp), "GLOBAL"))
    conn.commit()
    print(f"\nSaved as model_run_id={run_id}")
    conn.close()


def current_state_features(df: pd.DataFrame, current_team_by_player: dict | None = None) -> pd.DataFrame:
    """One row per player: their feature vector for predicting the NEXT
    (not-yet-played) match -- i.e. the same EWM formulas as add_features, but
    INCLUDING their most recent actual match rather than shifted past it. This
    is the correct 'as of right now' state for live prediction, as opposed to
    add_features's shift(1) which is for backtesting against a known outcome.

    current_team_by_player: {player_id: current_team_id}, from players.current_team_id
    (kept current by fetch_current_roster.py) -- needed for is_transfer, since a
    fresh summer signing may have ZERO match rows yet for their new club, so the
    comparison can't be done from this dataframe's own historical rows alone."""
    df = df.copy()

    def per_player(group):
        ewm_play_rate = group["played"].ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean()
        ewm_one_earlier = ewm_play_rate.shift(1)  # see add_features's docstring for why this matters
        played_minutes_only = group["minutes"].where(group["played"] == 1)
        ewm_minutes_conditional = played_minutes_only.ewm(halflife=HALFLIFE_MATCHES, min_periods=1).mean().ffill()
        last_match_minutes = group["minutes"]
        price = group["price_at_time"]

        zero_run = (group["played"] == 0).astype(int)
        games_since_last = zero_run.groupby((zero_run != zero_run.shift()).cumsum()).cumsum()
        games_since_last = games_since_last.where(zero_run == 1, 0)

        return pd.DataFrame({
            "ewm_play_rate": ewm_play_rate,
            "ewm_one_earlier": ewm_one_earlier,
            "ewm_minutes_conditional": ewm_minutes_conditional,
            "last_match_minutes": last_match_minutes,
            "price_shifted": price,
            "games_since_last": games_since_last,
            "last_match_team_id": group["team_id"],
        }, index=group.index)

    features = df.groupby("player_id", group_keys=False).apply(per_player)
    features.index = df.index
    df = pd.concat([df, features], axis=1)

    for col in ["ewm_play_rate", "ewm_minutes_conditional", "last_match_minutes", "price_shifted"]:
        pos_avg = df.groupby("position")[col].transform("mean")
        df[col] = df[col].fillna(pos_avg)
    df["games_since_last"] = df["games_since_last"].fillna(0)
    df["ewm_one_earlier"] = df["ewm_one_earlier"].fillna(df["ewm_play_rate"])
    df["position_code"] = df["position"].astype("category").cat.codes

    latest = df.sort_values("kickoff_time").groupby("player_id").tail(1).copy()
    # days_since_last_match here means "as of TODAY" (when this prediction is actually being
    # run), not the per-row historical gap used in add_features -- this is the quantity that
    # was missing and caused the season-boundary bug (see docs/GOTCHAS.md): right after the
    # season ends, this correctly reads as a large number (~90 days), letting the trained
    # model discount last_match_minutes the way it learned to at past season boundaries.
    latest["days_since_last_match"] = (pd.Timestamp.now(tz="UTC") - latest["kickoff_time"]).dt.days.clip(lower=0)
    latest["decayed_last_match_signal"] = latest["last_match_minutes"] * np.exp(-latest["days_since_last_match"] / 30)

    if current_team_by_player:
        current_team = latest["player_id"].map(current_team_by_player)
        latest["is_transfer"] = (
            current_team.notna() & latest["last_match_team_id"].notna()
            & (current_team != latest["last_match_team_id"])
        ).astype(int)
    else:
        latest["is_transfer"] = 0

    return latest[["player_id", "name", "position"] + FEATURE_COLUMNS]
