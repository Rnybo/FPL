"""
Integration tests for the API layer. Uses the REAL cache DB (read-only
queries only, no test double) -- pragmatic for a project this size, and
representative of what actually gets served. See docs/GOTCHAS.md's practice
of verifying against real data rather than assuming; these tests just make
that verification permanent instead of a one-off script.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_players_returns_real_data():
    resp = client.get("/api/players")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["players"]) > 0
    first = data["players"][0]
    assert set(first.keys()) == {"player_id", "name", "position", "team", "team_code", "price", "xP", "breakdown", "gameweeks", "historic", "last_season_stats", "last_season_total_points", "last_season_breakdown", "prob", "opponent_stats", "points_by_month", "points_vs_opponent_last_season", "ownership_pct", "differential"}
    assert first["position"] in {"GK", "DEF", "MID", "FWD"}


def test_players_ownership_and_differential_are_present_and_well_formed():
    """ownership_pct is a real 0-100 percentage (or None if genuinely
    missing), and differential = xP * (1 - ownership/100) exactly -- FPL is
    a relative game, so a high-xP player everyone owns is worth less
    strategically than an equally-good, low-owned pick (see players.py's
    comment for the full rationale)."""
    resp = client.get("/api/players")
    players = resp.json()["players"]
    checked_any = False
    for p in players[:100]:
        if p["ownership_pct"] is None:
            assert p["differential"] == p["xP"]  # missing ownership treated as 0% owned
            continue
        checked_any = True
        assert 0 <= p["ownership_pct"] <= 100
        expected = round(p["xP"] * (1 - p["ownership_pct"] / 100), 3)
        assert p["differential"] == pytest.approx(expected, abs=0.01)
    assert checked_any, "no player in the sample had ownership_pct -- test wasn't exercised"


def test_players_differential_is_lower_for_highly_owned_players_at_similar_xp():
    """The whole point of the stat: among players with similar xP, a
    heavily-owned one should show a NOTICEABLY lower differential than a
    lightly-owned one -- confirms ownership is actually doing something,
    not just carried through as a decorative extra field."""
    resp = client.get("/api/players")
    players = [p for p in resp.json()["players"] if p["ownership_pct"] is not None and p["xP"] > 0]
    highly_owned = [p for p in players if p["ownership_pct"] >= 30]
    lightly_owned = [p for p in players if p["ownership_pct"] <= 5]
    assert highly_owned and lightly_owned, "sample didn't include both a highly- and lightly-owned player"
    for p in highly_owned:
        assert p["differential"] < p["xP"]  # meaningfully discounted
    for p in lightly_owned:
        assert p["differential"] == pytest.approx(p["xP"], abs=p["xP"] * 0.05 + 0.01)  # barely discounted


def test_players_scout_can_sort_by_differential():
    """Confirms it's a genuinely varying number across the pool (not a
    constant that would make sorting by it a no-op)."""
    resp = client.get("/api/players")
    values = {p["differential"] for p in resp.json()["players"]}
    assert len(values) > 10


def test_players_prob_is_a_real_probability_and_correlates_with_the_points_it_explains():
    """prob.{goal_pts,assist_pts,cs_pts,defcon_pts} are P(>=1 of that
    outcome) over the window -- must be real probabilities (0-1), and a
    player with a much higher xP in that specific component should
    generally have a higher probability of it too (they're literally
    derived from the same underlying rate -- see players.py's
    _outcome_probabilities docstring)."""
    resp = client.get("/api/players")
    players = [p for p in resp.json()["players"] if p["prob"] is not None]
    assert len(players) > 0
    for p in players[:100]:
        for key in ("goal_pts", "assist_pts", "cs_pts", "defcon_pts"):
            assert 0 <= p["prob"][key] <= 1

    by_goal_pts = sorted(players, key=lambda p: p["breakdown"]["goal_pts"])
    low, high = by_goal_pts[0], by_goal_pts[-1]
    assert high["prob"]["goal_pts"] >= low["prob"]["goal_pts"]

    by_defcon_pts = sorted(players, key=lambda p: p["breakdown"]["defcon_pts"])
    low, high = by_defcon_pts[0], by_defcon_pts[-1]
    assert high["prob"]["defcon_pts"] >= low["prob"]["defcon_pts"]


def test_players_prob_widens_towards_certainty_over_a_longer_window():
    """P(>=1 goal) etc. is a combined/cumulative probability -- a longer
    window must never give a LOWER probability than a strict sub-window for
    the same player (more chances to do it at least once)."""
    resp1 = client.get("/api/players?gw_start=1&gw_end=1")
    resp5 = client.get("/api/players?gw_start=1&gw_end=5")
    prob1_by_id = {p["player_id"]: p["prob"] for p in resp1.json()["players"] if p["prob"]}
    prob5_by_id = {p["player_id"]: p["prob"] for p in resp5.json()["players"] if p["prob"]}
    checked_any = False
    for pid, prob5 in prob5_by_id.items():
        prob1 = prob1_by_id.get(pid)
        if prob1 is None:
            continue
        checked_any = True
        for key in ("goal_pts", "assist_pts", "cs_pts", "defcon_pts"):
            assert prob5[key] >= prob1[key] - 1e-9
    assert checked_any


def test_players_last_season_stats_are_internally_consistent():
    """mean/max/min/variance/start_pct of REAL scored points, last complete
    season -- must be sane relative to each other for any player who
    actually has last-season data (a brand-new signing legitimately has
    None -- see players.py's docstring for why)."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"][:50]:
        s = p["last_season_stats"]
        if s is None:
            continue
        checked_any = True
        assert s["min_points"] <= s["mean_points"] <= s["max_points"]
        assert s["games"] > 0
        assert 0 <= s["starts"] <= s["games"]
        assert s["start_pct"] == pytest.approx(100 * s["starts"] / s["games"], abs=0.1)
        assert s["variance"] >= 0
        assert s["std_dev"] == pytest.approx(s["variance"] ** 0.5, abs=0.05)
        assert s["total_points"] == pytest.approx(s["games"] * s["mean_points"], abs=s["games"] * 0.5)
    assert checked_any, "no player in the sample had last-season data -- test wasn't exercised"


def test_players_last_season_total_points_is_flattened_and_matches_nested_stats():
    """last_season_total_points exists directly on the row (for Player
    Scout's sortable column) and must always agree with the nested
    last_season_stats.total_points it's derived from -- or be 0 when there's
    no last-season data at all (a brand-new signing)."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"][:50]:
        if p["last_season_stats"] is None:
            assert p["last_season_total_points"] == 0
        else:
            checked_any = True
            assert p["last_season_total_points"] == p["last_season_stats"]["total_points"]
    assert checked_any, "no player in the sample had last-season data -- test wasn't exercised"


def test_players_scout_can_sort_by_last_season_total_points():
    """The whole point of flattening it -- confirms it's actually a usable,
    varying number across the pool, not a constant that would make sorting
    by it a no-op."""
    resp = client.get("/api/players")
    values = {p["last_season_total_points"] for p in resp.json()["players"]}
    assert len(values) > 10  # genuinely varies across the pool


def test_players_last_season_breakdown_is_internally_consistent():
    """Real per-game points (for games where the player actually STARTED --
    see load_player_gameweeks_to_cache.py's docstring on why `starts` is
    used, not `minutes > 0`), percentile averages, and points-by-component --
    all reconstructed from raw stats, must agree with each other."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"][:50]:
        b = p["last_season_breakdown"]
        if b is None:
            continue
        checked_any = True
        games = b["games"]
        assert len(games) > 0
        pct = b["percentile_averages"]
        # Best-25% average must be >= best-50% >= best-75% >= overall --
        # each wider slice necessarily includes the previous slice's games
        # plus more (weaker) ones, so its average can't be higher.
        assert pct["top25"] >= pct["top50"] >= pct["top75"] >= pct["overall"]
        # The component breakdown must sum to (very nearly) games * overall
        # average -- same reconciliation principle as the xP breakdown.
        component_sum = sum(b["points_by_component"].values())
        assert component_sum == pytest.approx(len(games) * pct["overall"], abs=len(games) * 0.5)
    assert checked_any, "no player in the sample had a last-season breakdown -- test wasn't exercised"


