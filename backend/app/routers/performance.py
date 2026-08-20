"""GET /api/performance -- per-player actual-vs-expected comparison (over-/
under-performance) for goals/xG, assists/xA and combined GI/xGI, plus ICT
components, defensive contribution, bonus and BPS. Backs the "Player
Performance" tab -- see docs/model-architecture.md's "never a black box"
principle: every delta/rank here is derived straight from FPL's own raw
per-gameweek stats, nothing modeled.

Same in-process cache pattern as players.py (independent of any gw window --
last season is fixed history, current season is whatever's finished so far --
so it's computed once and invalidated only by a genuine data refresh; see
scheduler.py's _INVALIDATES_PERFORMANCE_CACHE).
"""
import threading

import numpy as np
import pandas as pd
from fastapi import APIRouter

from app.config import CURRENT_SEASON, DB_PATH
from app.services.db import query_df
from apply_live_status_override import load_live_status, STATUS_LABELS, set_piece_roles

router = APIRouter(prefix="/api/performance", tags=["performance"])

# Same "most recent COMPLETE season" constant as players.py -- duplicated
# rather than imported, matching that file's own established pattern of not
# sharing this one constant across routers.
LAST_COMPLETE_SEASON = "2025-26"

_cache_lock = threading.RLock()
_cache: dict = {}


def invalidate_performance_cache():
    """Call after a genuine data refresh (new finished-gameweek stats or a
    roster/ownership update) -- see scheduler.py."""
    with _cache_lock:
        _cache.clear()


def _cached(key, compute):
    with _cache_lock:
        if key not in _cache:
            _cache[key] = compute()
        return _cache[key]


AGG_COLS = [
    "minutes", "goals", "assists", "xg", "xa", "defensive_contribution",
    "bonus", "bps", "ict_index", "influence", "creativity", "threat",
    # saves/clean_sheet -- added to back the "Leaders" board's GK-specific
    # columns (Player Performance tab); harmless additions for outfield
    # players (always 0/absent there).
    "saves", "clean_sheet",
]

# Same real scoring thresholds as players.py's DEFCON_THRESHOLDS (duplicated
# rather than imported -- see LAST_COMPLETE_SEASON's comment above for this
# file's established no-cross-router-import pattern). GK is DEFCON-ineligible.
DEFCON_THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}


def _season_aggregates(season_id: str) -> pd.DataFrame:
    """One row per player: season totals for every stat in AGG_COLS, plus
    games/starts. A player with zero rows that season (didn't play / not in
    the league yet) simply isn't in the returned frame -- callers left-join
    against it and treat missing as zero/None as appropriate.
    """
    agg_cols_sql = ", ".join(f"SUM({c}) AS {c}" for c in AGG_COLS)
    df = query_df(
        f"""SELECT player_id, COUNT(*) AS games, SUM(starts) AS starts, {agg_cols_sql}
            FROM player_gameweek_stats WHERE season_id = ? GROUP BY player_id""",
        (season_id,),
    )
    return df


# A season only counts toward "sustained" performance if the player cleared
# this many minutes IN THAT SEASON (~10 full matches) -- below this, that
# season's own G-xG number is too small a sample to trust, so the whole
# season is excluded from the sum rather than down-weighted. Simple in/out
# gate, not a continuous shrinkage -- easier to explain ("which seasons
# counted") than a weighted blend.
SUSTAINED_MIN_MINUTES_PER_SEASON = 900

# Need at least this many QUALIFYING seasons before showing a "sustained"
# number at all -- a single good/bad season is exactly the noise this view
# exists to filter out (single-season G-xG is known to correlate weakly
# year-to-year for most players; see the chat discussion this feature came
# out of). Below this, sustained is None for that player, not a misleadingly
# confident number from one data point.
SUSTAINED_MIN_SEASONS = 2


