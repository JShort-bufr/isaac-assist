# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Pinned marker anchors. Drawing uses omni.ui.scene when Kit provides it.

"""World-space anchors for sticky-note markers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

Anchor = Tuple[float, float, float]

STATUS_COLORS = {
    "draft": (0.70, 0.70, 0.70, 1.0),
    "sent": (0.70, 0.70, 0.70, 1.0),
    "proposed": (1.0, 0.66, 0.0, 1.0),
    "confirmed": (0.25, 0.48, 1.0, 1.0),
    "applied": (0.20, 0.80, 0.35, 1.0),
    "rejected": (0.90, 0.22, 0.22, 1.0),
    "reverted": (0.55, 0.55, 0.55, 1.0),
}


def marker_color(status: Optional[str]) -> Tuple[float, float, float, float]:
    return STATUS_COLORS.get(status or "", (0.70, 0.70, 0.70, 1.0))


def marker_anchor(note: Dict[str, Any]) -> Optional[Anchor]:
    """Translation of the note's world transform.

    A 4x4 matrix uses USD's row-vector layout: translation is the fourth row.
    """
    transform = note.get("world_transform") or {}
    if not isinstance(transform, dict):
        return None
    translate = transform.get("translate")
    if isinstance(translate, (list, tuple)) and len(translate) >= 3:
        return (float(translate[0]), float(translate[1]), float(translate[2]))
    matrix = transform.get("matrix")
    if (
        isinstance(matrix, (list, tuple))
        and len(matrix) == 4
        and isinstance(matrix[3], (list, tuple))
        and len(matrix[3]) >= 3
    ):
        row = matrix[3]
        return (float(row[0]), float(row[1]), float(row[2]))
    return None


class MarkerOverlay:
    """Anchors that follow each note's prim. ``enabled`` hides every marker."""

    def __init__(self) -> None:
        self.enabled = True
        self._items: List[Dict[str, Any]] = []

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        return self.enabled

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def update(
        self,
        notes: Sequence[Dict[str, Any]],
        transforms_by_prim: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        overrides = transforms_by_prim or {}
        items = []
        for note in notes or []:
            prim_path = note.get("prim_path") or ""
            if not prim_path:
                continue
            current = dict(note)
            if prim_path in overrides:
                current["world_transform"] = overrides[prim_path]
            anchor = marker_anchor(current)
            items.append(
                {
                    "id": current.get("id"),
                    "prim_path": prim_path,
                    "status": current.get("status"),
                    "anchor": anchor,
                    "color": marker_color(current.get("status")),
                }
            )
        self._items = items
        return self.scene_items()

    def scene_items(self) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        return [item for item in self._items if item.get("anchor") is not None]


def mount_marker_overlay(scene: Any, overlay: MarkerOverlay) -> List[Dict[str, Any]]:
    """Draw one label per visible anchor when ``scene`` looks like omni.ui.scene."""
    items = overlay.scene_items()
    if scene is None:
        return items
    label = getattr(scene, "Label", None)
    for item in items:
        anchor = item["anchor"]
        text = f"PIN {item['prim_path']}"
        if callable(label):
            try:
                label(text, position=anchor, color=item["color"])
            except TypeError:
                label(text)
        item["text"] = text
    return items