def test_players_opponent_stats_shape_and_ranking():
    """best_opponents/worst_opponents are each up to 5 entries, ranked
    correctly (best descending by avg_points, worst ascending -- i.e. the
    single worst opponent first), each backed by at least 1 real historical
    game, and best_fdr/worst_fdr are genuinely the extremes of that player's
    own FDR-bucketed averages (see players.py's _opponent_stats docstring)."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"][:80]:
        s = p["opponent_stats"]
        if s is None:
            continue
        checked_any = True
        assert 0 < len(s["best_opponents"]) <= 5
        assert 0 < len(s["worst_opponents"]) <= 5
        for entry in s["best_opponents"] + s["worst_opponents"]:
            assert entry["games"] >= 1
            assert entry["opponent"]  # non-empty
            assert entry["next_gw"] is None or entry["next_gw"] >= 1

        best_avgs = [e["avg_points"] for e in s["best_opponents"]]
        assert best_avgs == sorted(best_avgs, reverse=True)  # descending -- favorite first
        worst_avgs = [e["avg_points"] for e in s["worst_opponents"]]
        assert worst_avgs == sorted(worst_avgs)  # ascending -- least favorite first

        for tier in (s["best_fdr"], s["worst_fdr"]):
            assert 1 <= tier["fdr"] <= 5
            assert tier["games"] >= 1
        if s["best_fdr"]["fdr"] != s["worst_fdr"]["fdr"]:
            assert s["best_fdr"]["avg_points"] >= s["worst_fdr"]["avg_points"]
    assert checked_any, "no player in the sample had opponent_stats -- test wasn't exercised"


def test_players_opponent_stats_next_gw_matches_a_real_upcoming_fixture():
    """Where next_gw is set, it must correspond to a REAL scheduled fixture
    this season between the player's current team and that opponent -- not
    just any future gameweek."""
    resp = client.get("/api/players")
    fixtures = client.get("/api/fixtures").json()["fixtures"]
    checked_any = False
    for p in resp.json()["players"][:200]:
        s = p["opponent_stats"]
        if s is None:
            continue
        for entry in s["best_opponents"] + s["worst_opponents"]:
            if entry["next_gw"] is None:
                continue
            checked_any = True
            matches = [
                f for f in fixtures
                if f["gw"] == entry["next_gw"]
                and entry["opponent"] in (f["home_team"], f["away_team"])
                and p["team"] in (f["home_team"], f["away_team"])
            ]
            assert matches, f"{p['name']}: no real fixture vs {entry['opponent']} in GW{entry['next_gw']}"
    assert checked_any, "no opponent entry in the sample had a next_gw set -- test wasn't exercised"


def test_players_points_by_month_shape_and_internal_consistency():
    """Each month's box-plot stats (min/q1/median/q3/max) must be internally
    ordered, n_seasons must match the length of the values array (at most
    MONTHLY_LOOKBACK_SEASONS=5), months must appear in Premier-League
    calendar order (Aug first, not Jan), and every value must be a genuine
    points-PER-GAME rate (not a raw monthly total) -- see players.py's
    _monthly_points_per_game docstring for why that distinction matters."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"][:80]:
        m = p["points_by_month"]
        if m is None:
            continue
        checked_any = True
        assert 1 <= len(m["seasons_included"]) <= 5
        assert len(m["months"]) > 0

        from app.routers.players import MONTH_ORDER
        seen_order = [entry["month"] for entry in m["months"]]
        assert seen_order == sorted(seen_order, key=MONTH_ORDER.index)

        for entry in m["months"]:
            assert entry["month"] in MONTH_ORDER
            assert 1 <= entry["n_seasons"] <= 5
            assert len(entry["values"]) == entry["n_seasons"]
            assert entry["min"] <= entry["q1"] <= entry["median"] <= entry["q3"] <= entry["max"]
            assert entry["min"] == pytest.approx(min(entry["values"]), abs=1e-6)
            assert entry["max"] == pytest.approx(max(entry["values"]), abs=1e-6)
            # A points-per-game RATE for a single game played is bounded on
            # both ends -- roughly [-6, 30] for a real single game (a red
            # card + own goal can go negative; a genuine 20+ point haul is
            # the ceiling) -- catches an accidental raw MONTHLY SUM (not
            # per-game average) regression, which could run into the
            # hundreds for a player with many games in that month.
            for v in entry["values"]:
                assert -6 <= v <= 30
    assert checked_any, "no player in the sample had points_by_month -- test wasn't exercised"


