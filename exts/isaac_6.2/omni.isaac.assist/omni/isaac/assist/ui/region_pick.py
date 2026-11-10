# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Drag-rectangle pick and cropped viewport metadata. No Kit required.

"""Screen-space region helpers for Sticky Note mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def normalize_drag(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    viewport_width: float,
    viewport_height: float,
) -> Dict[str, Any]:
    """Axis-aligned drag rect plus the viewport size it was drawn in."""
    x = min(float(x0), float(x1))
    y = min(float(y0), float(y1))
    width = abs(float(x1) - float(x0))
    height = abs(float(y1) - float(y0))
    return {
        "x": x,
        "y": y,
        "w": width,
        "h": height,
        "width": width,
        "height": height,
        "viewport": {"width": viewport_width, "height": viewport_height},
    }


def _rect(item: Dict[str, Any]) -> Optional[tuple]:
    if "x" not in item or "y" not in item:
        return None
    width = item.get("w", item.get("width"))
    height = item.get("h", item.get("height"))
    if width is None or height is None:
        return None
    return (float(item["x"]), float(item["y"]), float(width), float(height))


def intersects(region: Dict[str, Any], bounds: Dict[str, Any]) -> bool:
    left = _rect(region)
    right = _rect(bounds)
    if left is None or right is None:
        return False
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def prims_in_region(prim_bounds: Sequence[Dict[str, Any]], region: Dict[str, Any]) -> List[str]:
    hits = []
    for item in prim_bounds or []:
        path = item.get("prim_path") or ""
        if path and intersects(region, item):
            hits.append(str(path))
    return hits


def pick_prims(
    prim_bounds: Sequence[Dict[str, Any]],
    region: Dict[str, Any],
    fallback_paths: Sequence[str],
) -> List[str]:
    """Prims whose screen bounds hit the drag. Otherwise one selected prim."""
    hits = prims_in_region(prim_bounds, region)
    if hits:
        return hits
    for path in fallback_paths or []:
        if path:
            return [str(path)]
    return []


def crop_box(image_width: int, image_height: int, region: Dict[str, Any]) -> tuple:
    """Pixel box of ``region`` clamped to an image of the viewport size.

    ``region`` coordinates are in viewport pixels. They are scaled when the
    captured image size differs from ``region["viewport"]``.
    """
    viewport = region.get("viewport") if isinstance(region.get("viewport"), dict) else {}
    view_w = float(viewport.get("width") or image_width or 1)
    view_h = float(viewport.get("height") or image_height or 1)
    scale_x = float(image_width) / view_w if view_w else 1.0
    scale_y = float(image_height) / view_h if view_h else 1.0
    x = float(region.get("x") or 0) * scale_x
    y = float(region.get("y") or 0) * scale_y
    w = float(region.get("w", region.get("width")) or 0) * scale_x
    h = float(region.get("h", region.get("height")) or 0) * scale_y
    left = max(0, min(int(x), int(image_width)))
    top = max(0, min(int(y), int(image_height)))
    right = max(left, min(int(round(x + w)), int(image_width)))
    bottom = max(top, min(int(round(y + h)), int(image_height)))
    return (left, top, right, bottom)


def write_crop_bytes(path: str, payload: bytes) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return str(destination)
