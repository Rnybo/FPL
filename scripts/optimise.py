"""
Layer 6 -- optimizer (see docs/build-spec-inspiration.md for the design origin).

Two genuinely different sub-problems, deliberately solved with different tools:

1. best_lineup() -- pick the best XI + captain/vice from an EXISTING 15-man
   squad. Players are interchangeable within a position for this decision, so
   enumerating formations + greedily taking top-xP per slot is EXACT, not an
   approximation (confirmed against BUILD_SPEC.md's own reasoning). No solver
   needed.

2. build_initial_squad() -- pick 15 players FROM SCRATCH under a budget that's
   shared ACROSS positions plus a max-3-per-club constraint. This is a genuine
   knapsack/ILP problem -- greedy-by-value can be provably suboptimal here
   (a slightly worse GK might free up exactly enough budget for a much better
   forward), unlike lineup selection. Uses PuLP (free, open-source) for this
   one piece specifically -- not because MILP is the right tool everywhere,
   but because this particular sub-problem actually needs it.

suggest_transfers() sits in between: greedy (best single upgrade per outgoing
player) is a reasonable heuristic, not claimed to be exact for multi-transfer
combinations -- matches BUILD_SPEC.md's own scope (single best-per-player,
not a full re-optimization).
"""
import sqlite3
from pathlib import Path

import pandas as pd
import pulp

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fpl_cache.db"

SQUAD_LIMITS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
FORMATION_LIMITS = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
STARTING_XI = 11
BUDGET = 100.0
MAX_PER_CLUB = 3
BENCH_WEIGHT = 0.15  # see build_optimal_squad_and_lineup's docstring -- a documented
                      # simplification, not learned from data


def valid_formations():
    """Every legal (GK, DEF, MID, FWD) split summing to 11, per FORMATION_LIMITS.
    GK is always exactly 1 in FPL, so no need to loop over it."""
    formations = []
    for d in range(FORMATION_LIMITS["DEF"][0], FORMATION_LIMITS["DEF"][1] + 1):
        for m in range(FORMATION_LIMITS["MID"][0], FORMATION_LIMITS["MID"][1] + 1):
            for f in range(FORMATION_LIMITS["FWD"][0], FORMATION_LIMITS["FWD"][1] + 1):
                if 1 + d + m + f == STARTING_XI:
                    formations.append({"GK": 1, "DEF": d, "MID": m, "FWD": f})
    return formations


def _lineup_for_formation(squad: pd.DataFrame, formation: dict, score_col: str) -> dict | None:
    """Exact greedy XI for ONE fixed formation (players are interchangeable
    within a position for this decision -- see module docstring). Returns
    None if the squad doesn't have enough players in some position to fill
    it -- in practice this can't happen for a real 15-man squad respecting
    SQUAD_LIMITS (5 DEF/5 MID/3 FWD/2 GK always covers every valid formation's
    max), but callers may pass an arbitrary/malformed squad, so it's checked
    rather than assumed."""
    starters = []
    for pos, n in formation.items():
        pos_players = squad[squad["position"] == pos].nlargest(n, score_col)
        if len(pos_players) < n:
            return None
        starters.append(pos_players)
    starters_df = pd.concat(starters)
    total = starters_df[score_col].sum()
    bench_df = squad[~squad.index.isin(starters_df.index)]
    ranked = starters_df.sort_values(score_col, ascending=False)
    captain = ranked.iloc[0]
    vice = ranked.iloc[1]
    bench_sorted = pd.concat([
        bench_df[bench_df["position"] != "GK"].sort_values(score_col, ascending=False),
        bench_df[bench_df["position"] == "GK"],
    ])
    return dict(
        formation=formation, starters=starters_df, bench=bench_sorted,
        captain=captain["name"], vice_captain=vice["name"],
        expected_points=total,
        expected_points_with_captain=total + captain[score_col],
    )


