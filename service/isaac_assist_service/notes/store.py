# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sidecar JSON store. Local stages stay next to the file. Nucleus and
# read-only stages use a hashed sidecar under the user data dir.

"""Persistence for sticky notes.

``/tmp/scene.usd`` is stored at ``/tmp/scene.usd.notes.json``. A Nucleus URL
or a read-only file is stored at
``~/.local/share/bufrai/isaac-assist/notes/<sha256>.notes.json``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .stage_access import StageAccess, StageAccessError, classify_stage

NOTE_STATUSES = (
    "draft",
    "sent",
    "proposed",
    "confirmed",
    "applied",
    "rejected",
    "reverted",
)
EDIT_OPS = ("set_attribute", "set_transform", "add_prim", "none")


class NoteStoreError(ValueError):
    """The stage path cannot host a sidecar."""


def sidecar_for(stage_path: str) -> Any:
    try:
        return classify_stage(stage_path).sidecar
    except StageAccessError as exc:
        raise NoteStoreError(str(exc)) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoteStore:
    def __init__(
        self,
        stage_path: str,
        *,
        read_only: bool = False,
        session_layer: str = "",
        session_layer_writable: bool = False,
    ):
        try:
            access = classify_stage(
                stage_path,
                read_only=read_only,
                session_layer=session_layer,
                session_layer_writable=session_layer_writable,
            )
        except StageAccessError as exc:
            raise NoteStoreError(str(exc)) from exc
        self.access: StageAccess = access
        self.stage_path = access.stage_path
        self.path = access.sidecar
        self.crop_dir = access.crop_dir
        self.kind = access.kind
        self.edits_allowed = access.edits_allowed
        self.custom_data_allowed = access.custom_data_allowed
        self.session_layer = access.session_layer
        self.session_layer_writable = access.session_layer_writable
        self.edit_refusal = access.detail
        self.notes: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        notes = data.get("notes", [])
        if not isinstance(notes, list):
            raise NoteStoreError("sidecar notes field must be a list")
        return notes

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stage_path": self.stage_path,
            "kind": self.kind,
            "notes": self.notes,
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _crop_path(self, note_id: str, requested: Any, region: Any) -> Optional[str]:
        if not region and not requested:
            return None
        canonical = self.crop_dir / f"{note_id}.png"
        if not requested:
            return str(canonical)
        candidate = Path(str(requested)).expanduser()
        if candidate.suffix.lower() != ".png":
            return str(canonical)
        try:
            candidate.resolve().relative_to(self.crop_dir.resolve())
        except ValueError:
            return str(canonical)
        return str(candidate)

    def create(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        note_id = uuid.uuid4().hex
        region = fields.get("region")
        crop_path = self._crop_path(note_id, fields.get("crop_path"), region)
        note = {
            "id": note_id,
            "created_at": _now(),
            "prim_path": fields.get("prim_path") or "",
            "prim_type": fields.get("prim_type") or "",
            "key_attributes": dict(fields.get("key_attributes") or {}),
            "world_transform": fields.get("world_transform"),
            "region": region,
            "crop_path": crop_path,
            "comment": fields.get("comment") or "",
            "status": "draft",
            "proposal": None,
        }
        self.notes.append(note)
        self.save()
        return note

    def list_notes(self) -> List[Dict[str, Any]]:
        return list(self.notes)

    def get(self, note_id: str) -> Optional[Dict[str, Any]]:
        for note in self.notes:
            if note.get("id") == note_id:
                return note
        return None

    def delete(self, note_id: str) -> bool:
        kept = [note for note in self.notes if note.get("id") != note_id]
        if len(kept) == len(self.notes):
            return False
        self.notes = kept
        self.save()
        return True

    def update(self, note: Dict[str, Any]) -> Dict[str, Any]:
        for index, current in enumerate(self.notes):
            if current.get("id") == note.get("id"):
                self.notes[index] = note
                self.save()
                return note
        raise KeyError(note.get("id"))

    def replace_all(self, notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(notes, list):
            raise NoteStoreError("notes must be a list")
        self.notes = list(notes)
        self.save()
        return self.list_notes()

    def next_applied_seq(self) -> int:
        current = 0
        for note in self.notes:
            try:
                current = max(current, int(note.get("applied_seq") or 0))
            except (TypeError, ValueError):
                continue
        return current + 1

    def last_applied_id(self) -> Optional[str]:
        chosen = None
        chosen_seq = -1
        chosen_index = -1
        for index, note in enumerate(self.notes):
            if note.get("status") != "applied":
                continue
            try:
                seq = int(note.get("applied_seq") or 0)
            except (TypeError, ValueError):
                seq = 0
            if seq > chosen_seq or (seq == chosen_seq and index > chosen_index):
                chosen = note.get("id")
                chosen_seq = seq
                chosen_index = index
        return chosen
