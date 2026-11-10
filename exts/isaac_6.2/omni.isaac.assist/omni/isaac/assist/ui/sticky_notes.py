# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Sticky Note MVP panel. omni.* imports are optional so pytest can mock them.

"""Sticky Note mode for the Isaac Sim 6.2 extension.

The panel is a toggle, a selection or viewport-region capture, a comment
field, a list of notes with status, a pinned marker label, Send, and
per-note Confirm / Reject. Live viewport drawing and USD writes are
UNVERIFIED; this module only talks to the service API.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

try:
    import omni.usd as omni_usd
except Exception:
    omni_usd = None

try:
    from .notes_client import NotesClient
    from .markers import MarkerOverlay, marker_color
    from .prim_notes import apply_custom_data, write_notes
    from .region_pick import normalize_drag, pick_prims, write_crop_bytes
except ImportError:  # pytest path-injects this directory as a top-level module
    from notes_client import NotesClient
    from markers import MarkerOverlay, marker_color
    from prim_notes import apply_custom_data, write_notes
    from region_pick import normalize_drag, pick_prims, write_crop_bytes

NOTE_STATUSES = (
    "draft",
    "sent",
    "proposed",
    "confirmed",
    "applied",
    "rejected",
    "reverted",
)


def read_stage_selection() -> List[str]:
    """Selected prim paths from ``omni.usd``, or an empty list outside Kit."""
    if omni_usd is None:
        return []
    try:
        context = omni_usd.get_context()
        paths = context.get_selection().get_selected_prim_paths()
    except Exception:
        return []
    return [str(path) for path in (paths or [])]


def read_prim_snapshot(prim_path: str) -> Dict[str, Any]:
    """Best-effort prim type and optional attributes. Transform math is UNVERIFIED."""
    if omni_usd is None or not prim_path:
        return {}
    try:
        stage = omni_usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(prim_path)
    except Exception:
        return {}
    if prim is None:
        return {}
    valid = getattr(prim, "IsValid", lambda: True)
    if callable(valid) and not valid():
        return {}
    type_name = ""
    get_type = getattr(prim, "GetTypeName", None)
    if callable(get_type):
        type_name = str(get_type() or "")
    attributes: Dict[str, Any] = {}
    get_attrs = getattr(prim, "get_key_attributes", None)
    if callable(get_attrs):
        attributes = dict(get_attrs() or {})
    return {
        "prim_path": str(prim_path),
        "prim_type": type_name,
        "key_attributes": attributes,
        "world_transform": getattr(prim, "world_transform", None),
    }


def pinned_marker_text(note: Dict[str, Any]) -> str:
    path = note.get("prim_path") or ""
    if not path:
        return ""
    return f"PIN {path}"


def sticky_panel_rows(controller: "StickyNoteController") -> List[Dict[str, Any]]:
    """Pure view of the panel. The Kit builder and the tests both use it."""
    rows: List[Dict[str, Any]] = [
        {"kind": "label", "text": "Sticky Note"},
        {
            "kind": "toggle",
            "text": "Sticky Note: on" if controller.enabled else "Sticky Note: off",
        },
        {"kind": "button", "text": "Use selection"},
        {"kind": "button", "text": "Mark region"},
        {
            "kind": "toggle",
            "text": "Markers: on" if controller.markers.enabled else "Markers: off",
        },
        {"kind": "label", "text": "Comment"},
        {"kind": "field", "text": "comment", "value": controller.comment},
        {"kind": "button", "text": "Add note"},
        {"kind": "button", "text": "Send"},
        {"kind": "button", "text": "Confirm all"},
    ]
    for note in controller.notes:
        actions = ["Confirm", "Reject"]
        if note.get("status") == "applied":
            actions.append("Undo")
        outcome = controller.results.get(note.get("id")) or {}
        proposal = note.get("proposal") or {}
        rows.append(
            {
                "kind": "note",
                "id": note.get("id"),
                "text": f"{note.get('prim_path', '')} [{note.get('status', '')}]",
                "marker": pinned_marker_text(note),
                "marker_color": marker_color(note.get("status")),
                "summary": proposal.get("summary") or "",
                "result": outcome.get("detail") or note.get("error") or "",
                "status": note.get("status"),
                "actions": actions,
            }
        )
    return rows


class StickyNoteController:
    """UI state for Sticky Note mode. The client performs the HTTP calls."""

    def __init__(
        self,
        client: NotesClient,
        stage_path: str = "",
        selection_reader: Optional[Callable[[], List[str]]] = None,
        prim_reader: Optional[Callable[[str], Dict[str, Any]]] = None,
        stage_getter: Optional[Callable[[], Any]] = None,
    ):
        self.client = client
        self.stage_path = stage_path
        self.selection_reader = selection_reader or read_stage_selection
        self.prim_reader = prim_reader or read_prim_snapshot
        self.stage_getter = stage_getter
        self.enabled = False
        self.comment = ""
        self.region = None
        self.pending_region = None
        self.notes: List[Dict[str, Any]] = []
        self.selected_paths: List[str] = []
        self.prim_type = ""
        self.key_attributes: Dict[str, Any] = {}
        self.world_transform = None
        self.crop_path = None
        self.markers = MarkerOverlay()
        self.results: Dict[str, Any] = {}
        self.transform_overrides: Dict[str, Any] = {}
        self.pending_crop: Optional[bytes] = None
        self.read_only = False
        self.session_layer = ""
        self.session_layer_writable = False
        self.custom_data_writer = write_notes

    def _stage_flags(self) -> Dict[str, Any]:
        flags: Dict[str, Any] = {}
        if self.read_only:
            flags["read_only"] = True
        if self.session_layer:
            flags["session_layer"] = self.session_layer
        if self.session_layer_writable:
            flags["session_layer_writable"] = True
        return flags

    def _mirror_custom_data(self, result: Optional[Dict[str, Any]]) -> bool:
        if not result or not result.get("custom_data_allowed") or not result.get("custom_data"):
            return False
        if self.stage_getter is None:
            return False
        try:
            stage = self.stage_getter()
        except Exception:
            return False
        return apply_custom_data(stage, result["custom_data"])

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        return self.enabled

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def _apply_snapshot(self, prim_path: str) -> None:
        snapshot = self.prim_reader(prim_path) or {}
        self.prim_type = snapshot.get("prim_type") or self.prim_type
        if snapshot.get("key_attributes") is not None:
            self.key_attributes = dict(snapshot.get("key_attributes") or {})
        if "world_transform" in snapshot:
            self.world_transform = snapshot.get("world_transform")

    def capture_selection(self) -> List[str]:
        self.selected_paths = list(self.selection_reader() or [])
        if not self.selected_paths:
            return []
        self._apply_snapshot(self.selected_paths[0])
        return list(self.selected_paths)

    def capture_drag(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        viewport_width: float,
        viewport_height: float,
        prim_bounds: Optional[List[Dict[str, Any]]] = None,
        crop_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Store a drag rect, the prims inside it, and optional cropped PNG bytes."""
        self.region = normalize_drag(x0, y0, x1, y1, viewport_width, viewport_height)
        fallback = list(self.selection_reader() or [])
        picked = pick_prims(prim_bounds or [], self.region, fallback)
        self.selected_paths = picked
        if picked:
            self._apply_snapshot(picked[0])
        self.pending_crop = crop_bytes
        return {"region": dict(self.region), "prim_paths": list(picked)}

    def set_prim_transform(self, prim_path: str, world_transform: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.transform_overrides[prim_path] = world_transform
        if self.selected_paths and self.selected_paths[0] == prim_path:
            self.world_transform = world_transform
        return self.markers.update(self.notes, self.transform_overrides)

    def toggle_markers(self) -> bool:
        self.markers.toggle()
        return self.markers.enabled

    def mark_region(self) -> Dict[str, Any]:
        if self.pending_region is not None:
            self.region = dict(self.pending_region)
        elif self.region is None:
            self.region = {"x": 0, "y": 0, "width": 0, "height": 0}
        return dict(self.region)

    def draft_payload(self) -> Dict[str, Any]:
        prim_path = self.selected_paths[0] if self.selected_paths else ""
        return {
            "stage_path": self.stage_path,
            "prim_path": prim_path,
            "prim_type": self.prim_type,
            "key_attributes": dict(self.key_attributes),
            "world_transform": self.world_transform,
            "region": self.region,
            "crop_path": self.crop_path,
            "comment": self.comment,
        }

    def add_draft(self) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Sticky Note mode is off")
        payload = self.draft_payload()
        payload.update(self._stage_flags())
        note = self.client.create(payload)
        if self.pending_crop and note.get("crop_path"):
            write_crop_bytes(note["crop_path"], self.pending_crop)
            self.pending_crop = None
        self.notes.append(note)
        self.markers.update(self.notes, self.transform_overrides)
        return note

    def refresh(self) -> List[Dict[str, Any]]:
        self.notes = self.client.list_notes(self.stage_path)
        self.markers.update(self.notes, self.transform_overrides)
        return list(self.notes)

    def send_batch(self, ids: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Sticky Note mode is off")
        chosen = ids
        if chosen is None:
            chosen = [
                note["id"]
                for note in self.notes
                if note.get("status") in ("draft", "sent")
            ]
        result = self.client.send(self.stage_path, chosen, **self._stage_flags())
        returned = list(result.get("notes") or [])
        by_id = {note.get("id"): note for note in returned}
        if by_id:
            merged = []
            seen = set()
            for note in self.notes:
                note_id = note.get("id")
                merged.append(by_id.get(note_id, note))
                seen.add(note_id)
            for note in returned:
                if note.get("id") not in seen:
                    merged.append(note)
            self.notes = merged
        return result

    def confirm(self, note_id: str) -> Dict[str, Any]:
        result = self.client.confirm(self.stage_path, note_id, **self._stage_flags())
        self._replace(result.get("note"))
        self.results[note_id] = result
        self._mirror_custom_data(result)
        self.markers.update(self.notes, self.transform_overrides)
        return result

    def reject(self, note_id: str) -> Dict[str, Any]:
        result = self.client.reject(self.stage_path, note_id, **self._stage_flags())
        self._replace(result.get("note"))
        self.results[note_id] = result
        self._mirror_custom_data(result)
        self.markers.update(self.notes, self.transform_overrides)
        return result

    def undo(self, note_id: str) -> Dict[str, Any]:
        result = self.client.undo(self.stage_path, note_id, **self._stage_flags())
        self._replace(result.get("note"))
        self.results[note_id] = result
        self.markers.update(self.notes, self.transform_overrides)
        return result

    def confirm_all(self) -> Dict[str, Any]:
        """Confirm every proposed note. One click, then one result per note."""
        if not self.enabled:
            raise RuntimeError("Sticky Note mode is off")
        ids = [note["id"] for note in self.notes if note.get("status") == "proposed"]
        return self.review("confirm", ids)

    def review(self, action: str, ids: List[str]) -> Dict[str, Any]:
        result = self.client.review(self.stage_path, action, ids, **self._stage_flags())
        for item in result.get("results") or []:
            note_id = item.get("id")
            if note_id:
                self.results[note_id] = item
            self._replace(item.get("note"))
        self._mirror_custom_data(result)
        self.markers.update(self.notes, self.transform_overrides)
        return result

    def _replace(self, note: Optional[Dict[str, Any]]) -> None:
        if not note:
            return
        for index, current in enumerate(self.notes):
            if current.get("id") == note.get("id"):
                self.notes[index] = note
                return
        self.notes.append(note)


class _CommentModel:
    """Small stand-in when ``omni.ui.SimpleStringModel`` is absent."""

    def __init__(self, controller: StickyNoteController):
        self._controller = controller

    def get_value_as_string(self) -> str:
        return self._controller.comment

    def set_value(self, value: str) -> None:
        self._controller.comment = "" if value is None else str(value)


def _wire(row: Dict[str, Any], controller: StickyNoteController):
    text = row.get("text")
    if isinstance(text, str) and text.startswith("Markers"):
        return controller.toggle_markers
    if row["kind"] == "toggle":
        return controller.toggle
    if text == "Use selection":
        return controller.capture_selection
    if text == "Mark region":
        return controller.mark_region
    if text == "Add note":
        return controller.add_draft
    if text == "Send":
        return controller.send_batch
    if text == "Confirm all":
        return controller.confirm_all
    return None


def mount_sticky_note_panel(
    ui,
    service_base: str = "http://127.0.0.1:8000",
    controller: Optional[StickyNoteController] = None,
    stage_path: str = "",
) -> StickyNoteController:
    """Build the panel on an ``omni.ui``-like module and return the controller."""
    if controller is None:
        controller = StickyNoteController(NotesClient(service_base), stage_path=stage_path)
    comment_model = _CommentModel(controller)
    simple = getattr(ui, "SimpleStringModel", None)
    if simple is not None:
        try:
            comment_model = simple()
        except Exception:
            comment_model = _CommentModel(controller)

    with ui.VStack(spacing=4):
        for row in sticky_panel_rows(controller):
            kind = row["kind"]
            if kind == "label":
                ui.Label(row["text"])
            elif kind == "field":
                ui.StringField(model=comment_model)
            elif kind == "toggle":
                ui.Button(row["text"], clicked_fn=_wire(row, controller))
            elif kind == "button":
                clicked = _wire(row, controller)
                ui.Button(row["text"], clicked_fn=clicked)
            elif kind == "note":
                with ui.HStack(spacing=4):
                    ui.Label(row["text"])
                    if row.get("marker"):
                        ui.Label(row["marker"])
                    note_id = row.get("id")
                    if "Confirm" in row.get("actions", []):
                        ui.Button("Confirm", clicked_fn=lambda note_id=note_id: controller.confirm(note_id))
                    if "Reject" in row.get("actions", []):
                        ui.Button("Reject", clicked_fn=lambda note_id=note_id: controller.reject(note_id))
                    if "Undo" in row.get("actions", []):
                        ui.Button("Undo", clicked_fn=lambda note_id=note_id: controller.undo(note_id))
    return controller