def best_lineup(squad: pd.DataFrame, score_col: str = "xP", formation: dict | None = None) -> dict | None:
    """squad: one row per player (15 rows), columns include position, name,
    team, score_col. Returns starters, bench, formation, captain, vice.

    formation: if given (e.g. {"GK":1,"DEF":4,"MID":3,"FWD":3}), forces that
    EXACT formation instead of searching every valid one -- still the exact
    (not approximate) best XI for that one formation, just skips the "which
    formation scores most" search across all of them. Lets the frontend offer
    a formation picker without duplicating this greedy logic in JS -- one
    authoritative implementation, same as every other "transparency" number
    in this project (see BUILD_SPEC.md's conventions). Returns None if the
    formation itself is invalid (wrong total, outside FORMATION_LIMITS) or
    infeasible for this specific squad."""
    if formation is not None:
        if sum(formation.values()) != STARTING_XI:
            return None
        for pos, (lo, hi) in FORMATION_LIMITS.items():
            if not (lo <= formation.get(pos, 0) <= hi):
                return None
        return _lineup_for_formation(squad, formation, score_col)

    best = None
    for f in valid_formations():
        candidate = _lineup_for_formation(squad, f, score_col)
        if candidate is None:
            continue
        if best is None or candidate["expected_points"] > best["expected_points"]:
            best = candidate
    return best


def build_optimal_squad_and_lineup(pool: pd.DataFrame, score_col: str = "xP",
                                    budget: float = BUDGET, max_per_club: int = MAX_PER_CLUB,
                                    bench_weight: float = BENCH_WEIGHT,
                                    locked_player_ids: list | None = None) -> dict:
    """Jointly decides SQUAD membership (x) and STARTING XI membership (y) in
    one ILP, instead of the old two-stage build_initial_squad -> best_lineup
    pipeline. That two-stage approach had a real objective-function bug (found
    via user feedback, see docs/GOTCHAS.md): it maximized the sum of ALL 15
    players' xP equally, when only 11 of them actually score points. That
    encourages overspending on a merely-decent bench filler instead of saving
    that money for a genuinely strong starter -- the squad-selection stage
    had no way to know who'd even start.

    Objective: maximize sum(y_i * xP_i) + bench_weight * sum((x_i - y_i) * xP_i)
    -- starters count in full, bench players count at a small fraction
    (bench_weight), reflecting that they mostly don't score but aren't
    worthless either (auto-sub cover, future-gameweek options). bench_weight
    is a documented simplification, not learned from data -- a fully accurate
    version would weight each bench player by their own specific P(the
    starter ahead of them blanks), which would need the substitution mapping
    to be part of the ILP too. Flagged as a real simplification, not hidden.

    locked_player_ids: players that MUST be in the squad (x_i == 1) -- e.g.
    "build from what's already selected" passes the current squad's ids here.
    Their STARTING status (y_i) is NOT locked -- the optimizer can freely
    reshuffle who starts among a fixed squad, only membership is pinned.
    """
    prob = pulp.LpProblem("fpl_squad_and_lineup", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in pool.index}
    y = {i: pulp.LpVariable(f"y_{i}", cat="Binary") for i in pool.index}

    prob += pulp.lpSum(
        y[i] * pool.loc[i, score_col] + bench_weight * (x[i] - y[i]) * pool.loc[i, score_col]
        for i in pool.index
    )

    for pos, n in SQUAD_LIMITS.items():
        prob += pulp.lpSum(x[i] for i in pool.index if pool.loc[i, "position"] == pos) == n

    prob += pulp.lpSum(x[i] * pool.loc[i, "price"] for i in pool.index) <= budget

    for club in pool["team"].unique():
        prob += pulp.lpSum(x[i] for i in pool.index if pool.loc[i, "team"] == club) <= max_per_club

    for i in pool.index:
        prob += y[i] <= x[i]  # can't start someone who isn't even in the squad

    prob += pulp.lpSum(y[i] for i in pool.index) == STARTING_XI
    for pos, (lo, hi) in FORMATION_LIMITS.items():
        starters_in_pos = pulp.lpSum(y[i] for i in pool.index if pool.loc[i, "position"] == pos)
        prob += starters_in_pos >= lo
        prob += starters_in_pos <= hi

    missing_ids = []
    for pid in (locked_player_ids or []):
        matching_idx = pool.index[pool["player_id"] == pid]
        if len(matching_idx) == 0:
            missing_ids.append(pid)
            continue
        for i in matching_idx:
            prob += x[i] == 1
    if missing_ids:
        return dict(status="PlayerNotFound", squad=None, missing_player_ids=missing_ids)

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if pulp.LpStatus[prob.status] != "Optimal":
        return dict(status=pulp.LpStatus[prob.status], squad=None)

    squad_idx = [i for i in pool.index if x[i].value() == 1]
    starter_idx = [i for i in pool.index if y[i].value() == 1]
    squad = pool.loc[squad_idx]
    starters_df = pool.loc[starter_idx]
    bench_df = squad[~squad.index.isin(starter_idx)]
    bench_sorted = pd.concat([
        bench_df[bench_df["position"] != "GK"].sort_values(score_col, ascending=False),
        bench_df[bench_df["position"] == "GK"],
    ])
    ranked_starters = starters_df.sort_values(score_col, ascending=False)
    captain, vice = ranked_starters.iloc[0], ranked_starters.iloc[1]
    formation = {pos: int((starters_df["position"] == pos).sum()) for pos in SQUAD_LIMITS}

    lineup = dict(
        formation=formation, starters=starters_df, bench=bench_sorted,
        captain=captain["name"], vice_captain=vice["name"],
        expected_points=float(starters_df[score_col].sum()),
        expected_points_with_captain=float(starters_df[score_col].sum() + captain[score_col]),
    )
    return dict(status="Optimal", squad=squad, lineup=lineup,
                total_score=float(squad[score_col].sum()), total_cost=float(squad["price"].sum()))


