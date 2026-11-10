# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# One code_patch per distinct code and description inside a turn.

"""Drop duplicate code patches inside a single chat turn."""

from __future__ import annotations

from typing import Any, Dict, List


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split())


def patch_key(patch: Dict[str, Any]) -> tuple:
    return (_normalize(patch.get("code")), _normalize(patch.get("description")))


def same_code_patch(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return patch_key(left) == patch_key(right)


def dedupe_code_patches(patches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the first patch when later ones match after whitespace folding."""
    kept: List[Dict[str, Any]] = []
    seen = set()
    for patch in patches or []:
        if not isinstance(patch, dict):
            continue
        key = patch_key(patch)
        if key in seen:
            continue
        seen.add(key)
        kept.append(patch)
    return kept
