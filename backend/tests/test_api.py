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
    assert set(first.keys()) == {"player_id", "name", "position", "team", "team_code", "price", "xP", "breakdown", "gameweeks", "historic"}
    assert first["position"] in {"GK", "DEF", "MID", "FWD"}


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