def build_initial_squad(pool: pd.DataFrame, score_col: str = "xP",
                         budget: float = BUDGET, max_per_club: int = MAX_PER_CLUB,
                         locked_player_ids: list | None = None) -> dict:
    """Pick 15 players from scratch maximizing total score_col, subject to:
    SQUAD_LIMITS per position, budget, and max_per_club. Genuine ILP -- see
    module docstring for why greedy isn't provably optimal here.

    locked_player_ids: players that MUST be in the squad (e.g. "I want
    Haaland regardless"). Implemented as x_i == 1 for those rows -- every
    other constraint (budget, position quota, club limit) still applies to
    the REMAINING slots automatically, since those constraints sum over all
    players including the locked ones. If a lock makes the problem
    infeasible (e.g. 3 locked players from the same club), PuLP reports that
    rather than silently ignoring the lock."""
    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in pool.index}

    prob += pulp.lpSum(x[i] * pool.loc[i, score_col] for i in pool.index)

    for pos, n in SQUAD_LIMITS.items():
        prob += pulp.lpSum(x[i] for i in pool.index if pool.loc[i, "position"] == pos) == n

    prob += pulp.lpSum(x[i] * pool.loc[i, "price"] for i in pool.index) <= budget

    for club in pool["team"].unique():
        prob += pulp.lpSum(x[i] for i in pool.index if pool.loc[i, "team"] == club) <= max_per_club

    missing_ids = []
    for pid in (locked_player_ids or []):
        matching_idx = pool.index[pool["player_id"] == pid]
        if len(matching_idx) == 0:
            missing_ids.append(pid)
            continue
        for i in matching_idx:
            prob += x[i] == 1
    if missing_ids:
        return dict(status="PlayerNotFound", squad=None, missing_player_ids=missing_ids)

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if pulp.LpStatus[prob.status] != "Optimal":
        return dict(status=pulp.LpStatus[prob.status], squad=None)

    chosen = pool.loc[[i for i in pool.index if x[i].value() == 1]]
    return dict(
        status="Optimal", squad=chosen,
        total_score=chosen[score_col].sum(), total_cost=chosen["price"].sum(),
    )


def suggest_transfers(squad: pd.DataFrame, candidates: pd.DataFrame, bank: float,
                       score_col: str = "xP", min_gain: float = 0.5,
                       max_per_club: int = MAX_PER_CLUB, max_suggestions: int = 5) -> pd.DataFrame:
    """Best single-player upgrade per outgoing squad member (greedy, per
    BUILD_SPEC.md's own scope -- not a full joint re-optimization)."""
    club_counts = squad["team"].value_counts().to_dict()
    suggestions = []
    for _, out_player in squad.iterrows():
        affordable_budget = bank + out_player["price"]
        pos_candidates = candidates[
            (candidates["position"] == out_player["position"])
            & (candidates["price"] <= affordable_budget)
            & (~candidates["player_id"].isin(squad["player_id"]))
        ]
        for _, in_player in pos_candidates.iterrows():
            club_count_after = club_counts.get(in_player["team"], 0) - \
                (1 if in_player["team"] == out_player["team"] else 0)
            if club_count_after >= max_per_club:
                continue
            gain = in_player[score_col] - out_player[score_col]
            if gain >= min_gain:
                suggestions.append(dict(
                    out_name=out_player["name"], in_name=in_player["name"],
                    # ids alongside names -- matching back to a squad/candidate row by
                    # name alone is exactly the bug pattern this project already hit
                    # once (accent-encoding duplicate-name splits, see docs/GOTCHAS.md).
                    # Additive columns only -- existing callers reading out_name/in_name
                    # are unaffected.
                    out_player_id=out_player["player_id"], in_player_id=in_player["player_id"],
                    position=out_player["position"], gain=gain,
                    cost_change=in_player["price"] - out_player["price"],
                ))
    return pd.DataFrame(suggestions).sort_values("gain", ascending=False).head(max_suggestions) \
        if suggestions else pd.DataFrame(
            columns=["out_name", "in_name", "out_player_id", "in_player_id", "position", "gain", "cost_change"]
        )