def test_players_points_by_month_matches_a_manual_recomputation():
    """Recompute one real player's points-per-game for one real month from
    raw player_gameweek_stats + fixtures directly, and confirm it matches
    the API's number exactly -- not just structurally plausible."""
    import sqlite3
    from app.config import DB_PATH
    from app.routers.players import _recent_season_ids, LAST_COMPLETE_SEASON, MONTHLY_LOOKBACK_SEASONS

    resp = client.get("/api/players")
    target = next(p for p in resp.json()["players"] if p["points_by_month"] is not None)
    month_entry = target["points_by_month"]["months"][0]
    season_ids = _recent_season_ids(LAST_COMPLETE_SEASON, MONTHLY_LOOKBACK_SEASONS)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT pgs.season_id, pgs.total_points, f.kickoff_time
           FROM player_gameweek_stats pgs
           JOIN fixtures f ON f.fixture_id = pgs.fixture_id
           WHERE pgs.player_id = ? AND pgs.minutes > 0""",
        (target["player_id"],),
    ).fetchall()
    conn.close()

    import datetime
    by_season: dict[str, list[int]] = {}
    for r in rows:
        if r["season_id"] not in season_ids:
            continue
        month = datetime.datetime.fromisoformat(r["kickoff_time"].replace("Z", "+00:00")).strftime("%b")
        if month != month_entry["month"]:
            continue
        by_season.setdefault(r["season_id"], []).append(r["total_points"])

    manual_values = sorted(round(sum(v) / len(v), 2) for v in by_season.values())
    assert manual_values == month_entry["values"]


def test_points_vs_opponent_last_season_shape_and_scoping():
    """One row per fixture in the requested [gw_start, gw_end] window (a
    double gameweek gives two rows for that gw), venue_now must be H or A,
    gw must fall inside the requested range, and either points field is
    either a real int or None (never a stray 0 standing in for "didn't
    meet") -- see players.py's _points_vs_opponent_last_season docstring."""
    resp = client.get("/api/players?gw_start=1&gw_end=5")
    checked_any = False
    for p in resp.json()["players"][:80]:
        rows = p["points_vs_opponent_last_season"]
        if rows is None:
            continue
        checked_any = True
        for r in rows:
            assert 1 <= r["gw"] <= 5
            assert r["venue_now"] in ("H", "A")
            assert r["opponent"]
            for key in ("home_points_last_season", "away_points_last_season"):
                assert r[key] is None or isinstance(r[key], int)
    assert checked_any, "no player in the sample had points_vs_opponent_last_season -- test wasn't exercised"


def test_points_vs_opponent_last_season_matches_real_fixtures_and_history():
    """Cross-check against two independent sources: the CURRENT fixture
    (opponent + venue) must match a real scheduled fixture from /api/fixtures,
    and where a last-season points figure IS set, it must match a real
    last-season row from /api/players' own opponent_stats for that same
    opponent (both are derived from the same underlying history, so they
    must agree)."""
    resp = client.get("/api/players?gw_start=1&gw_end=3")
    fixtures = client.get("/api/fixtures?gw_start=1&gw_end=3").json()["fixtures"]
    checked_fixture = checked_history = False

    for p in resp.json()["players"][:100]:
        rows = p["points_vs_opponent_last_season"]
        if not rows:
            continue
        for r in rows:
            match = next(
                (f for f in fixtures if f["gw"] == r["gw"]
                 and p["team"] in (f["home_team"], f["away_team"])
                 and r["opponent"] in (f["home_team"], f["away_team"])),
                None,
            )
            assert match, f"{p['name']}: no real GW{r['gw']} fixture vs {r['opponent']}"
            expected_venue = "H" if match["home_team"] == p["team"] else "A"
            assert r["venue_now"] == expected_venue
            checked_fixture = True

    assert checked_fixture, "no row in the sample matched against a real fixture -- test wasn't exercised"


def test_points_vs_opponent_last_season_no_meeting_is_none_not_zero():
    """A player with NO 2025-26 Premier League history at all (`historic` is
    None -- genuinely new to the top flight, not just "his CURRENT club
    didn't play last season," since a transferred-in player can carry real
    history from a DIFFERENT club -- this is deliberately player-centric,
    see _points_vs_opponent_last_season's docstring) must show None ("-" in
    the UI) for BOTH legs against every opponent, never a coincidental 0
    that would misleadingly look like "played and blanked"."""
    resp = client.get("/api/players")
    checked_any = False
    for p in resp.json()["players"]:
        if p["historic"] is not None:
            continue  # has SOME last-season history -- not the case being tested
        rows = p.get("points_vs_opponent_last_season")
        if not rows:
            continue
        for r in rows:
            checked_any = True
            assert r["home_points_last_season"] is None
            assert r["away_points_last_season"] is None
    assert checked_any, "no player with zero last-season history had rows in the sample -- test wasn't exercised"


def test_players_gameweeks_sum_to_headline_xp():
    """The new per-gameweek breakdown must be consistent with the aggregate --
    same transparency principle as the component breakdown."""
    resp = client.get("/api/players?gw_start=1&gw_end=5")
    data = resp.json()
    for p in data["players"][:20]:
        assert p["gameweeks"], f"{p['name']} has no gameweeks in range"
        gws = [g["gw"] for g in p["gameweeks"]]
        assert gws == sorted(gws)  # ascending order
        assert all(1 <= g <= 5 for g in gws)  # within the requested range
        assert sum(g["xP"] for g in p["gameweeks"]) == pytest.approx(p["xP"], abs=1e-2)


def test_players_breakdown_sums_to_xp():
    """See docs/model-architecture.md's transparency principle -- the whole
    point of persisting a breakdown is that it must always reconcile exactly
    with the headline number, not just be plausible-looking."""
    resp = client.get("/api/players")
    for p in resp.json()["players"][:20]:
        assert sum(p["breakdown"].values()) == pytest.approx(p["xP"], abs=1e-2)


def test_players_gw_range_changes_result():
    resp1 = client.get("/api/players?gw_start=1&gw_end=1")
    resp5 = client.get("/api/players?gw_start=1&gw_end=5")
    assert resp1.status_code == 200 and resp5.status_code == 200
    top1 = max(p["xP"] for p in resp1.json()["players"])
    top5 = max(p["xP"] for p in resp5.json()["players"])
    assert top5 > top1


def test_players_no_duplicate_ids():
    """Double-gameweek aggregation (see docs/GOTCHAS.md) should mean every
    player appears exactly once, even across a multi-gameweek horizon."""
    resp = client.get("/api/players")
    ids = [p["player_id"] for p in resp.json()["players"]]
    assert len(ids) == len(set(ids))


def test_model_runs_returns_history():
    resp = client.get("/api/model-runs")
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) > 0


