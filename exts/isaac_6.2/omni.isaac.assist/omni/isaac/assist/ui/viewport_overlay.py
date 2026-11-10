# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Viewport drag and pinned markers follow the Omniverse scene-gesture samples.

"""Sticky Note viewport overlay.

The drag follows ``omni.ui.scene`` ``DragGesture`` (began, changed, ended),
the same shape as the archived gestures sample and ``ovui`` scene manipulator.
Markers are labels anchored at each note's world translation, the same idea
as the ui-scene object-info sample. Kit imports stay optional.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

try:
    import omni.ui.scene as ui_scene
except Exception:
    ui_scene = None

try:
    from omni.kit.viewport.utility import get_active_viewport_window
except Exception:
    get_active_viewport_window = None

try:
    from .markers import mount_marker_overlay
    from .region_pick import normalize_drag
except ImportError:
    from markers import mount_marker_overlay
    from region_pick import normalize_drag

SizeReader = Callable[[], Tuple[float, float]]
BoundsReader = Callable[[], list]


def screen_point(payload: Any) -> Tuple[float, float]:
    """Mouse position from a gesture payload, a mapping, or an ``(x, y)`` pair."""
    if payload is None:
        raise ValueError("gesture payload is missing")
    mouse = getattr(payload, "mouse", None)
    if mouse is not None and hasattr(mouse, "x") and hasattr(mouse, "y"):
        return float(mouse.x), float(mouse.y)
    if isinstance(payload, dict):
        nested = payload.get("mouse")
        if isinstance(nested, dict) and "x" in nested and "y" in nested:
            return float(nested["x"]), float(nested["y"])
        if "x" in payload and "y" in payload:
            return float(payload["x"]), float(payload["y"])
    if isinstance(payload, (list, tuple)) and len(payload) >= 2:
        return float(payload[0]), float(payload[1])
    raise ValueError("gesture payload has no screen point")


def _payload_of(sender: Any) -> Any:
    payload = getattr(sender, "gesture_payload", None)
    if payload is not None:
        return payload
    return sender


class DragSession:
    """One screen-space rectangle. Phases match DragGesture."""

    def __init__(self) -> None:
        self.phase = "idle"
        self.origin: Optional[Tuple[float, float]] = None
        self.current: Optional[Tuple[float, float]] = None
        self.region: Optional[Dict[str, Any]] = None

    def began(self, x: float, y: float) -> None:
        self.phase = "began"
        self.origin = (float(x), float(y))
        self.current = self.origin
        self.region = None

    def changed(self, x: float, y: float) -> None:
        if self.phase not in ("began", "changed"):
            return
        self.phase = "changed"
        self.current = (float(x), float(y))

    def ended(
        self,
        x: float,
        y: float,
        viewport_width: float,
        viewport_height: float,
    ) -> Optional[Dict[str, Any]]:
        if self.origin is None or self.phase not in ("began", "changed"):
            return None
        self.current = (float(x), float(y))
        self.region = normalize_drag(
            self.origin[0],
            self.origin[1],
            self.current[0],
            self.current[1],
            viewport_width,
            viewport_height,
        )
        self.phase = "ended"
        return dict(self.region)

    def cancel(self) -> None:
        self.phase = "idle"
        self.origin = None
        self.current = None
        self.region = None


class StickyViewport:
    """Connects a drag gesture and the marker overlay to one sticky controller."""

    def __init__(
        self,
        controller: Any,
        size_reader: Optional[SizeReader] = None,
        bounds_reader: Optional[BoundsReader] = None,
    ) -> None:
        self.controller = controller
        self.drag = DragSession()
        self.size_reader = size_reader or (lambda: (1280.0, 720.0))
        self.bounds_reader = bounds_reader or (lambda: [])
        self.scene_module: Any = None

    def on_payload(self, payload: Any, phase: str) -> Optional[Dict[str, Any]]:
        x, y = screen_point(payload)
        if phase == "began":
            if not getattr(self.controller, "enabled", False):
                return None
            self.drag.began(x, y)
            return None
        if phase == "changed":
            self.drag.changed(x, y)
            return None
        if phase == "ended":
            width, height = self.size_reader()
            return self.finish(x, y, width, height)
        raise ValueError(f"unknown gesture phase {phase}")

    def on_sender(self, sender: Any, phase: str) -> Optional[Dict[str, Any]]:
        return self.on_payload(_payload_of(sender), phase)

    def finish(
        self,
        x: float,
        y: float,
        viewport_width: float,
        viewport_height: float,
    ) -> Optional[Dict[str, Any]]:
        region = self.drag.ended(x, y, viewport_width, viewport_height)
        if region is None:
            return None
        captured = self.controller.capture_drag(
            region["x"],
            region["y"],
            region["x"] + region["w"],
            region["y"] + region["h"],
            viewport_width,
            viewport_height,
            self.bounds_reader() or [],
        )
        self.invalidate()
        return captured

    def invalidate(self) -> list:
        if self.scene_module is None:
            return []
        return mount_marker_overlay(self.scene_module, self.controller.markers)


def build_drag_gesture(scene: Any, viewport: StickyViewport) -> Any:
    """A DragGesture subclass when that is possible, otherwise callback kwargs."""
    drag_cls = getattr(scene, "DragGesture", None)
    if not isinstance(drag_cls, type):
        if not callable(drag_cls):
            return None
        return drag_cls(
            on_began_fn=lambda sender: viewport.on_sender(sender, "began"),
            on_changed_fn=lambda sender: viewport.on_sender(sender, "changed"),
            on_ended_fn=lambda sender: viewport.on_sender(sender, "ended"),
        )

    class _StickyDrag(drag_cls):
        def on_began(self) -> None:
            viewport.on_sender(self, "began")

        def on_changed(self) -> None:
            viewport.on_sender(self, "changed")

        def on_ended(self) -> None:
            viewport.on_sender(self, "ended")

    try:
        return _StickyDrag()
    except Exception:
        return drag_cls(
            on_began_fn=lambda sender: viewport.on_sender(sender, "began"),
            on_changed_fn=lambda sender: viewport.on_sender(sender, "changed"),
            on_ended_fn=lambda sender: viewport.on_sender(sender, "ended"),
        )


def mount_drag_screen(scene: Any, viewport: StickyViewport) -> Any:
    """Full-viewport hit target. Returns the gesture, or None when scene has no Screen."""
    viewport.scene_module = scene
    screen = getattr(scene, "Screen", None)
    gesture = build_drag_gesture(scene, viewport)
    if not callable(screen) or gesture is None:
        return gesture
    screen(gesture=gesture)
    return gesture


def _window_size(window: Any) -> Tuple[float, float]:
    api = getattr(window, "viewport_api", None)
    resolution = getattr(api, "resolution", None)
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        return float(resolution[0]), float(resolution[1])
    width = getattr(window, "width", None)
    height = getattr(window, "height", None)
    if width and height:
        return float(width), float(height)
    return 1280.0, 720.0


def attach_sticky_scene(controller: Any) -> bool:
    """Overlay the active Kit viewport. Returns False when Kit scene APIs are absent."""
    if controller is None or ui_scene is None or get_active_viewport_window is None:
        return False
    try:
        window = get_active_viewport_window()
    except Exception:
        return False
    if window is None or not hasattr(window, "get_frame"):
        return False
    viewport = StickyViewport(controller, size_reader=lambda: _window_size(window))
    controller.viewport = viewport
    try:
        frame = window.get_frame("omni.isaac.assist.sticky")
        with frame:
            scene_view = ui_scene.SceneView()
            with scene_view.scene:
                mount_drag_screen(ui_scene, viewport)
                mount_marker_overlay(ui_scene, controller.markers)
        adder = getattr(getattr(window, "viewport_api", None), "add_scene_view", None)
        if callable(adder):
            adder(scene_view)
        controller.scene_view = scene_view
    except Exception:
        return False
    return True
