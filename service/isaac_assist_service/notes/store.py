# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sidecar JSON store: <stage>.notes.json next to a local stage file.

"""Persistence for sticky notes.

``/tmp/scene.usd`` is stored at ``/tmp/scene.usd.notes.json``. Nucleus and
other URL stages are rejected; that path is UNVERIFIED on Legion.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

NOTE_STATUSES = ("draft", "sent", "proposed", "confirmed", "applied", "rejected")
EDIT_OPS = ("set_attribute", "set_transform", "add_prim", "none")


class NoteStoreError(ValueError):
    """The stage path cannot host a local sidecar."""


def sidecar_for(stage_path: str) -> Path:
    if not stage_path or not str(stage_path).strip():
        raise NoteStoreError("stage_path is required")
    text = str(stage_path).strip()
    if "://" in text:
        raise NoteStoreError("sidecar store supports local stage paths only")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise NoteStoreError("stage_path must be absolute")
    return path.parent / f"{path.name}.notes.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoteStore:
    def __init__(self, stage_path: str):
        self.stage_path = str(Path(stage_path).expanduser())
        self.path = sidecar_for(self.stage_path)
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
        payload = {"stage_path": self.stage_path, "notes": self.notes}
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def create(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        note = {
            "id": uuid.uuid4().hex,
            "created_at": _now(),
            "prim_path": fields.get("prim_path") or "",
            "prim_type": fields.get("prim_type") or "",
            "key_attributes": dict(fields.get("key_attributes") or {}),
            "world_transform": fields.get("world_transform"),
            "region": fields.get("region"),
            "crop_path": fields.get("crop_path"),
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
