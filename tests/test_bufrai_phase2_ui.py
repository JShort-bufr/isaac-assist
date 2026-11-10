# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Drag-region pick, marker anchors, and batch review in the sticky panel."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.l0

UI_DIR = (
    Path(__file__).resolve().parent.parent
    / "exts"
    / "isaac_6.2"
    / "omni.isaac.assist"
    / "omni"
    / "isaac"
    / "assist"
    / "ui"
)
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

import markers  # noqa: E402
import prim_notes  # noqa: E402
import region_pick  # noqa: E402
import sticky_notes  # noqa: E402


class _Client:
    def __init__(self):
        self.created = []

    def create(self, payload):
        note = {
            "id": "n1",
            "status": "draft",
            "prim_path": payload.get("prim_path", ""),
            "crop_path": payload.get("crop_path") or "/tmp/scene.usd.notes/n1.png",
            "region": payload.get("region"),
            "comment": payload.get("comment", ""),
        }
        self.created.append(payload)
        return note

    def send(self, stage_path, ids, **flags):
        return {"notes": []}

    def review(self, stage_path, action, ids, **flags):
        results = []
        for note_id in ids:
            if note_id == "bad":
                results.append(
                    {
                        "id": note_id,
                        "ok": False,
                        "applied": False,
                        "status": "rejected",
                        "detail": "type mismatch: xformOp:scale expects double3, got str",
                        "note": {"id": note_id, "status": "rejected", "prim_path": "/World/Bad", "error": "type mismatch"},
                    }
                )
            else:
                results.append(
                    {
                        "id": note_id,
                        "ok": True,
                        "applied": True,
                        "status": "applied",
                        "detail": "set_attribute",
                        "note": {
                            "id": note_id,
                            "status": "applied",
                            "prim_path": "/World/Cube",
                            "proposal": {"summary": "scale it"},
                        },
                    }
                )
        return {"results": results, "custom_data_allowed": False}


def test_drag_region_picks_hits_and_falls_back_to_one_prim(tmp_path):
    region = region_pick.normalize_drag(30, 10, 10, 40, 800, 600)
    assert region["x"] == 10
    assert region["y"] == 10
    assert region["w"] == 20
    assert region["h"] == 30
    assert region["viewport"] == {"width": 800, "height": 600}
    bounds = [
        {"prim_path": "/World/Cube", "x": 12, "y": 12, "w": 8, "h": 8},
        {"prim_path": "/World/Far", "x": 400, "y": 400, "width": 10, "height": 10},
    ]
    assert region_pick.pick_prims(bounds, region, ["/World/Selected"]) == ["/World/Cube"]
    assert region_pick.pick_prims([], region, ["/World/Selected", "/World/Other"]) == ["/World/Selected"]
    assert region_pick.crop_box(800, 600, region) == (10, 10, 30, 40)
    assert region_pick.crop_box(400, 300, region) == (5, 5, 15, 20)

    client = _Client()
    controller = sticky_notes.StickyNoteController(
        client,
        stage_path=str(tmp_path / "scene.usd"),
        selection_reader=lambda: ["/World/Selected"],
        prim_reader=lambda path: {"prim_type": "Cube", "world_transform": {"translate": [1, 2, 3]}},
    )
    controller.toggle()
    captured = controller.capture_drag(30, 10, 10, 40, 800, 600, bounds, crop_bytes=b"png-bytes")
    assert captured["prim_paths"] == ["/World/Cube"]
    controller.comment = "look here"
    note = controller.add_draft()
    destination = Path(note["crop_path"])
    assert destination.read_bytes() == b"png-bytes"
    assert client.created[0]["region"]["w"] == 20
    assert client.created[0]["prim_path"] == "/World/Cube"


def test_marker_anchor_follows_the_prim_and_status_color():
    matrix = [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [4, 5, 6, 1],
    ]
    note = {"id": "n1", "prim_path": "/World/Cube", "status": "proposed", "world_transform": {"matrix": matrix}}
    assert markers.marker_anchor(note) == (4.0, 5.0, 6.0)
    assert markers.marker_color("applied")[1] > markers.marker_color("rejected")[1]
    overlay = markers.MarkerOverlay()
    shown = overlay.update([note])
    assert shown[0]["anchor"] == (4.0, 5.0, 6.0)
    assert shown[0]["color"] == markers.marker_color("proposed")
    moved = overlay.update([note], {"/World/Cube": {"translate": [9, 8, 7]}})
    assert moved[0]["anchor"] == (9.0, 8.0, 7.0)
    overlay.set_enabled(False)
    assert overlay.scene_items() == []
    overlay.set_enabled(True)
    drawn = []

    class _Scene:
        def Label(self, text, position=None, color=None):
            drawn.append((text, position, color))

    markers.mount_marker_overlay(_Scene(), overlay)
    assert drawn[0][0] == "PIN /World/Cube"
    assert drawn[0][1] == (9.0, 8.0, 7.0)


def test_batch_confirm_keeps_a_result_per_note_and_custom_data_write():
    client = _Client()
    prims = {}

    class _Prim:
        def __init__(self, read_only=False):
            self.read_only = read_only
            self.custom = {}

        def GetCustomData(self):
            return dict(self.custom)

        def SetCustomData(self, custom):
            self.custom = dict(custom)

    class _Stage:
        def __init__(self):
            self.prims = {"/World/Cube": _Prim(), "/World/Locked": _Prim(read_only=True)}

        def GetPrimAtPath(self, path):
            return self.prims.get(path)

    stage = _Stage()
    controller = sticky_notes.StickyNoteController(client, stage_path="/tmp/scene.usd", stage_getter=lambda: stage)
    controller.toggle()
    controller.notes = [
        {"id": "good", "status": "proposed", "prim_path": "/World/Cube", "proposal": {"summary": "scale it"}},
        {"id": "bad", "status": "proposed", "prim_path": "/World/Bad", "proposal": {"summary": "bad scale"}},
        {"id": "draft", "status": "draft", "prim_path": "/World/Other"},
    ]
    result = controller.confirm_all()
    assert [item["id"] for item in result["results"]] == ["good", "bad"]
    assert controller.notes[0]["status"] == "applied"
    assert controller.notes[1]["status"] == "rejected"
    assert controller.notes[2]["status"] == "draft"
    rows = {row["id"]: row for row in sticky_notes.sticky_panel_rows(controller) if row["kind"] == "note"}
    assert rows["good"]["summary"] == "scale it"
    assert rows["good"]["result"] == "set_attribute"
    assert "Undo" in rows["good"]["actions"]
    assert "type mismatch" in rows["bad"]["result"]
    assert controller.results["bad"]["applied"] is False

    payload = {"/World/Cube": {"good": {"comment": "hi", "status": "applied", "created_at": "t"}}}
    assert prim_notes.apply_custom_data(stage, payload) is True
    assert prim_notes.read_notes(stage.prims["/World/Cube"])["good"]["status"] == "applied"
    locked = {"/World/Locked": {"x": {"comment": "no", "status": "draft", "created_at": "t"}}}
    assert prim_notes.write_notes(stage.prims["/World/Locked"], locked["/World/Locked"]) is False
    assert prim_notes.read_notes(stage.prims["/World/Locked"]) == {}
