# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# One proposed edit per note. Proposals are not applied here.

"""Turn a sticky note into one structured edit proposal.

The provider chain is asked for a plan. An offline reply becomes a
non-executable proposal so a later confirm cannot edit the stage.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ..providers.chain import OFFLINE_TEXT, FallbackChainProvider

_OPS = {"set_attribute", "set_transform", "add_prim"}
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_plan(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    candidates = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for blob in candidates:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("op") in _OPS:
            return parsed
    return None


async def complete_with_chain(messages, context=None):
    provider = FallbackChainProvider()
    return await provider.complete(messages, context or {})


def _offline_proposal(note: Dict[str, Any], summary: str) -> Dict[str, Any]:
    return {
        "op": "none",
        "prim_path": note.get("prim_path") or "",
        "payload": {},
        "executable": False,
        "summary": summary or OFFLINE_TEXT,
    }


async def propose_for_note(note: Dict[str, Any]) -> Dict[str, Any]:
    """Return one proposal. Does not apply it."""
    prompt = (
        "Propose exactly one scene edit as JSON with keys op, prim_path, payload. "
        "op must be set_attribute, set_transform, or add_prim. "
        f"prim_path={note.get('prim_path', '')} "
        f"prim_type={note.get('prim_type', '')} "
        f"comment={note.get('comment', '')}"
    )
    response = await complete_with_chain(
        [{"role": "user", "content": prompt}],
        {},
    )
    text = getattr(response, "text", "") or ""
    if "assistant is offline" in text.lower():
        return _offline_proposal(note, text)

    parsed = _extract_json_plan(text)
    if parsed is not None:
        parsed["executable"] = True
        parsed.setdefault("prim_path", note.get("prim_path") or "")
        parsed.setdefault("payload", {})
        parsed.setdefault(
            "summary",
            f"Proposed {parsed.get('op')} on {parsed.get('prim_path')}",
        )
        return parsed

    tool_calls = getattr(response, "tool_calls", None) or []
    if tool_calls:
        function = (tool_calls[0].get("function") or {})
        return {
            "op": "set_attribute",
            "prim_path": note.get("prim_path") or "",
            "payload": {
                "tool": function.get("name", ""),
                "arguments": function.get("arguments", ""),
            },
            "executable": True,
            "summary": f"Proposed tool call {function.get('name', '')} without executing it",
        }

    return {
        "op": "set_attribute",
        "prim_path": note.get("prim_path") or "",
        "payload": {
            "comment": note.get("comment") or "",
            "prim_type": note.get("prim_type") or "",
        },
        "executable": True,
        "summary": f"Proposed set_attribute on {note.get('prim_path') or ''}",
    }