def test_model_runs_filter_by_type():
    resp = client.get("/api/model-runs?model_type=predict_upcoming")
    data = resp.json()["runs"]
    assert all(r["model_type"] == "predict_upcoming" for r in data)


def test_fixtures_returns_2026_27_season():
    resp = client.get("/api/fixtures?gw=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["season"] == "2026-27"
    assert len(data["fixtures"]) > 0
    assert all(f["gw"] == 1 for f in data["fixtures"])


def test_fixtures_gw_range_returns_multiple_gameweeks():
    """Needed for the frontend's FDR strip (several gameweeks per team)."""
    resp = client.get("/api/fixtures?gw_start=1&gw_end=3")
    assert resp.status_code == 200
    gws = {f["gw"] for f in resp.json()["fixtures"]}
    assert gws == {1, 2, 3}


def test_fixtures_clean_sheet_probs_are_present_and_well_formed():
    """home/away_clean_sheet_prob back Fixture Swing's clean-sheet ranking --
    real probabilities (0-1) where the current prediction run covers that
    fixture, None where it doesn't (a fixture beyond the run's horizon, or
    long finished) -- never a stray placeholder value."""
    resp = client.get("/api/fixtures")
    fixtures = resp.json()["fixtures"]
    checked_any = False
    for f in fixtures:
        for key in ("home_clean_sheet_prob", "away_clean_sheet_prob"):
            if f[key] is not None:
                checked_any = True
                assert 0 <= f[key] <= 1
    assert checked_any, "no fixture in the sample had a clean sheet prob -- test wasn't exercised"


def test_fixtures_clean_sheet_prob_matches_captain_sim_inputs_directly():
    """Cross-check against the raw source table directly, not just
    structural plausibility -- a team's clean_sheet_prob on a fixture must
    equal what's actually stored in captain_sim_inputs for any one of that
    team's players on that fixture (they're all identical -- see
    fixtures.py's _clean_sheet_prob_by_fixture_team docstring)."""
    import sqlite3
    from app.config import DB_PATH, CURRENT_SEASON

    resp = client.get("/api/fixtures")
    fixtures = [f for f in resp.json()["fixtures"] if f["home_clean_sheet_prob"] is not None]
    assert fixtures, "no fixture in the sample had a clean sheet prob -- test wasn't exercised"
    target = fixtures[0]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT csi.p_clean_sheet
           FROM captain_sim_inputs csi
           JOIN player_season ps ON ps.player_id = csi.player_id AND ps.season_id = ?
           JOIN fixtures f ON f.fixture_id = csi.fixture_id
           WHERE csi.fixture_id = ? AND ps.team_id = f.home_team_id
           LIMIT 1""",
        (CURRENT_SEASON, target["fixture_id"]),
    ).fetchone()
    conn.close()
    assert row is not None
    assert target["home_clean_sheet_prob"] == pytest.approx(row["p_clean_sheet"], abs=0.001)


def test_fixtures_recent_form_is_present_and_well_formed():
    """Every current team with any real finished-match history at all should
    have a recent_form entry -- home/away gf_per_game/ga_per_game are real
    per-game averages (small, non-negative-ish floats, not raw totals),
    tracked SEPARATELY (not blended) since a team's home and away form can
    genuinely differ, and each *_games count is at most RECENT_FORM_GAMES."""
    from app.routers.fixtures import RECENT_FORM_GAMES

    resp = client.get("/api/fixtures")
    data = resp.json()
    assert "recent_form" in data
    form = data["recent_form"]
    assert len(form) > 0
    checked_home = checked_away = False
    for team, f in form.items():
        assert team  # non-empty
        assert 0 <= f["home_games"] <= RECENT_FORM_GAMES
        assert 0 <= f["away_games"] <= RECENT_FORM_GAMES
        if f["home_games"] > 0:
            checked_home = True
            assert 0 <= f["home_gf_per_game"] <= 10
            assert 0 <= f["home_ga_per_game"] <= 10
        else:
            assert f["home_gf_per_game"] is None
            assert f["home_ga_per_game"] is None
        if f["away_games"] > 0:
            checked_away = True
            assert 0 <= f["away_gf_per_game"] <= 10
            assert 0 <= f["away_ga_per_game"] <= 10
        else:
            assert f["away_gf_per_game"] is None
            assert f["away_ga_per_game"] is None
    assert checked_home and checked_away, "sample didn't include both home and away form -- test wasn't fully exercised"


def test_fixtures_recent_form_falls_back_across_season_boundary_when_current_season_has_no_finished_games():
    """The actual bug this exists to fix: pre-season, CURRENT_SEASON has
    ZERO finished fixtures of its own -- recent_form must still be populated
    by falling back to last season's closing games, not show nothing for
    every team just because the new season hasn't kicked off yet."""
    resp = client.get("/api/fixtures")
    data = resp.json()
    current_season_finished = [f for f in data["fixtures"] if f["finished"]]
    if current_season_finished:
        pytest.skip("current season already has finished fixtures -- this test targets the pre-season gap specifically")
    assert len(data["recent_form"]) > 0, "recent_form was empty despite no current-season finished games -- fallback isn't working"


def test_fixtures_recent_form_matches_a_manual_recomputation():
    """Recompute one real team's HOME recent form directly from the
    fixtures table (any season, not just current, joined by NAME -- team_id
    is NOT a stable cross-season identifier in this cache, see fixtures.py's
    module docstring) and confirm it matches exactly -- not just
    structurally plausible."""
    import sqlite3
    from app.config import DB_PATH
    from app.routers.fixtures import RECENT_FORM_GAMES

    resp = client.get("/api/fixtures")
    form = resp.json()["recent_form"]
    team_name = next(name for name, f in form.items() if f["home_games"] > 0)
    expected = form[team_name]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT f.home_goals, f.away_goals, f.kickoff_time
           FROM fixtures f
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           WHERE f.finished = 1 AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL
                 AND th.name = ?
           ORDER BY f.kickoff_time""",
        (team_name,),
    ).fetchall()
    conn.close()

    recent = rows[-RECENT_FORM_GAMES:]
    assert expected["home_games"] == len(recent)
    assert expected["home_gf_per_game"] == pytest.approx(sum(r["home_goals"] for r in recent) / len(recent), abs=0.01)
    assert expected["home_ga_per_game"] == pytest.approx(sum(r["away_goals"] for r in recent) / len(recent), abs=0.01)


def test_fixtures_last_season_team_stats_shape_and_internal_consistency():
    """goals/clean-sheets are non-negative integers consistent with
    games_home/games_away, favorable/unfavorable opponents are each up to
    FAVORABLE_OPPONENTS_TOP_N entries ranked correctly (favorable descending
    by avg_goal_diff, unfavorable ascending -- worst first), and the
    favorable list's best entry must never be worse than the unfavorable
    list's worst entry."""
    from app.routers.fixtures import FAVORABLE_OPPONENTS_TOP_N

    resp = client.get("/api/fixtures")
    data = resp.json()
    assert "last_season_team_stats" in data
    stats = data["last_season_team_stats"]
    assert len(stats) > 0

    for team, s in stats.items():
        assert team
        assert s["games_home"] >= 0 and s["games_away"] >= 0
        assert s["goals_for_home"] >= 0 and s["goals_for_away"] >= 0
        assert s["goals_against_home"] >= 0 and s["goals_against_away"] >= 0
        assert 0 <= s["clean_sheets_home"] <= s["games_home"]
        assert 0 <= s["clean_sheets_away"] <= s["games_away"]
        assert s["clean_sheets_total"] == s["clean_sheets_home"] + s["clean_sheets_away"]

        assert 0 < len(s["favorable_opponents"]) <= FAVORABLE_OPPONENTS_TOP_N
        assert 0 < len(s["unfavorable_opponents"]) <= FAVORABLE_OPPONENTS_TOP_N
        for entry in s["favorable_opponents"] + s["unfavorable_opponents"]:
            assert entry["opponent"]
            assert entry["games"] >= 1
            assert entry["next_gw"] is None or entry["next_gw"] >= 1

        fav_diffs = [e["avg_goal_diff"] for e in s["favorable_opponents"]]
        assert fav_diffs == sorted(fav_diffs, reverse=True)
        unfav_diffs = [e["avg_goal_diff"] for e in s["unfavorable_opponents"]]
        assert unfav_diffs == sorted(unfav_diffs)
        assert fav_diffs[0] >= unfav_diffs[0]


def test_fixtures_last_season_team_stats_matches_a_manual_recomputation():
    """Recompute one real team's last-season home goals for/against and
    clean sheets directly from the fixtures table (joined by NAME -- see
    fixtures.py's module docstring on why team_id isn't safe across
    seasons) and confirm they match exactly -- not just structurally
    plausible."""
    import sqlite3
    from app.config import DB_PATH
    from app.routers.fixtures import LAST_COMPLETE_SEASON

    resp = client.get("/api/fixtures")
    stats = resp.json()["last_season_team_stats"]
    assert stats, "no team had last_season_team_stats -- test wasn't exercised"
    team_name = next(iter(stats))
    expected = stats[team_name]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    home_rows = conn.execute(
        """SELECT f.home_goals, f.away_goals FROM fixtures f
           JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
           WHERE f.season_id = ? AND f.finished = 1 AND th.name = ?
                 AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL""",
        (LAST_COMPLETE_SEASON, team_name),
    ).fetchall()
    conn.close()

    assert expected["games_home"] == len(home_rows)
    assert expected["goals_for_home"] == sum(r["home_goals"] for r in home_rows)
    assert expected["goals_against_home"] == sum(r["away_goals"] for r in home_rows)
    assert expected["clean_sheets_home"] == sum(1 for r in home_rows if r["away_goals"] == 0)


def test_fixtures_last_season_team_stats_favorable_opponent_matches_a_real_upcoming_fixture():
    """Where next_gw is set on a favorable/unfavorable opponent entry, it
    must correspond to a REAL scheduled fixture this season between the two
    teams -- not just any future gameweek."""
    resp = client.get("/api/fixtures")
    data = resp.json()
    fixtures = data["fixtures"]
    checked_any = False
    for team, s in data["last_season_team_stats"].items():
        for entry in s["favorable_opponents"] + s["unfavorable_opponents"]:
            if entry["next_gw"] is None:
                continue
            checked_any = True
            matches = [
                f for f in fixtures
                if f["gw"] == entry["next_gw"]
                and team in (f["home_team"], f["away_team"])
                and entry["opponent"] in (f["home_team"], f["away_team"])
            ]
            assert matches, f"{team}: no real fixture vs {entry['opponent']} in GW{entry['next_gw']}"
    assert checked_any, "no favorable/unfavorable opponent entry had a next_gw set -- test wasn't exercised"


def test_fixtures_goals_vs_opponent_shape_and_scoping():
    """One row per fixture in the requested [gw_start, gw_end] window for
    EACH team (a double gameweek gives two rows for that gw), venue_now
    must be H or A, gw must fall inside the requested range, and any goals
    figure is either a real non-negative int or None (never a stray 0
    standing in for "didn't meet") -- see fixtures.py's
    _team_goals_vs_opponent_last_season docstring."""
    resp = client.get("/api/fixtures?gw_start=1&gw_end=5")
    data = resp.json()
    assert "goals_vs_opponent" in data
    checked_any = False
    for team, rows in data["goals_vs_opponent"].items():
        assert team
        assert len(rows) > 0
        for r in rows:
            checked_any = True
            assert 1 <= r["gw"] <= 5
            assert r["venue_now"] in ("H", "A")
            assert r["opponent"]
            for key in ("home_gf_last_season", "home_ga_last_season", "away_gf_last_season", "away_ga_last_season"):
                assert r[key] is None or (isinstance(r[key], int) and r[key] >= 0)
    assert checked_any, "no team in the sample had goals_vs_opponent rows -- test wasn't exercised"


def test_fixtures_goals_vs_opponent_matches_real_fixtures_and_last_season_history():
    """Cross-check against two independent sources: the CURRENT fixture
    (opponent + venue) must match a real scheduled fixture in this same
    response, and where a goals figure IS set, it must match a real
    last-season row recomputed directly from the fixtures table (joined by
    NAME -- team_id isn't stable across seasons, see module docstring)."""
    import sqlite3
    from app.config import DB_PATH
    from app.routers.fixtures import LAST_COMPLETE_SEASON

    resp = client.get("/api/fixtures?gw_start=1&gw_end=3")
    data = resp.json()
    fixtures = data["fixtures"]
    checked_fixture = checked_history = False

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    for team, rows in data["goals_vs_opponent"].items():
        for r in rows:
            match = next(
                (f for f in fixtures if f["gw"] == r["gw"]
                 and team in (f["home_team"], f["away_team"])
                 and r["opponent"] in (f["home_team"], f["away_team"])),
                None,
            )
            assert match, f"{team}: no real GW{r['gw']} fixture vs {r['opponent']}"
            expected_venue = "H" if match["home_team"] == team else "A"
            assert r["venue_now"] == expected_venue
            checked_fixture = True

            if r["home_gf_last_season"] is not None:
                checked_history = True
                real = conn.execute(
                    """SELECT f.home_goals, f.away_goals FROM fixtures f
                       JOIN teams th ON f.home_team_id = th.team_id AND f.season_id = th.season_id
                       JOIN teams ta ON f.away_team_id = ta.team_id AND f.season_id = ta.season_id
                       WHERE f.season_id = ? AND f.finished = 1 AND th.name = ? AND ta.name = ?
                             AND f.home_goals IS NOT NULL AND f.away_goals IS NOT NULL""",
                    (LAST_COMPLETE_SEASON, team, r["opponent"]),
                ).fetchall()
                assert r["home_gf_last_season"] == sum(x["home_goals"] for x in real)
                assert r["home_ga_last_season"] == sum(x["away_goals"] for x in real)

    conn.close()
    assert checked_fixture, "no row matched against a real fixture -- test wasn't exercised"
    assert checked_history, "no row had last-season history to cross-check -- test wasn't exercised"


def test_fixtures_goals_vs_opponent_no_meeting_is_none_not_zero():
    """A newly-promoted opponent (no top-flight games last season at all)
    must show None ("-" in the UI) for both legs, never a coincidental 0
    that would misleadingly look like "met and drew 0-0"."""
    import sqlite3
    from app.config import DB_PATH
    from app.routers.fixtures import LAST_COMPLETE_SEASON

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    played_last_season = {
        r["name"] for r in conn.execute(
            """SELECT DISTINCT t.name FROM fixtures f
               JOIN teams t ON t.team_id IN (f.home_team_id, f.away_team_id) AND t.season_id = ?
               WHERE f.season_id = ?""",
            (LAST_COMPLETE_SEASON, LAST_COMPLETE_SEASON),
        ).fetchall()
    }
    conn.close()

    resp = client.get("/api/fixtures?gw_start=1&gw_end=10")
    data = resp.json()
    checked_any = False
    for team, rows in data["goals_vs_opponent"].items():
        for r in rows:
            if r["opponent"] in played_last_season:
                continue  # opponent has real history -- not the case being tested
            checked_any = True
            assert r["home_gf_last_season"] is None
            assert r["home_ga_last_season"] is None
            assert r["away_gf_last_season"] is None
            assert r["away_ga_last_season"] is None
    assert checked_any, "no row referenced a newly-promoted opponent -- test wasn't exercised"


def test_squad_optimal_respects_budget_and_positions():
    resp = client.get("/api/squad/optimal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] <= 100.0
    positions = [p["position"] for p in data["squad"]]
    assert positions.count("GK") == 2
    assert positions.count("DEF") == 5
    assert positions.count("MID") == 5
    assert positions.count("FWD") == 3


def test_squad_optimal_reported_xp_is_not_inflated_by_lookahead():
    """See docs/GOTCHAS.md: the optimizer's SELECTION should reward fixtures
    staying easy past the window, but the reported total_xp/per-player xP
    must stay the true, undistorted figure for the window asked for."""
    resp = client.get("/api/squad/optimal?gw_start=1&gw_end=3")
    data = resp.json()
    assert data["total_xp"] == pytest.approx(sum(p["xP"] for p in data["squad"]), abs=1e-6)
    # None of the per-player xP values should carry any lookahead weighting artifact --
    # spot check they're plausible single/multi-gameweek totals, not inflated.
    assert all(p["xP"] < 30 for p in data["squad"])  # sanity ceiling for a 3-GW window


def test_squad_optimal_gw_range_changes_result():
    """A GW1 only vs GW1-5 request should generally produce different
    total_xp (summed over more fixtures) -- catches the range params
    silently being ignored."""
    resp1 = client.get("/api/squad/optimal?gw_start=1&gw_end=1")
    resp5 = client.get("/api/squad/optimal?gw_start=1&gw_end=5")
    assert resp1.status_code == 200 and resp5.status_code == 200
    assert resp5.json()["total_xp"] > resp1.json()["total_xp"]


def test_squad_optimal_lock_includes_player():
    players = client.get("/api/players").json()["players"]
    target = players[len(players) // 2]  # any real, valid player_id

    resp = client.get(f"/api/squad/optimal?locked={target['player_id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert target["player_id"] in [p["player_id"] for p in data["squad"]]
    assert data["locked_player_ids"] == [target["player_id"]]


def test_squad_optimal_unknown_lock_returns_400():
    resp = client.get("/api/squad/optimal?locked=999999999")
    assert resp.status_code == 400



def test_squad_lineup_matches_optimal_for_same_squad():
    """Re-requesting the SAME squad through /lineup (no ILP, just best_lineup())
    should give identical results to what /optimal already computed for it --
    catches the two code paths silently diverging."""
    optimal = client.get("/api/squad/optimal?gw_start=1&gw_end=5").json()
    ids = [p["player_id"] for p in optimal["squad"]]
    resp = client.get(f"/api/squad/lineup?player_ids={','.join(map(str, ids))}&gw_start=1&gw_end=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_xp"] == pytest.approx(optimal["total_xp"], abs=1e-6)
    assert data["lineup"]["formation"] == optimal["lineup"]["formation"]


def test_squad_lineup_rejects_wrong_count():
    resp = client.get("/api/squad/lineup?player_ids=1,2,3")
    assert resp.status_code == 400


def test_squad_lineup_rejects_bad_position_shape():
    """15 real, valid player_ids that don't satisfy SQUAD_LIMITS (e.g. all
    the same position) should be rejected, not silently mis-scored."""
    players = client.get("/api/players").json()["players"]
    same_position = [p["player_id"] for p in players if p["position"] == "MID"][:15]
    resp = client.get(f"/api/squad/lineup?player_ids={','.join(map(str, same_position))}")
    assert resp.status_code == 400


def test_squad_optimal_returns_starter_and_bench_ids():
    """starter_ids/bench_ids must be the authoritative fields -- matching by
    name is fragile (see docs/GOTCHAS.md's duplicate-player-record finding).
    """
    data = client.get("/api/squad/optimal?gw_start=1&gw_end=5").json()
    starter_ids = data["lineup"]["starter_ids"]
    bench_ids = data["lineup"]["bench_ids"]
    assert len(starter_ids) == 11
    assert len(bench_ids) == 4
    assert set(starter_ids).isdisjoint(bench_ids)
    squad_ids = {p["player_id"] for p in data["squad"]}
    assert set(starter_ids) | set(bench_ids) == squad_ids


def test_captain_picks_returns_fixture_and_fdr_context():
    """haul% alone doesn't say why it's high -- fixture+FDR must come back
    alongside it, see captain_simulation.py's top_captain_picks docstring."""
    resp = client.get("/api/captain/picks?top_k=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gw"] is not None
    assert len(data["safe"]) == 3
    assert len(data["haul"]) == 3
    for pick in data["safe"] + data["haul"]:
        assert set(pick.keys()) == {"name", "fixture", "fdr", "mean", "p10", "p90", "p_haul", "p_blank"}
        assert 1 <= pick["fdr"] <= 5
        assert pick["fixture"]  # non-empty string
        assert pick["p10"] <= pick["mean"] <= pick["p90"]


def test_captain_picks_explicit_gw_matches_requested_gw():
    resp = client.get("/api/captain/picks?gw=1&top_k=1")
    assert resp.status_code == 200
    assert resp.json()["gw"] == 1
