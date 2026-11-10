# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Forward a confirmed plan over the existing Kit /exec_sync bridge.

"""Dispatch one confirmed plan to the open Kit stage.

The service does not edit USD itself. It reuses ``kit_tools.exec_sync``, which
posts to the extension's existing Kit RPC server. The code that runs in Kit
calls ``apply_plan_on_open_stage``. The note may become ``applied`` only when
that call reports ``changed: true``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ..chat.tools import kit_tools

MARKER = "ISAAC_ASSIST_NOTE_RESULT"


def build_kit_exec_code(plan: Dict[str, Any]) -> str:
    """Python that Kit's main-thread exec tick will run."""
    encoded = json.dumps(plan, separators=(",", ":"))
    literal = json.dumps(encoded)
    marker = json.dumps(MARKER)
    return (
        "import json\n"
        "from omni.isaac.assist.executor.note_apply import apply_plan_on_open_stage\n"
        f"_plan = json.loads({literal})\n"
        "_result = apply_plan_on_open_stage(_plan)\n"
        f"print({marker} + ' ' + json.dumps(_result))\n"
    )


def parse_kit_exec_output(output: str) -> Optional[Dict[str, Any]]:
    if not output:
        return None
    prefix = MARKER + " "
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            parsed = json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def apply_via_kit(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return whether Kit actually changed the open stage."""
    alive = await kit_tools.is_kit_rpc_alive()
    if not alive:
        return {
            "applied": False,
            "kit_connected": False,
            "changed": False,
            "detail": "Kit is not connected; the stage was not edited",
        }
    result = await kit_tools.exec_sync(build_kit_exec_code(plan), timeout=30)
    if not result.get("success"):
        return {
            "applied": False,
            "kit_connected": True,
            "changed": False,
            "detail": "Kit did not change the stage",
        }
    parsed = parse_kit_exec_output(result.get("output") or "")
    if not parsed or not parsed.get("ok") or not parsed.get("changed"):
        detail = (parsed or {}).get("detail") or "Kit did not change the stage"
        return {
            "applied": False,
            "kit_connected": True,
            "changed": False,
            "detail": str(detail),
        }
    return {
        "applied": True,
        "kit_connected": True,
        "changed": True,
        "detail": str(parsed.get("detail") or "stage updated"),
    }
