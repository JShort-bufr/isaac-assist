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
except ImportError:  # pytest path-injects this directory as a top-level module
    from notes_client import NotesClient

NOTE_STATUSES = ("draft", "sent", "proposed", "confirmed", "applied", "rejected")


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
        {"kind": "label", "text": "Comment"},
        {"kind": "field", "text": "comment", "value": controller.comment},
        {"kind": "button", "text": "Add note"},
        {"kind": "button", "text": "Send"},
    ]
    for note in controller.notes:
        rows.append(
            {
                "kind": "note",
                "id": note.get("id"),
                "text": f"{note.get('prim_path', '')} [{note.get('status', '')}]",
                "marker": pinned_marker_text(note),
                "status": note.get("status"),
                "actions": ["Confirm", "Reject"],
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
    ):
        self.client = client
        self.stage_path = stage_path
        self.selection_reader = selection_reader or read_stage_selection
        self.prim_reader = prim_reader or read_prim_snapshot
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

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        return self.enabled

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def capture_selection(self) -> List[str]:
        self.selected_paths = list(self.selection_reader() or [])
        if not self.selected_paths:
            return []
        snapshot = self.prim_reader(self.selected_paths[0]) or {}
        self.prim_type = snapshot.get("prim_type") or self.prim_type
        if snapshot.get("key_attributes") is not None:
            self.key_attributes = dict(snapshot.get("key_attributes") or {})
        if "world_transform" in snapshot:
            self.world_transform = snapshot.get("world_transform")
        return list(self.selected_paths)

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
        note = self.client.create(self.draft_payload())
        self.notes.append(note)
        return note

    def refresh(self) -> List[Dict[str, Any]]:
        self.notes = self.client.list_notes(self.stage_path)
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
        result = self.client.send(self.stage_path, chosen)
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
        result = self.client.confirm(self.stage_path, note_id)
        self._replace(result.get("note"))
        return result

    def reject(self, note_id: str) -> Dict[str, Any]:
        result = self.client.reject(self.stage_path, note_id)
        self._replace(result.get("note"))
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
                ui.Button(row["text"], clicked_fn=controller.toggle)
            elif kind == "button":
                clicked = _wire(row, controller)
                ui.Button(row["text"], clicked_fn=clicked)
            elif kind == "note":
                with ui.HStack(spacing=4):
                    ui.Label(row["text"])
                    if row.get("marker"):
                        ui.Label(row["marker"])
                    note_id = row.get("id")
                    ui.Button("Confirm", clicked_fn=lambda note_id=note_id: controller.confirm(note_id))
                    ui.Button("Reject", clicked_fn=lambda note_id=note_id: controller.reject(note_id))
    return controller
