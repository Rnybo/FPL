"""Tests for GET /api/team/{team_id}. Real cache DB for the player pool
(same "verify against real data" philosophy as test_api.py) but _fetch_json
is monkeypatched -- team.py talks to the LIVE fantasy.premierleague.com API,
which for the current pre-season period returns no current gameweek at all
(GW1 deadline is 2026-08-21, after this was written -- see team.py's module
docstring), so real squad-published data genuinely doesn't exist yet to test
against. Monkeypatching lets this be tested deterministically regardless.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import app
from app.config import CURRENT_SEASON
from app.services.db import get_connection
from app.routers import team as team_module

client = TestClient(app)


def _real_squad_codes():
    """15 real (code, position) pairs from the current cache DB, matching
    SQUAD_LIMITS exactly (2 GK/5 DEF/5 MID/3 FWD) and all present in the
    latest predict_upcoming run -- so best_lineup/suggest_transfers get a
    genuinely valid, real squad to work with."""
    conn = get_connection()
    run_row = conn.execute(
        "SELECT run_id FROM model_runs WHERE model_type='predict_upcoming' ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert run_row is not None, "no predict_upcoming run in the cache DB -- can't test against real data"
    run_id = run_row["run_id"]

    need = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    picked: dict[str, list[int]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    element_ids: dict[int, int] = {}  # code -> a fabricated element id

    rows = conn.execute(
        """SELECT DISTINCT p.code, p.position
           FROM model_predictions mp
           JOIN players p ON p.player_id = mp.player_id
           JOIN player_season ps ON ps.player_id = p.player_id AND ps.season_id = ?
           WHERE mp.run_id = ? AND p.code IS NOT NULL""",
        (CURRENT_SEASON, run_id),
    ).fetchall()
    conn.close()

    for row in rows:
        pos = row["position"]
        if len(picked[pos]) < need[pos]:
            picked[pos].append(row["code"])
    assert all(len(v) == need[k] for k, v in picked.items()), \
        f"cache DB doesn't have enough real players per position to build a test squad: {picked}"

    codes = [c for lst in picked.values() for c in lst]
    for i, code in enumerate(codes):
        element_ids[code] = 90000 + i  # fabricated FPL element ids, just need to be unique
    return codes, element_ids


def _fake_bootstrap(current_gw: int | None, codes: list[int], element_ids: dict[int, int]):
    events = [{"id": 1, "is_current": current_gw == 1, "is_next": current_gw != 1}]
    elements = [{"id": eid, "code": code} for code, eid in element_ids.items()]
    return {"events": events, "elements": elements}


def test_team_before_season_start_reports_no_current_gameweek(monkeypatch):
    async def fake_fetch(url):
        if "/entry/123/" in url and "/event/" not in url:
            return 200, {"player_first_name": "Test", "player_last_name": "Manager",
                         "name": "Test FC", "summary_overall_rank": None, "summary_overall_points": 0}
        if "bootstrap-static" in url:
            return 200, {"events": [{"id": 1, "is_current": False, "is_next": True}], "elements": []}
        raise AssertionError(f"unexpected URL in this test: {url}")

    monkeypatch.setattr(team_module, "_fetch_json", fake_fetch)
    resp = client.get("/api/team/123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["squad_published"] is False
    assert data["picks"] is None
    assert "season hasn't started" in data["note"].lower()


def test_team_picks_not_yet_published_for_current_gw(monkeypatch):
    async def fake_fetch(url):
        if "/event/" in url:
            return 404, None
        if "bootstrap-static" in url:
            return 200, {"events": [{"id": 1, "is_current": True, "is_next": False}], "elements": []}
        return 200, {"player_first_name": "Test", "player_last_name": "Manager", "name": "Test FC"}

    monkeypatch.setattr(team_module, "_fetch_json", fake_fetch)
    resp = client.get("/api/team/123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["squad_published"] is False
    assert "not published yet" in data["note"].lower()


def test_team_with_published_squad_returns_matched_lineup_and_suggestions(monkeypatch):
    codes, element_ids = _real_squad_codes()
    bootstrap = _fake_bootstrap(current_gw=1, codes=codes, element_ids=element_ids)
    picks_payload = {
        "picks": [{"element": eid, "selling_price": 50} for eid in element_ids.values()],
        "entry_history": {"bank": 15},
    }

    async def fake_fetch(url):
        if "/event/" in url:
            return 200, picks_payload
        if "bootstrap-static" in url:
            return 200, bootstrap
        return 200, {"player_first_name": "Test", "player_last_name": "Manager", "name": "Test FC",
                     "summary_overall_rank": 12345, "summary_overall_points": 500}

    monkeypatch.setattr(team_module, "_fetch_json", fake_fetch)
    resp = client.get("/api/team/123")
    assert resp.status_code == 200
    data = resp.json()

    assert data["squad_published"] is True
    assert data["bank"] == pytest.approx(1.5)
    assert len(data["picks"]) == 15
    # selling_price (50 tenths = 5.0m) must be attached and distinct from
    # current price, since that's the whole point of matching this way.
    assert all(p["selling_price"] == pytest.approx(5.0) for p in data["picks"])

    assert data["lineup"] is not None
    assert sum(data["lineup"]["formation"].values()) == 11
    assert len(data["lineup"]["starter_ids"]) == 11
    assert len(data["lineup"]["bench_ids"]) == 4

    assert isinstance(data["suggestions"], list)
    if data["suggestions"]:
        assert set(data["suggestions"][0].keys()) == {"out_name", "in_name", "position", "gain", "cost_change"}


def test_team_unknown_manager_returns_upstream_error_status(monkeypatch):
    async def fake_fetch(url):
        return 404, None

    monkeypatch.setattr(team_module, "_fetch_json", fake_fetch)
    resp = client.get("/api/team/999999999")
    assert resp.status_code == 404