def _seasons_with_xg() -> list[str]:
    """Which seasons actually have xG/xA data at all (2021-22 predates FPL
    exposing it -- see schema.sql) -- queried dynamically rather than
    hardcoded so a newly-started current season is picked up automatically
    once it has real rows, with no code change needed each year.
    """
    df = query_df("SELECT DISTINCT season_id FROM player_gameweek_stats WHERE xg IS NOT NULL ORDER BY season_id")
    return df["season_id"].tolist()


def _sustained_aggregates(position_by_player: dict) -> tuple[pd.DataFrame, list[str], dict[int, list[str]]]:
    """Per player: totals SUMMED across only their qualifying seasons (see
    SUSTAINED_MIN_MINUTES_PER_SEASON), for anyone with at least
    SUSTAINED_MIN_SEASONS such seasons. Summing raw totals (not averaging
    per-90 rates across seasons) means a season with more minutes naturally
    counts for more in the combined per-90 rate computed afterward --
    weighted by playing time, not by season count.

    Also returns the final qualifying_seasons_by_player map (only players
    who cleared SUSTAINED_MIN_SEASONS) -- the "Leaders" board's sustained
    DEFCON hit-rate needs the exact same per-player season set the rest of
    this row was built from, not a re-derived approximation.
    """
    seasons = _seasons_with_xg()
    combined: dict[int, dict] = {}
    qualifying_seasons_by_player: dict[int, list[str]] = {}

    for season_id in seasons:
        season_df = _season_aggregates(season_id)
        if season_df.empty:
            continue
        qualifying = season_df[season_df["minutes"].fillna(0) >= SUSTAINED_MIN_MINUTES_PER_SEASON]
        for row in qualifying.to_dict(orient="records"):
            pid = int(row["player_id"])
            qualifying_seasons_by_player.setdefault(pid, []).append(season_id)
            acc = combined.setdefault(pid, {"player_id": pid, "games": 0, "starts": 0.0, **{c: 0.0 for c in AGG_COLS}})
            acc["games"] += row["games"]
            acc["starts"] += row["starts"] if pd.notna(row["starts"]) else 0
            for c in AGG_COLS:
                v = row[c]
                acc[c] += v if pd.notna(v) else 0

    rows = []
    final_qualifying: dict[int, list[str]] = {}
    for pid, acc in combined.items():
        qualifying = sorted(qualifying_seasons_by_player[pid])
        if len(qualifying) < SUSTAINED_MIN_SEASONS:
            continue
        acc["qualifying_seasons"] = len(qualifying)
        acc["seasons_included"] = qualifying
        rows.append(acc)
        final_qualifying[pid] = qualifying

    if not rows:
        return pd.DataFrame(), seasons, final_qualifying

    df = pd.DataFrame(rows)
    df = _add_ranks(_add_derived(df), position_by_player)
    return df, seasons, final_qualifying


def _per_start_raw() -> pd.DataFrame:
    """One row per player per FIXTURE (not gameweek -- a double gameweek is
    two separate rows here, matching player_gameweek_stats' own
    (player_id, fixture_id) primary key) across every season, just the
    columns needed for started-game rate maths: season_id, starts,
    defensive_contribution, goals, assists. Cached globally (independent of
    any gw window) and reused by all three season views below rather than
    re-querying per view.
    """
    def compute():
        return query_df(
            "SELECT player_id, season_id, starts, defensive_contribution, goals, assists "
            "FROM player_gameweek_stats"
        )
    return _cached("per_start_raw", compute)


