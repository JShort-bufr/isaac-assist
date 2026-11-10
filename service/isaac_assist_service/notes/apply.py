# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# The only scene-edit gate. Confirm is the sole caller.

"""Scene-edit gate.

``apply_scene_edit`` is the only function that accepts a sticky-note plan.
It does not open a USD stage. Live Kit application of the plan is UNVERIFIED
and is left for the Legion smoke. Offline and unconfirmed plans must never
reach this function.
"""

from __future__ import annotations

from typing import Any, Dict

_ALLOWED_OPS = {"set_attribute", "set_transform", "add_prim"}


def apply_scene_edit(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Record one confirmed executable plan. Refuses everything else."""
    if not isinstance(plan, dict) or not plan.get("executable"):
        raise RuntimeError("refusing non-executable plan")
    op = plan.get("op")
    if op not in _ALLOWED_OPS:
        raise RuntimeError("refusing unknown edit op")
    return {
        "ok": True,
        "op": op,
        "prim_path": plan.get("prim_path") or "",
    }
