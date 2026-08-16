"""Tests for /api/saved-squads (Squad Builder's "save as draft" feature).
Uses the REAL cache DB's saved_squads table (created by ensure_schema.py),
cleaning up any rows it creates so repeat runs don't accumulate test data.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.main import app
from app.services.db import get_connection

client = TestClient(app)


def _cleanup(squad_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM saved_squads WHERE id = ?", (squad_id,))
    conn.commit()
    conn.close()


def test_create_list_get_update_delete_roundtrip():
    ids = list(range(1, 16))
    locked = [1, 2]

    create_resp = client.post("/api/saved-squads", json={"name": "My Draft", "player_ids": ids, "locked_player_ids": locked})
    assert create_resp.status_code == 201
    created = create_resp.json()
    squad_id = created["id"]
    assert created["name"] == "My Draft"
    assert created["player_ids"] == ids
    assert created["locked_player_ids"] == locked

    try:
        list_resp = client.get("/api/saved-squads")
        assert list_resp.status_code == 200
        summaries = list_resp.json()["squads"]
        match = next(s for s in summaries if s["id"] == squad_id)
        assert match["name"] == "My Draft"
        assert match["player_count"] == 15
        # Summary list must NOT ship the full player_ids array (keeps the
        # list endpoint light -- detail is a separate fetch).
        assert "player_ids" not in match

        get_resp = client.get(f"/api/saved-squads/{squad_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["player_ids"] == ids
        assert get_resp.json()["locked_player_ids"] == locked

        update_resp = client.put(f"/api/saved-squads/{squad_id}", json={"name": "Renamed Draft"})
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["name"] == "Renamed Draft"
        assert updated["player_ids"] == ids  # unchanged, only name was patched
        assert updated["locked_player_ids"] == locked  # unchanged too

        replace_ids = list(range(100, 115))
        replace_resp = client.put(f"/api/saved-squads/{squad_id}", json={"player_ids": replace_ids, "locked_player_ids": []})
        assert replace_resp.status_code == 200
        assert replace_resp.json()["player_ids"] == replace_ids
        assert replace_resp.json()["locked_player_ids"] == []
        assert replace_resp.json()["name"] == "Renamed Draft"  # unchanged, only ids were patched

        delete_resp = client.delete(f"/api/saved-squads/{squad_id}")
        assert delete_resp.status_code == 204
        assert client.get(f"/api/saved-squads/{squad_id}").status_code == 404
    finally:
        _cleanup(squad_id)  # no-op if the delete above already succeeded


def test_create_defaults_locked_player_ids_to_empty_when_omitted():
    """Older frontend calls (or anyone hitting the API directly) that don't
    send locked_player_ids at all must still work -- defaults to "nothing
    locked", not a validation error."""
    resp = client.post("/api/saved-squads", json={"name": "No Locks Specified", "player_ids": [1, 2, 3]})
    assert resp.status_code == 201
    squad_id = resp.json()["id"]
    try:
        assert resp.json()["locked_player_ids"] == []
    finally:
        _cleanup(squad_id)


def test_create_rejects_locked_player_ids_not_in_the_squad():
    """A locked id that isn't even part of the saved squad is nonsensical --
    must be rejected, not silently accepted and forgotten on load anyway."""
    resp = client.post("/api/saved-squads", json={"name": "Bad Lock", "player_ids": [1, 2, 3], "locked_player_ids": [999]})
    assert resp.status_code == 422


def test_update_rejects_locked_player_ids_not_in_the_new_player_ids():
    resp = client.post("/api/saved-squads", json={"name": "Will Update", "player_ids": [1, 2, 3], "locked_player_ids": [1]})
    squad_id = resp.json()["id"]
    try:
        update_resp = client.put(f"/api/saved-squads/{squad_id}", json={"player_ids": [4, 5, 6]})  # drops player 1
        assert update_resp.status_code == 422
    finally:
        _cleanup(squad_id)


def test_get_unknown_squad_is_404():
    assert client.get("/api/saved-squads/999999999").status_code == 404


def test_update_unknown_squad_is_404():
    assert client.put("/api/saved-squads/999999999", json={"name": "x"}).status_code == 404


def test_delete_unknown_squad_is_404():
    assert client.delete("/api/saved-squads/999999999").status_code == 404


def test_create_rejects_empty_name():
    resp = client.post("/api/saved-squads", json={"name": "", "player_ids": [1, 2, 3]})
    assert resp.status_code == 422


def test_create_rejects_more_than_15_players():
    resp = client.post("/api/saved-squads", json={"name": "Too Many", "player_ids": list(range(16))})
    assert resp.status_code == 422


def test_partial_squad_can_be_saved():
    """A draft doesn't have to be a complete 15 -- an in-progress squad you
    want to come back to later is exactly the use case this feature is for."""
    resp = client.post("/api/saved-squads", json={"name": "Work In Progress", "player_ids": [1, 2, 3]})
    assert resp.status_code == 201
    squad_id = resp.json()["id"]
    try:
        assert resp.json()["player_ids"] == [1, 2, 3]
    finally:
        _cleanup(squad_id)
