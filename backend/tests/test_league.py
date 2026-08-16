"""Tests for GET /api/league/{league_id} -- proxies the live FPL classic-
league standings endpoint, so _fetch-equivalent httpx call is mocked here
too (see test_team.py's docstring for why: this hits a real external API).
"""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import app
from app.routers import league as league_module

client = TestClient(app)


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


def test_league_returns_ranked_standings(monkeypatch):
    fake_payload = {
        "league": {"name": "Test Mini League"},
        "standings": {"results": [
            {"rank": 1, "player_name": "Alice A", "entry_name": "Alice FC", "entry": 111, "total": 250},
            {"rank": 2, "player_name": "Bob B", "entry_name": "Bob United", "entry": 222, "total": 240},
        ]},
    }

    async def fake_get(self, url, **kwargs):
        return _FakeResponse(200, fake_payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/league/456")
    assert resp.status_code == 200
    data = resp.json()
    assert data["league_id"] == 456
    assert data["league_name"] == "Test Mini League"
    assert data["standings"] == [
        {"rank": 1, "manager_name": "Alice A", "team_name": "Alice FC", "team_id": 111, "total_points": 250},
        {"rank": 2, "manager_name": "Bob B", "team_name": "Bob United", "team_id": 222, "total_points": 240},
    ]


def test_league_unknown_id_returns_upstream_error_status(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResponse(404, None)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    resp = client.get("/api/league/999999999")
    assert resp.status_code == 404
