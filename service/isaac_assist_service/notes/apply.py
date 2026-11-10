# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Changes: validation only. Kit /exec_sync performs the stage edit.

"""Validation gate for a sticky-note plan.

``apply_scene_edit`` refuses a plan that must not be sent to Kit. It does not
edit a stage and it does not mark a note applied. Stage edits go through
``kit_apply.apply_via_kit`` and the 6.2 extension.
"""

from __future__ import annotations

from typing import Any, Dict

_ALLOWED_OPS = {"set_attribute", "set_transform", "add_prim"}


def apply_scene_edit(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Accept a plan shape. The caller still has to edit USD before applied."""
    if not isinstance(plan, dict) or not plan.get("executable"):
        raise RuntimeError("refusing non-executable plan")
    op = plan.get("op")
    if op not in _ALLOWED_OPS:
        raise RuntimeError("refusing unknown edit op")
    return {
        "ok": False,
        "changed": False,
        "op": op,
        "prim_path": plan.get("prim_path") or "",
        "detail": "validation only; the stage was not edited",
    }