# Current FPL rule (2024/25+): +1 free transfer per gameweek, banked unused
# up to this cap. Matches user's confirmed choice for plan_horizon below.
MAX_BANKED_FREE_TRANSFERS = 5
# Same convention/values as squad.py's LOOKAHEAD_WEEKS/LOOKAHEAD_WEIGHT --
# duplicated here rather than imported cross-router/module (see this
# project's own "small duplication over shared helpers" pattern).
PLAN_LOOKAHEAD_WEEKS = 3
PLAN_LOOKAHEAD_WEIGHT = 0.3


def plan_horizon(squad: pd.DataFrame, candidates: pd.DataFrame, per_gw_xp: pd.DataFrame,
                  gameweeks: list[int], bank: float, free_transfers: int = 1,
                  lookahead_weeks: int = PLAN_LOOKAHEAD_WEEKS, lookahead_weight: float = PLAN_LOOKAHEAD_WEIGHT,
                  min_gain: float = 2.0, max_per_club: int = MAX_PER_CLUB,
                  max_banked_transfers: int = MAX_BANKED_FREE_TRANSFERS,
                  allow_hits: bool = False, hit_cost: float = 4.0, max_hits_per_gw: int = 2,
                  min_hold_weeks: int = 2) -> list[dict]:
    """A round-by-round game plan across a multi-gameweek horizon: for each
    gameweek, decide transfers (if worth it) and pick that week's best
    lineup/captain from whatever squad exists AFTER those transfers. GREEDY,
    round-by-round -- NOT a joint multi-period optimization (matches this
    module's own existing honesty standard: suggest_transfers is greedy too,
    not claimed exact for multi-transfer combinations).

    Free transfers are always used first. If allow_hits, additional
    transfers beyond the free ones are taken as real -hit_cost point hits
    (matches the actual FPL rule: -4 per transfer beyond your free ones),
    but only when the lookahead-scored gain clears min_gain + hit_cost --
    i.e. the hit has to pay for itself, not just the transfer. Hits are
    capped at max_hits_per_gw per round so the planner can't recommend
    "take 5 hits this week" chasing marginal lookahead noise.

    squad: current 15-man squad -- static columns (player_id, name, position,
        team, price) plus optionally selling_price (real transfer economics,
        see team.py's own reasoning -- defaults to price if absent).
    candidates: every other player, same static columns, CURRENT price (what
        buying them would cost).
    per_gw_xp: long frame (player_id, gw, xP) covering every player in squad
        + candidates, for every gw in `gameweeks` PLUS up to lookahead_weeks
        past the final one (needed to score the last round's transfers
        fairly -- without a tail, the last gameweek would look like nothing
        is ever worth buying for the future because there IS no future left
        in the data).
    gameweeks: sorted list of gameweek numbers to plan, e.g. [4, 5, 6, 7, 8].
    bank, free_transfers: starting state.
    min_hold_weeks: a player bought DURING this plan can't be sold again for
        at least this many gameweeks (including the one they were bought
        for). Without this, the greedy per-round re-scoring can thrash --
        buy a player one week, sell them the next because that week's
        lookahead window shifted and briefly favours someone else, then buy
        them back again a couple of rounds later. No real manager would
        spend transfers reversing their own decision like that, and it's
        pure noise from the lookahead window sliding, not a genuine
        long-term upgrade -- a real, documented judgment call, same honesty
        standard as LOOKAHEAD_WEEKS/WEIGHT elsewhere in this pipeline.
        Players already in the squad at the START of the plan are never
        restricted -- only players THIS function buys.

    Returns a list of one dict per gameweek (in order):
        gameweek, formation, starters, bench, captain, vice_captain,
        transfers_in, transfers_out (player_id lists), transfers_in_names,
        transfers_out_names, hits_taken, free_transfers_after, bank_after,
        expected_points, expected_points_with_captain (BEFORE any hit
        deduction -- the raw lineup score), expected_points_after_hits,
        expected_points_with_captain_after_hits (what you'd actually bank
        that gameweek once -hit_cost per hit is subtracted). The last
        `hits_taken` entries of transfers_in/transfers_out are the paid
        ones -- everything before that was free.
    """
    squad = squad.copy()
    if "selling_price" not in squad.columns:
        squad["selling_price"] = squad["price"]
    candidates = candidates[~candidates["player_id"].isin(squad["player_id"])].copy()
    held_since: dict[int, int] = {}  # player_id -> gw bought, ONLY for players this plan itself bought

    plan = []
    for gw in gameweeks:
        gw_xp = per_gw_xp.loc[per_gw_xp["gw"] == gw].set_index("player_id")["xP"]
        lookahead_xp = per_gw_xp.loc[
            (per_gw_xp["gw"] > gw) & (per_gw_xp["gw"] <= gw + lookahead_weeks)
        ].groupby("player_id")["xP"].sum()

        def _scored(df):
            df = df.copy()
            df["xP"] = df["player_id"].map(gw_xp).fillna(0.0)
            df["selection_score"] = df["xP"] + lookahead_weight * df["player_id"].map(lookahead_xp).fillna(0.0)
            return df

        working_squad = _scored(squad)
        candidate_pool = _scored(candidates)

        transfers_in_ids, transfers_out_ids = [], []
        transfers_in_names, transfers_out_names = [], []
        free_remaining = free_transfers
        hits_taken = 0
        # One transfer at a time (max_suggestions=1), applied and re-scored
        # before considering the next -- suggest_transfers alone doesn't
        # account for two simultaneous suggestions spending the same bank
        # or breaching max_per_club together, so this loop is what actually
        # enforces that across multiple transfers in the same gameweek.
        while True:
            if free_remaining > 0:
                threshold = min_gain
            elif allow_hits and hits_taken < max_hits_per_gw:
                threshold = min_gain + hit_cost  # the hit has to pay for itself
            else:
                break

            squad_for_transfers = working_squad.drop(columns=["price"]).rename(columns={"selling_price": "price"})
            # Ask for every possible upgrade (one per outgoing squad member,
            # at most len(squad)), not just the single best -- the single
            # best might be a currently-protected (too-recently-bought)
            # player, and we need the next-best real option instead of
            # giving up entirely.
            suggestions = suggest_transfers(
                squad_for_transfers, candidate_pool, bank,
                score_col="selection_score", min_gain=threshold,
                max_per_club=max_per_club, max_suggestions=len(squad_for_transfers),
            )
            protected_ids = {pid for pid, since_gw in held_since.items() if gw - since_gw < min_hold_weeks}
            if protected_ids and not suggestions.empty:
                suggestions = suggestions[~suggestions["out_player_id"].isin(protected_ids)]
            if suggestions.empty:
                break
            row = suggestions.iloc[0]
            bank -= row["cost_change"]
            in_row = candidate_pool.loc[candidate_pool["player_id"] == row["in_player_id"]].iloc[0].to_dict()
            in_row["selling_price"] = in_row["price"]
            working_squad = pd.concat([
                working_squad.loc[working_squad["player_id"] != row["out_player_id"]],
                pd.DataFrame([in_row]),
            ], ignore_index=True)
            candidate_pool = candidate_pool.loc[candidate_pool["player_id"] != row["in_player_id"]]
            transfers_out_ids.append(int(row["out_player_id"]))
            transfers_in_ids.append(int(row["in_player_id"]))
            transfers_out_names.append(row["out_name"])
            transfers_in_names.append(row["in_name"])
            held_since.pop(int(row["out_player_id"]), None)
            held_since[int(row["in_player_id"])] = gw
            if free_remaining > 0:
                free_remaining -= 1
            else:
                hits_taken += 1

        lineup = best_lineup(working_squad, score_col="xP")
        free_transfers_after = min(max_banked_transfers, free_remaining + 1)
        hit_points = hits_taken * hit_cost

        plan.append(dict(
            gameweek=gw, formation=lineup["formation"],
            starters=lineup["starters"], bench=lineup["bench"],
            captain=lineup["captain"], vice_captain=lineup["vice_captain"],
            transfers_in=transfers_in_ids, transfers_out=transfers_out_ids,
            transfers_in_names=transfers_in_names, transfers_out_names=transfers_out_names,
            hits_taken=hits_taken,
            free_transfers_after=free_transfers_after, bank_after=bank,
            expected_points=lineup["expected_points"],
            expected_points_with_captain=lineup["expected_points_with_captain"],
            expected_points_after_hits=lineup["expected_points"] - hit_points,
            expected_points_with_captain_after_hits=lineup["expected_points_with_captain"] - hit_points,
        ))

        squad = working_squad.drop(columns=["xP", "selection_score"])
        free_transfers = free_transfers_after

    return plan


