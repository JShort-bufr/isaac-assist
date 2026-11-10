# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sticky Note HTTP API. Apply runs only from the confirm route.

"""Sticky Note routes under ``/api/v1/notes``.

Nothing in create, list, delete, send, or reject calls ``apply_scene_edit``.
Confirm calls it only for an executable proposal whose status is ``proposed``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import apply as scene_apply
from .proposals import propose_for_note
from .store import NoteStore, NoteStoreError

logger = logging.getLogger("isaac_assist.notes")
router = APIRouter()


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage_path: str
    prim_path: str = ""
    prim_type: str = ""
    key_attributes: Dict[str, Any] = Field(default_factory=dict)
    world_transform: Optional[Dict[str, Any]] = None
    region: Optional[Dict[str, Any]] = None
    crop_path: Optional[str] = None
    comment: str = ""


class SendNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage_path: str
    ids: List[str]


def _store(stage_path: str) -> NoteStore:
    try:
        return NoteStore(stage_path)
    except NoteStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_transform(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="world_transform must be an object")
    if "matrix" in value:
        matrix = value["matrix"]
        ok = (
            isinstance(matrix, list)
            and len(matrix) == 4
            and all(isinstance(row, list) and len(row) == 4 for row in matrix)
        )
        if not ok:
            raise HTTPException(status_code=400, detail="world_transform.matrix must be 4x4")
        return {"matrix": matrix}
    needed = ("translate", "rotate", "scale")
    if all(key in value for key in needed):
        return {key: list(value[key]) for key in needed}
    raise HTTPException(
        status_code=400,
        detail="world_transform needs a 4x4 matrix or translate/rotate/scale",
    )


def _require_region(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="region must be an object")
    keys = ("x", "y", "width", "height")
    if not all(key in value for key in keys):
        raise HTTPException(status_code=400, detail="region needs x, y, width, height")
    return {key: value[key] for key in keys}


def _get_note(store: NoteStore, note_id: str) -> Dict[str, Any]:
    note = store.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note


@router.post("")
async def create_note(body: NoteCreate):
    if not isinstance(body.key_attributes, dict):
        raise HTTPException(status_code=400, detail="key_attributes must be an object")
    store = _store(body.stage_path)
    note = store.create(
        {
            "prim_path": body.prim_path,
            "prim_type": body.prim_type,
            "key_attributes": body.key_attributes,
            "world_transform": _require_transform(body.world_transform),
            "region": _require_region(body.region),
            "crop_path": body.crop_path,
            "comment": body.comment,
        }
    )
    logger.info("note created; id=%s status=%s", note["id"], note["status"])
    return {"note": note}


@router.get("")
async def list_notes(stage_path: str = Query(...)):
    store = _store(stage_path)
    return {"notes": store.list_notes(), "stage_path": store.stage_path}


@router.delete("")
async def delete_note(stage_path: str = Query(...), id: str = Query(...)):
    store = _store(stage_path)
    if not store.delete(id):
        raise HTTPException(status_code=404, detail="note not found")
    logger.info("note deleted; id=%s", id)
    return {"deleted": id}


@router.post("/send")
async def send_notes(body: SendNotes):
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids is required")
    store = _store(body.stage_path)
    updated = []
    for note_id in body.ids:
        note = _get_note(store, note_id)
        note["status"] = "sent"
        store.update(note)
        proposal = await propose_for_note(note)
        note["proposal"] = proposal
        note["status"] = "proposed"
        store.update(note)
        updated.append(note)
        logger.info("note proposed; id=%s executable=%s", note_id, bool(proposal.get("executable")))
    return {"notes": updated}


@router.post("/{note_id}/confirm")
async def confirm_note(note_id: str, stage_path: str = Query(...)):
    store = _store(stage_path)
    note = _get_note(store, note_id)
    if note.get("status") != "proposed":
        raise HTTPException(status_code=409, detail="only a proposed note can be confirmed")
    proposal = note.get("proposal") or {}
    if not proposal.get("executable"):
        note["status"] = "confirmed"
        store.update(note)
        logger.info("note confirmed without apply; id=%s", note_id)
        return {"note": note, "applied": False}
    scene_apply.apply_scene_edit(proposal)
    note["status"] = "applied"
    store.update(note)
    logger.info("note applied; id=%s op=%s", note_id, proposal.get("op"))
    return {"note": note, "applied": True}


@router.post("/{note_id}/reject")
async def reject_note(note_id: str, stage_path: str = Query(...)):
    store = _store(stage_path)
    note = _get_note(store, note_id)
    if note.get("status") not in ("draft", "sent", "proposed", "confirmed"):
        raise HTTPException(status_code=409, detail="note cannot be rejected")
    note["status"] = "rejected"
    store.update(note)
    logger.info("note rejected; id=%s", note_id)
    return {"note": note, "applied": False}
