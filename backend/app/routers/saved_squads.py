"""GET/POST/PUT/DELETE /api/saved-squads -- named snapshots of a squad, for
Squad Builder's "save as draft" feature. Only player_ids (+ which of them
were locked) are ever stored -- xP/price/everything else is ALWAYS
re-resolved live against whatever predictions are current at LOAD time,
never frozen at save time, so a draft saved weeks ago reflects TODAY's
model, not a stale one (matches this app's "never a black box, always
current" principle elsewhere -- e.g. My Team's transfer suggestions use
current selling price, not a cached one).

locked_player_ids exists specifically because it was previously missing: a
draft saved WITH locked players would silently forget them on reload (only
player_ids was persisted), so a follow-up "Optimize with bank" run in Squad
Builder came back fully unconstrained instead of respecting whatever had
actually been locked in.

Solo, single-user app, no auth (see docs/build-spec-inspiration.md) -- so
there's deliberately no owner/user_id column here.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db import get_connection

router = APIRouter(prefix="/api/saved-squads", tags=["saved-squads"])


class SavedSquadIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    player_ids: list[int] = Field(min_length=1, max_length=15)
    locked_player_ids: list[int] = Field(default_factory=list, max_length=15)


class SavedSquadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    player_ids: list[int] | None = Field(default=None, min_length=1, max_length=15)
    locked_player_ids: list[int] | None = Field(default=None, max_length=15)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_locked(row) -> list[int]:
    # Pre-existing rows from before this column existed default to '[]' at
    # the SQL level (see schema.sql), but guard here too in case of an old
    # NULL slipping through some other path.
    raw = row["locked_player_ids"]
    return json.loads(raw) if raw else []


def _validate_locked_subset(locked_player_ids: list[int], player_ids: list[int]):
    if not set(locked_player_ids).issubset(set(player_ids)):
        raise HTTPException(422, "locked_player_ids must be a subset of player_ids")


def _row_to_summary(row) -> dict:
    return {
        "id": row["id"], "name": row["name"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "player_count": len(json.loads(row["player_ids"])),
    }


def _row_to_detail(row) -> dict:
    return {
        "id": row["id"], "name": row["name"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "player_ids": json.loads(row["player_ids"]),
        "locked_player_ids": _parse_locked(row),
    }


@router.get("")
def list_saved_squads():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM saved_squads ORDER BY updated_at DESC").fetchall()
    conn.close()
    return {"squads": [_row_to_summary(r) for r in rows]}


@router.get("/{squad_id}")
def get_saved_squad(squad_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM saved_squads WHERE id = ?", (squad_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, f"No saved squad with id {squad_id}")
    return _row_to_detail(row)


@router.post("", status_code=201)
def create_saved_squad(body: SavedSquadIn):
    _validate_locked_subset(body.locked_player_ids, body.player_ids)
    now = _now()
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO saved_squads (name, player_ids, locked_player_ids, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (body.name, json.dumps(body.player_ids), json.dumps(body.locked_player_ids), now, now),
    )
    conn.commit()
    squad_id = cur.lastrowid
    conn.close()
    return {
        "id": squad_id, "name": body.name, "created_at": now, "updated_at": now,
        "player_ids": body.player_ids, "locked_player_ids": body.locked_player_ids,
    }


@router.put("/{squad_id}")
def update_saved_squad(squad_id: int, body: SavedSquadUpdate):
    conn = get_connection()
    row = conn.execute("SELECT * FROM saved_squads WHERE id = ?", (squad_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(404, f"No saved squad with id {squad_id}")
    name = body.name if body.name is not None else row["name"]
    player_ids = body.player_ids if body.player_ids is not None else json.loads(row["player_ids"])
    locked_player_ids = body.locked_player_ids if body.locked_player_ids is not None else _parse_locked(row)
    _validate_locked_subset(locked_player_ids, player_ids)
    now = _now()
    conn.execute(
        "UPDATE saved_squads SET name = ?, player_ids = ?, locked_player_ids = ?, updated_at = ? WHERE id = ?",
        (name, json.dumps(player_ids), json.dumps(locked_player_ids), now, squad_id),
    )
    conn.commit()
    conn.close()
    return {
        "id": squad_id, "name": name, "created_at": row["created_at"], "updated_at": now,
        "player_ids": player_ids, "locked_player_ids": locked_player_ids,
    }


@router.delete("/{squad_id}", status_code=204)
def delete_saved_squad(squad_id: int):
    conn = get_connection()
    row = conn.execute("SELECT id FROM saved_squads WHERE id = ?", (squad_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(404, f"No saved squad with id {squad_id}")
    conn.execute("DELETE FROM saved_squads WHERE id = ?", (squad_id,))
    conn.commit()
    conn.close()
