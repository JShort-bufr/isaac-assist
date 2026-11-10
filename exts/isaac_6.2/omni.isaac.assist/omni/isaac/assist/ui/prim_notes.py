# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Read and write bufrai:stickyNotes on a prim. Refuses a read-only prim.

"""Prim customData helpers for sticky notes."""

from __future__ import annotations

from typing import Any, Dict

CUSTOM_KEY = "bufrai:stickyNotes"


def read_notes(prim: Any) -> Dict[str, Any]:
    if prim is None or not hasattr(prim, "GetCustomData"):
        return {}
    custom = prim.GetCustomData() or {}
    notes = custom.get(CUSTOM_KEY) or {}
    if not isinstance(notes, dict):
        return {}
    return dict(notes)


def apply_custom_data(stage: Any, payload: Dict[str, Any]) -> bool:
    """Write each prim's note dictionary. Skips a missing or read-only prim."""
    if stage is None or not payload or not hasattr(stage, "GetPrimAtPath"):
        return False
    wrote = False
    for prim_path, entries in payload.items():
        if not isinstance(entries, dict):
            continue
        prim = stage.GetPrimAtPath(prim_path)
        wrote = write_notes(prim, entries) or wrote
    return wrote


def write_notes(prim: Any, entries: Dict[str, Any]) -> bool:
    """Write the note dictionary. A read-only prim is left unchanged."""
    if prim is None or not hasattr(prim, "SetCustomData"):
        return False
    if getattr(prim, "read_only", False):
        return False
    custom = dict(prim.GetCustomData() or {}) if hasattr(prim, "GetCustomData") else {}
    custom[CUSTOM_KEY] = dict(entries)
    prim.SetCustomData(custom)
    return True
