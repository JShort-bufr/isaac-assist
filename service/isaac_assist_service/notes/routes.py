# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sticky Note HTTP API. Apply runs only from an explicit confirm.

"""Sticky Note routes under ``/api/v1/notes``.

Nothing in create, list, delete, send, reject, or reconcile edits the stage.
Confirm of an executable plan is forwarded over the existing Kit RPC bridge
after a USD type check. A type mismatch is not applied. Nucleus and read-only
stages refuse confirm unless the caller names a writable session layer.
The note becomes ``applied`` only when Kit reports that the stage changed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .customdata import dictionary_for_notes, reconcile
from .kit_apply import apply_via_kit, undo_via_kit
from .proposals import propose_for_note
from .store import NoteStore, NoteStoreError
from .usd_types import prepare_plan

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
    read_only: bool = False
    session_layer: str = ""
    session_layer_writable: bool = False


class SendNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage_path: str
    ids: List[str]
    read_only: bool = False
    session_layer: str = ""
    session_layer_writable: bool = False


class ReviewNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage_path: str
    action: str
    ids: List[str] = Field(default_factory=list)
    read_only: bool = False
    session_layer: str = ""
    session_layer_writable: bool = False


class ReconcileNotes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage_path: str
    prims: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False
    session_layer: str = ""
    session_layer_writable: bool = False


def _store(
    stage_path: str,
    *,
    read_only: bool = False,
    session_layer: str = "",
    session_layer_writable: bool = False,
) -> NoteStore:
    try:
        return NoteStore(
            stage_path,
            read_only=read_only,
            session_layer=session_layer,
            session_layer_writable=session_layer_writable,
        )
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


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _require_region(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="region must be an object")
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    width = value.get("w", value.get("width"))
    height = value.get("h", value.get("height"))
    w = _number(width)
    h = _number(height)
    if x is None or y is None or w is None or h is None:
        raise HTTPException(status_code=400, detail="region needs x, y, width, height")
    if w < 0 or h < 0:
        raise HTTPException(status_code=400, detail="region width and height must be >= 0")
    region: Dict[str, Any] = {"x": x, "y": y, "w": w, "h": h, "width": w, "height": h}
    viewport = value.get("viewport")
    if isinstance(viewport, dict):
        vw = _number(viewport.get("width"))
        vh = _number(viewport.get("height"))
        if vw is None or vh is None or vw <= 0 or vh <= 0:
            raise HTTPException(status_code=400, detail="region.viewport needs positive width and height")
        region["viewport"] = {"width": vw, "height": vh}
    return region


def _get_note(store: NoteStore, note_id: str) -> Dict[str, Any]:
    if not note_id or not str(note_id).strip():
        raise HTTPException(status_code=400, detail="note id is required")
    note = store.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")
    return note


def _custom_payload(store: NoteStore) -> Optional[Dict[str, Any]]:
    if not store.custom_data_allowed:
        return None
    return dictionary_for_notes(store.list_notes())


def _plan_for_kit(proposal: Dict[str, Any], store: NoteStore) -> Dict[str, Any]:
    plan = dict(proposal)
    if store.session_layer:
        plan["session_layer"] = store.session_layer
        plan["session_layer_writable"] = store.session_layer_writable
    return plan


def _refuse_edit(store: NoteStore) -> None:
    if store.edits_allowed:
        return
    detail = store.edit_refusal or "stage is read-only; confirm and apply are refused"
    raise HTTPException(status_code=409, detail=detail)


async def _confirm_existing(store: NoteStore, note: Dict[str, Any]) -> Dict[str, Any]:
    note_id = note.get("id")
    if note.get("status") != "proposed":
        return {
            "id": note_id,
            "ok": False,
            "applied": False,
            "status": note.get("status"),
            "detail": "only a proposed note can be confirmed",
            "note": note,
        }
    proposal = dict(note.get("proposal") or {})
    if not proposal.get("executable"):
        note["status"] = "confirmed"
        note["error"] = ""
        store.update(note)
        logger.info("note confirmed without apply; id=%s", note_id)
        return {
            "id": note_id,
            "ok": True,
            "applied": False,
            "status": "confirmed",
            "detail": "proposal is not executable; no scene edit",
            "note": note,
        }
    prepared = prepare_plan(proposal)
    if not prepared["ok"]:
        note["proposal"] = prepared.get("plan") or proposal
        note["status"] = "rejected"
        note["error"] = prepared["error"]
        store.update(note)
        logger.info("note type check refused apply; id=%s", note_id)
        return {
            "id": note_id,
            "ok": False,
            "applied": False,
            "status": "rejected",
            "detail": prepared["error"],
            "error": prepared["error"],
            "note": note,
        }
    proposal = prepared["plan"]
    note["proposal"] = proposal
    if not store.edits_allowed:
        detail = store.edit_refusal or "stage is read-only; confirm and apply are refused"
        note["error"] = detail
        store.update(note)
        logger.info("note confirm refused; id=%s kind=%s", note_id, store.kind)
        return {
            "id": note_id,
            "ok": False,
            "applied": False,
            "status": note.get("status"),
            "detail": detail,
            "error": detail,
            "note": note,
        }
    outcome = await apply_via_kit(_plan_for_kit(proposal, store))
    if outcome.get("before") is not None:
        note["before"] = outcome["before"]
    command_failed = bool(outcome.get("command_failed"))
    detail = str(outcome.get("detail") or "")
    if outcome["applied"]:
        note["status"] = "applied"
        note["applied_seq"] = store.next_applied_seq()
        note["error"] = ""
    elif command_failed:
        note["status"] = "rejected"
        note["error"] = detail
    else:
        note["status"] = "confirmed"
        note["error"] = "" if outcome["applied"] else detail
    store.update(note)
    logger.info(
        "note confirm; id=%s status=%s kit_connected=%s",
        note_id,
        note["status"],
        outcome["kit_connected"],
    )
    body = {
        "id": note_id,
        "ok": outcome["applied"] or not command_failed,
        "applied": outcome["applied"],
        "kit_connected": outcome["kit_connected"],
        "status": note["status"],
        "detail": detail,
        "note": note,
    }
    if command_failed:
        body["ok"] = False
        body["error"] = detail
    return body


def _reject_existing(store: NoteStore, note: Dict[str, Any]) -> Dict[str, Any]:
    note_id = note.get("id")
    if note.get("status") not in ("draft", "sent", "proposed", "confirmed"):
        return {
            "id": note_id,
            "ok": False,
            "applied": False,
            "status": note.get("status"),
            "detail": "note cannot be rejected",
            "note": note,
        }
    note["status"] = "rejected"
    store.update(note)
    logger.info("note rejected; id=%s", note_id)
    return {
        "id": note_id,
        "ok": True,
        "applied": False,
        "status": "rejected",
        "detail": "rejected",
        "note": note,
    }


@router.post("")
async def create_note(body: NoteCreate):
    if not isinstance(body.key_attributes, dict):
        raise HTTPException(status_code=400, detail="key_attributes must be an object")
    store = _store(
        body.stage_path,
        read_only=body.read_only,
        session_layer=body.session_layer,
        session_layer_writable=body.session_layer_writable,
    )
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
    return {
        "note": note,
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
        "edits_allowed": store.edits_allowed,
    }


@router.get("")
async def list_notes(
    stage_path: str = Query(...),
    read_only: bool = Query(False),
    session_layer: str = Query(""),
    session_layer_writable: bool = Query(False),
):
    store = _store(
        stage_path,
        read_only=read_only,
        session_layer=session_layer,
        session_layer_writable=session_layer_writable,
    )
    return {
        "notes": store.list_notes(),
        "stage_path": store.stage_path,
        "kind": store.kind,
        "edits_allowed": store.edits_allowed,
        "custom_data_allowed": store.custom_data_allowed,
    }


@router.delete("")
async def delete_note(
    stage_path: str = Query(...),
    id: str = Query(...),
    read_only: bool = Query(False),
    session_layer: str = Query(""),
    session_layer_writable: bool = Query(False),
):
    store = _store(
        stage_path,
        read_only=read_only,
        session_layer=session_layer,
        session_layer_writable=session_layer_writable,
    )
    if not store.delete(id):
        raise HTTPException(status_code=404, detail="note not found")
    logger.info("note deleted; id=%s", id)
    return {"deleted": id}


@router.post("/send")
async def send_notes(body: SendNotes):
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids is required")
    store = _store(
        body.stage_path,
        read_only=body.read_only,
        session_layer=body.session_layer,
        session_layer_writable=body.session_layer_writable,
    )
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


@router.post("/review")
async def review_notes(body: ReviewNotes):
    if body.action not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="action must be confirm or reject")
    store = _store(
        body.stage_path,
        read_only=body.read_only,
        session_layer=body.session_layer,
        session_layer_writable=body.session_layer_writable,
    )
    if body.action == "reject" and not body.ids:
        raise HTTPException(status_code=400, detail="ids is required")
    if body.ids:
        ids = list(body.ids)
    else:
        ids = [note["id"] for note in store.list_notes() if note.get("status") == "proposed"]
    results = []
    for note_id in ids:
        note = store.get(note_id)
        if note is None:
            results.append(
                {
                    "id": note_id,
                    "ok": False,
                    "applied": False,
                    "status": "",
                    "detail": "note not found",
                }
            )
            continue
        if body.action == "confirm":
            results.append(await _confirm_existing(store, note))
        else:
            results.append(_reject_existing(store, note))
    return {
        "results": results,
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
    }


@router.post("/reconcile")
async def reconcile_notes(body: ReconcileNotes):
    store = _store(
        body.stage_path,
        read_only=body.read_only,
        session_layer=body.session_layer,
        session_layer_writable=body.session_layer_writable,
    )
    if not isinstance(body.prims, dict):
        raise HTTPException(status_code=400, detail="prims must be an object")
    merged = reconcile(store.list_notes(), body.prims)
    store.replace_all(merged)
    logger.info("notes reconciled; count=%s kind=%s", len(merged), store.kind)
    return {
        "notes": store.list_notes(),
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
        "stage_path": store.stage_path,
    }


@router.post("/{note_id}/confirm")
async def confirm_note(
    note_id: str,
    stage_path: str = Query(...),
    read_only: bool = Query(False),
    session_layer: str = Query(""),
    session_layer_writable: bool = Query(False),
):
    store = _store(
        stage_path,
        read_only=read_only,
        session_layer=session_layer,
        session_layer_writable=session_layer_writable,
    )
    note = _get_note(store, note_id)
    if note.get("status") != "proposed":
        raise HTTPException(status_code=409, detail="only a proposed note can be confirmed")
    result = await _confirm_existing(store, note)
    if result.get("detail") == "only a proposed note can be confirmed":
        raise HTTPException(status_code=409, detail=result["detail"])
    if result.get("error") and not result.get("applied") and result.get("status") == note.get("status") and not store.edits_allowed:
        raise HTTPException(status_code=409, detail=result["detail"])
    body = {
        "note": result["note"],
        "applied": result["applied"],
        "detail": result["detail"],
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
    }
    if "kit_connected" in result:
        body["kit_connected"] = result["kit_connected"]
    if result.get("error"):
        body["error"] = result["error"]
    return body


@router.post("/{note_id}/reject")
async def reject_note(
    note_id: str,
    stage_path: str = Query(...),
    read_only: bool = Query(False),
    session_layer: str = Query(""),
    session_layer_writable: bool = Query(False),
):
    store = _store(
        stage_path,
        read_only=read_only,
        session_layer=session_layer,
        session_layer_writable=session_layer_writable,
    )
    note = _get_note(store, note_id)
    if note.get("status") not in ("draft", "sent", "proposed", "confirmed"):
        raise HTTPException(status_code=409, detail="note cannot be rejected")
    result = _reject_existing(store, note)
    return {
        "note": result["note"],
        "applied": False,
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
    }


@router.post("/{note_id}/undo")
async def undo_note(
    note_id: str,
    stage_path: str = Query(...),
    read_only: bool = Query(False),
    session_layer: str = Query(""),
    session_layer_writable: bool = Query(False),
):
    store = _store(
        stage_path,
        read_only=read_only,
        session_layer=session_layer,
        session_layer_writable=session_layer_writable,
    )
    note = _get_note(store, note_id)
    if note.get("status") != "applied":
        raise HTTPException(status_code=409, detail="only an applied note can be undone")
    if store.last_applied_id() != note_id:
        raise HTTPException(status_code=409, detail="only the last applied note can be undone")
    _refuse_edit(store)
    outcome = await undo_via_kit()
    if not outcome["reverted"]:
        logger.info("note undo refused; id=%s kit_connected=%s", note_id, outcome["kit_connected"])
        return {
            "note": note,
            "reverted": False,
            "kit_connected": outcome["kit_connected"],
            "detail": outcome["detail"],
        }
    note["status"] = "reverted"
    note["error"] = ""
    store.update(note)
    logger.info("note reverted; id=%s", note_id)
    return {
        "note": note,
        "reverted": True,
        "kit_connected": True,
        "detail": outcome["detail"],
        "custom_data": _custom_payload(store),
        "custom_data_allowed": store.custom_data_allowed,
    }