if __name__ == "__main__":
    import sys
    lock_names = sys.argv[1:]  # e.g. `python optimise.py "Erling Haaland"`

    conn = sqlite3.connect(DB)
    latest_run = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()[0]

    pool = pd.read_sql_query(
        """SELECT p.player_id, p.name, p.position, ps.team_id, t.name AS team,
                  ps.price_end AS price, mp.predicted_points AS xP
           FROM model_predictions mp
           JOIN players p ON mp.player_id = p.player_id
           JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = '2026-27'
           JOIN teams t ON t.team_id = ps.team_id AND t.season_id = '2026-27'
           WHERE mp.run_id = ?""",
        conn, params=(latest_run,),
    )
    # RULE FIX: double gameweeks mean a player can have >1 fixture row for the same
    # predicted gameweek -- FPL only lets you own one copy of them, and their points from
    # BOTH fixtures count toward that one copy. Without this aggregation, the ILP could
    # "buy" the same player twice via two separate prediction rows (see docs/GOTCHAS.md).
    n_before = len(pool)
    pool = pool.groupby(["player_id", "name", "position", "team_id", "team", "price"], as_index=False)["xP"].sum()
    if n_before != len(pool):
        print(f"Aggregated {n_before} prediction rows -> {len(pool)} players "
              f"(double-gameweek fixtures summed per player, not double-counted)")
    print(f"Loaded {len(pool)} candidate players with xP from run_id={latest_run}\n")

    locked_ids = []
    for name in lock_names:
        match = pool[pool["name"].str.lower() == name.lower()]
        if match.empty:
            print(f"WARNING: locked player '{name}' not found in pool -- ignoring")
        else:
            locked_ids.append(int(match.iloc[0]["player_id"]))
            print(f"Locking in: {match.iloc[0]['name']} ({match.iloc[0]['team']}, "
                  f"{match.iloc[0]['position']}, xP={match.iloc[0]['xP']:.2f})")

    print(f"\nBuilding initial 15-man squad (ILP, budget=100.0)...")
    result = build_initial_squad(pool, locked_player_ids=locked_ids)
    print(f"Status: {result['status']}")
    if result["status"] == "Infeasible":
        print("No valid squad satisfies the locked players + budget/position/club rules together --"
              " try locking fewer players or check they don't violate the 3-per-club limit.")
    if result["squad"] is not None:
        squad = result["squad"]
        print(f"Total cost: {squad['price'].sum():.1f}  Total xP: {squad['xP'].sum():.2f}\n")
        print(squad[["name", "team", "position", "price", "xP"]].sort_values(["position", "xP"], ascending=[True, False])
              .to_string(index=False, formatters={"xP": "{:.2f}".format, "price": "{:.1f}".format})
              .encode("ascii", "replace").decode())

        print("\nBest lineup from this squad:")
        lineup = best_lineup(squad)
        print(f"Formation: {lineup['formation']}")
        print(f"Captain: {lineup['captain']}  Vice: {lineup['vice_captain']}")
        print(f"XI expected points: {lineup['expected_points']:.2f}  "
              f"(with captain double: {lineup['expected_points_with_captain']:.2f})")
        print("\nStarting XI:")
        print(lineup["starters"][["name", "team", "position", "xP"]].sort_values("position")
              .to_string(index=False, formatters={"xP": "{:.2f}".format})
              .encode("ascii", "replace").decode())

    conn.close()