def _per_start_stats(df: pd.DataFrame, position_by_player: dict) -> dict[int, dict]:
    """Per player, among only the rows in df (already restricted to a
    season, or to a set of qualifying seasons for "sustained", by the
    caller) -- three parallel "hit rate + per start" pairs, all computed
    over STARTED games only (not all appearances -- a cameo sub can't
    meaningfully hit a per-90-scaled threshold or a full-game scoring rate):
    - defcon_hit_rate / defcon_per_start: fraction of starts meeting this
      player's position threshold, and the average raw defensive-
      contribution action count. None for GK (DEFCON-ineligible).
    - goals_hit_rate / goals_per_start: fraction of starts with >=1 goal,
      and average goals per start. Computed for every position (GK scoring
      is vanishingly rare but not gated out).
    - assists_hit_rate / assists_per_start: same shape, for assists.
    - gi_hit_rate / gi_per_start: "offensive return" -- fraction of starts
      with >=1 goal OR assist (the union, not goal_hit_rate + assist_hit_rate,
      which would double-count a game with both), and average goals+assists
      per start. Backs MID/FWD's combined attacking-return column.
    - defcon_starts: the started-game sample size all of the above are
      based on, so the UI can show/require a minimum sample.
    """
    if df.empty:
        return {}
    df = df[df["starts"].fillna(0) >= 1].copy()
    if df.empty:
        return {}
    df["position"] = df["player_id"].map(position_by_player)
    df["threshold"] = df["position"].map(DEFCON_THRESHOLDS)
    df["defcon_hit"] = df["defensive_contribution"].fillna(0) >= df["threshold"]
    df["goal_hit"] = df["goals"].fillna(0) >= 1
    df["assist_hit"] = df["assists"].fillna(0) >= 1
    df["gi_hit"] = df["goal_hit"] | df["assist_hit"]
    df["gi"] = df["goals"].fillna(0) + df["assists"].fillna(0)

    out: dict[int, dict] = {}
    for pid, g in df.groupby("player_id"):
        threshold = g["threshold"].iloc[0]
        entry = {
            "defcon_starts": int(len(g)),
            "goals_hit_rate": round(float(g["goal_hit"].mean()), 3),
            "goals_per_start": round(float(g["goals"].fillna(0).mean()), 2),
            "assists_hit_rate": round(float(g["assist_hit"].mean()), 3),
            "assists_per_start": round(float(g["assists"].fillna(0).mean()), 2),
            "gi_hit_rate": round(float(g["gi_hit"].mean()), 3),
            "gi_per_start": round(float(g["gi"].mean()), 2),
        }
        if pd.isna(threshold):  # GK -- DEFCON-ineligible
            entry["defcon_hit_rate"] = None
            entry["defcon_per_start"] = None
        else:
            entry["defcon_hit_rate"] = round(float(g["defcon_hit"].mean()), 3)
            entry["defcon_per_start"] = round(float(g["defensive_contribution"].fillna(0).mean()), 2)
        out[int(pid)] = entry
    return out


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Adds per-90 rates, expected-goal-involvement (xGI = xG + xA, FPL
    doesn't store this as its own column), actual GI, and over-/under-
    performance deltas (actual minus expected) -- both season-total and
    per-90 flavors. Per-90 is the fairer basis for ranking (a nailed-on
    starter and a squad player who both beat their xG by the same TOTAL
    margin didn't really over-perform by the same amount), so ranks below
    are computed on the per-90 columns; totals are kept alongside for
    context.
    """
    df = df.copy()
    nineties = (df["minutes"] / 90).replace(0, np.nan)  # np.nan (not pd.NA)
    # avoids the object-dtype trap this project has hit before -- see
    # data.py's add_shrunk_rates convention in the build spec.

    df["gi"] = df["goals"] + df["assists"]
    df["xgi"] = df["xg"] + df["xa"]
    df["goals_minus_xg"] = df["goals"] - df["xg"]
    df["assists_minus_xa"] = df["assists"] - df["xa"]
    df["gi_minus_xgi"] = df["gi"] - df["xgi"]

    for col in ["goals", "assists", "xg", "xa", "gi", "xgi",
                "goals_minus_xg", "assists_minus_xa", "gi_minus_xgi",
                "defensive_contribution", "bonus", "bps",
                "ict_index", "influence", "creativity", "threat",
                "saves", "clean_sheet"]:
        df[f"{col}_per90"] = (df[col] / nineties).round(3)

    return df


def _add_ranks(df: pd.DataFrame, position_by_player: dict) -> pd.DataFrame:
    """Overall + position rank (1 = best/highest) for the stats that are
    meaningful to rank -- the three per-90 over-/under-performance deltas
    and the four per-90 ICT components. Only ranked among players who
    actually have minutes that season (a 0-minute player ranking "1st" by a
    NaN comparison would be meaningless) -- others get rank None, not a
    misleading number.
    """
    df = df.copy()
    df["position"] = df["player_id"].map(position_by_player)
    ranked_pool = df["minutes"].fillna(0) > 0

    rank_cols = [
        "goals_minus_xg_per90", "assists_minus_xa_per90", "gi_minus_xgi_per90",
        "ict_index_per90", "influence_per90", "creativity_per90", "threat_per90",
    ]
    for col in rank_cols:
        overall_col, pos_col = f"{col}_rank_overall", f"{col}_rank_position"
        df[overall_col] = None
        df[pos_col] = None
        pool = df[ranked_pool]
        df.loc[ranked_pool, overall_col] = pool[col].rank(ascending=False, method="min")
        df.loc[ranked_pool, pos_col] = pool.groupby("position")[col].rank(ascending=False, method="min")
        df[overall_col] = df[overall_col].astype("Int64")
        df[pos_col] = df[pos_col].astype("Int64")
    return df


def _json_safe(v):
    """Normalizes a single pandas/numpy scalar to a plain JSON-serializable
    Python value -- pd.NA (from the nullable Int64 rank columns) and NaN
    both become None; numpy int/float become native int/float (numpy.int64
    isn't a subclass of Python int, so FastAPI's encoder can choke on it
    otherwise, unlike numpy.float64 which IS a float subclass). Lists/strs
    (e.g. sustained's seasons_included) pass through untouched -- pd.isna()
    on a list returns an elementwise array, not a single bool, so it must be
    special-cased BEFORE the isna check below, not after."""
    if isinstance(v, (list, str)):
        return v
    if pd.isna(v):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, float):
        return round(v, 3)
    return v


def _round_floats(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: _json_safe(v) for k, v in row.items()}


def _strip(row) -> dict | None:
    """Drops the join keys (player_id/position, already at the top level of
    the player entry) from a per-season stats row; None if the player has no
    rows that season at all (new signing, hasn't played this season yet)."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in ("player_id", "position")}


def _status_by_player() -> dict[int, dict]:
    """Current live availability per player -- same shape/source as
    players.py's own _status_by_player (duplicated rather than imported,
    matching this file's established pattern of not sharing helpers across
    routers -- see LAST_COMPLETE_SEASON's comment above)."""
    def compute():
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        try:
            live = load_live_status(conn)
        finally:
            conn.close()
        out: dict[int, dict] = {}
        for row in live.to_dict(orient="records"):
            pid = row["player_id"]
            if pid is None:
                continue
            status = row["status"] or "a"
            chance = row["chance_of_playing_next_round"]
            news = row["news"]
            out[int(pid)] = {
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "chance_of_playing_next_round": chance if pd.notna(chance) else None,
                "news": news if pd.notna(news) else None,
                "set_piece_roles": set_piece_roles(row),
            }
        return out
    return _cached("status_by_player", compute)


def _compute() -> dict:
    position_by_player = query_df("SELECT player_id, position FROM players").set_index("player_id")["position"].to_dict()

    last = _add_ranks(_add_derived(_season_aggregates(LAST_COMPLETE_SEASON)), position_by_player)
    current = _add_ranks(_add_derived(_season_aggregates(CURRENT_SEASON)), position_by_player)
    sustained_df, seasons_with_xg, sustained_qualifying = _sustained_aggregates(position_by_player)

    def _dict_to_df(d: dict[int, dict]) -> pd.DataFrame:
        """{player_id: {stat: value, ...}} -> a plain DataFrame with
        player_id as a normal int column, ready to merge -- avoids the
        dict-of-dicts .T transpose's dtype/index headaches."""
        if not d:
            return pd.DataFrame()
        return pd.DataFrame([{"player_id": pid, **stats} for pid, stats in d.items()])

    # Started-game hit-rate/per-start stats (DEFCON, goals, assists) --
    # computed from raw per-fixture rows (season aggregates only carry
    # SUMS, which can't answer "in what fraction of his STARTS did he
    # score"). Merged onto each season's frame below via player_id so it
    # flows through the existing _strip/_round_floats pipeline for free,
    # same as every other column.
    per_start_raw = _per_start_raw()
    defcon_last = _dict_to_df(_per_start_stats(per_start_raw[per_start_raw["season_id"] == LAST_COMPLETE_SEASON], position_by_player))
    defcon_current = _dict_to_df(_per_start_stats(per_start_raw[per_start_raw["season_id"] == CURRENT_SEASON], position_by_player))
    sustained_pairs = pd.DataFrame(
        [(pid, s) for pid, seasons in sustained_qualifying.items() for s in seasons],
        columns=["player_id", "season_id"],
    )
    defcon_sustained_subset = per_start_raw.merge(sustained_pairs, on=["player_id", "season_id"]) if not sustained_pairs.empty else per_start_raw.iloc[0:0]
    defcon_sustained = _dict_to_df(_per_start_stats(defcon_sustained_subset, position_by_player))

    def _merge_defcon(df: pd.DataFrame, defcon_df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or defcon_df.empty:
            return df
        return df.merge(defcon_df, on="player_id", how="left")

    last = _merge_defcon(last, defcon_last)
    current = _merge_defcon(current, defcon_current)
    if not sustained_df.empty:
        sustained_df = _merge_defcon(sustained_df, defcon_sustained)

    meta = query_df(
        """SELECT p.player_id, p.name, p.position, t.name AS team, t.code AS team_code,
                  ps.price_end AS price, ps.ownership_pct
           FROM players p
           JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
           JOIN teams t ON t.team_id = ps.team_id AND t.season_id = ?""",
        (CURRENT_SEASON, CURRENT_SEASON),
    )

    last_by_player = {int(r["player_id"]): r for r in last.to_dict(orient="records")}
    current_by_player = {int(r["player_id"]): r for r in current.to_dict(orient="records")}
    sustained_by_player = (
        {int(r["player_id"]): r for r in sustained_df.to_dict(orient="records")}
        if not sustained_df.empty else {}
    )

    status_by_player = _status_by_player()

    players = []
    for row in meta.to_dict(orient="records"):
        pid = int(row["player_id"])
        entry = {
            "player_id": pid,
            "name": row["name"],
            "position": row["position"],
            "team": row["team"],
            "team_code": int(row["team_code"]) if pd.notna(row["team_code"]) else None,
            "price": row["price"],
            "ownership_pct": round(row["ownership_pct"], 1) if pd.notna(row["ownership_pct"]) else None,
            "last_season": _round_floats(_strip(last_by_player.get(pid))),
            "current_season": _round_floats(_strip(current_by_player.get(pid))),
            "sustained": _round_floats(_strip(sustained_by_player.get(pid))),
        }
        entry.update(status_by_player.get(pid, {
            "status": "a", "status_label": STATUS_LABELS["a"],
            "chance_of_playing_next_round": None, "news": None, "set_piece_roles": [],
        }))
        players.append(entry)

    return {
        "last_season_id": LAST_COMPLETE_SEASON,
        "current_season_id": CURRENT_SEASON,
        "sustained_seasons_available": seasons_with_xg,
        "sustained_min_minutes_per_season": SUSTAINED_MIN_MINUTES_PER_SEASON,
        "sustained_min_seasons": SUSTAINED_MIN_SEASONS,
        "players": players,
    }


def warm_performance_cache():
    _cached("performance", _compute)


@router.get("")
def get_performance():
    return _cached("performance", _compute)
