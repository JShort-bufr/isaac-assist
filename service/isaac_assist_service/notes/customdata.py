# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Prim customData mirror. The sidecar wins when the two disagree.

"""Reconcile sticky notes with prim ``customData``."""

from __future__ import annotations

from typing import Any, Dict, List

CUSTOM_KEY = "bufrai:stickyNotes"


def entry_for(note: Dict[str, Any]) -> Dict[str, str]:
    return {
        "comment": note.get("comment") or "",
        "status": note.get("status") or "",
        "created_at": note.get("created_at") or "",
    }


def dictionary_for_notes(notes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, str]]]:
    grouped: Dict[str, Dict[str, Dict[str, str]]] = {}
    for note in notes:
        prim_path = note.get("prim_path") or ""
        note_id = note.get("id") or ""
        if not prim_path or not note_id:
            continue
        grouped.setdefault(prim_path, {})[note_id] = entry_for(note)
    return grouped


def reconcile(
    sidecar_notes: List[Dict[str, Any]],
    custom_by_prim: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Sidecar fields win. Notes that exist only on a prim are appended."""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for note in sidecar_notes:
        note_id = note.get("id")
        if not note_id:
            continue
        copied = dict(note)
        merged[note_id] = copied
        order.append(note_id)
    for prim_path, entries in (custom_by_prim or {}).items():
        if not isinstance(entries, dict):
            continue
        for note_id, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            if note_id in merged:
                current = merged[note_id]
                for key in ("comment", "status", "created_at"):
                    if not current.get(key) and entry.get(key):
                        current[key] = entry[key]
                continue
            created = {
                "id": note_id,
                "created_at": entry.get("created_at") or "",
                "prim_path": str(prim_path),
                "prim_type": "",
                "key_attributes": {},
                "world_transform": None,
                "region": None,
                "crop_path": None,
                "comment": entry.get("comment") or "",
                "status": entry.get("status") or "draft",
                "proposal": None,
            }
            merged[note_id] = created
            order.append(note_id)
    return [merged[note_id] for note_id in order]
