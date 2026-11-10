# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Isaac Sim 6.2 profile, extension copy, and import-safe Sticky Note UI."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.l0

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "exts" / "isaac_6.2" / "omni.isaac.assist" / "omni" / "isaac" / "assist" / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

import sticky_notes  # noqa: E402
from notes_client import NotesClient  # noqa: E402


class RecordingUI:
    def __init__(self):
        self.events = []

    class _Frame:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def VStack(self, **kwargs):
        self.events.append(("VStack", kwargs))
        return self._Frame()

    def HStack(self, **kwargs):
        self.events.append(("HStack", kwargs))
        return self._Frame()

    def Label(self, text, **kwargs):
        self.events.append(("Label", text))
        return text

    def Button(self, text, **kwargs):
        self.events.append(("Button", text, kwargs.get("clicked_fn")))
        return text

    def StringField(self, **kwargs):
        self.events.append(("StringField", kwargs.get("model")))
        return kwargs.get("model")


class FakeNotes:
    def __init__(self):
        self.created = []
        self.sent = []
        self.confirmed = []
        self.rejected = []

    def create(self, payload):
        note = {
            "id": f"n{len(self.created) + 1}",
            "status": "draft",
            "prim_path": payload["prim_path"],
            "comment": payload["comment"],
        }
        self.created.append(payload)
        return note

    def list_notes(self, stage_path):
        return []

    def send(self, stage_path, ids):
        self.sent.append(list(ids))
        return {"notes": [{"id": ids[0], "status": "proposed", "prim_path": "/World/Cube"}]}

    def confirm(self, stage_path, note_id):
        self.confirmed.append(note_id)
        return {"note": {"id": note_id, "status": "applied", "prim_path": "/World/Cube"}, "applied": True}

    def reject(self, stage_path, note_id):
        self.rejected.append(note_id)
        return {"note": {"id": note_id, "status": "rejected", "prim_path": "/World/Cube"}, "applied": False}


def test_runtime_profile_aliases_and_env(monkeypatch):
    from service.isaac_assist_service.runtime_profiles import (
        ISAAC_SIM_60,
        ISAAC_SIM_62,
        get_runtime_profile,
        metadata_matches_profile,
        prompt_runtime_rules,
        runtime_scope_summary,
    )

    assert get_runtime_profile("isaacsim-6.2").key == "isaacsim-6.2"
    assert get_runtime_profile("6.2").isaac_sim_version == "6.2.0"
    assert get_runtime_profile("6.2.0").extension_folder == "exts/isaac_6.2"
    assert get_runtime_profile("isaacsim_6.2").ros2_omnigraph_namespace == "isaacsim.ros2.nodes"
    assert get_runtime_profile("6.2").code_pattern_version == "6.2.0"

    monkeypatch.delenv("ISAAC_VERSION", raising=False)
    monkeypatch.delenv("ISAAC_SIM_ROOT", raising=False)
    monkeypatch.delenv("ISAAC_SIM_PATH", raising=False)
    monkeypatch.setenv("ISAAC_RUNTIME_PROFILE", "6.2")
    assert get_runtime_profile().key == ISAAC_SIM_62.key

    monkeypatch.delenv("ISAAC_RUNTIME_PROFILE", raising=False)
    monkeypatch.setenv("ISAAC_SIM_ROOT", "/opt/isaac-sim-6.2.0")
    assert get_runtime_profile().key == "isaacsim-6.2"

    summary = runtime_scope_summary(ISAAC_SIM_62)
    assert summary["extension_folder"] == "exts/isaac_6.2"
    assert summary["ros2_omnigraph_namespace"] == "isaacsim.ros2.nodes"
    assert "Python 3.12" in prompt_runtime_rules(ISAAC_SIM_62)
    assert "UNVERIFIED" in prompt_runtime_rules(ISAAC_SIM_62)

    tagged_60 = {"runtime_profiles": ["isaacsim-6.0"]}
    assert metadata_matches_profile(tagged_60, ISAAC_SIM_62)
    assert metadata_matches_profile(tagged_60, ISAAC_SIM_60)
    assert not metadata_matches_profile({"runtime_profiles": ["isaacsim-5.1"]}, ISAAC_SIM_62)
    assert not metadata_matches_profile({"task_id": "legacy"}, ISAAC_SIM_62)
    assert metadata_matches_profile({"isaac_sim_versions": ["6.0.0"]}, ISAAC_SIM_62)
    assert metadata_matches_profile({"runtime_profiles": ["isaacsim-6.2"]}, ISAAC_SIM_62)
    assert not metadata_matches_profile({"runtime_profiles": ["isaacsim-6.2"]}, ISAAC_SIM_60)


def test_api_validator_puts_62_on_the_60_lane():
    from service.isaac_assist_service.chat.tools.api_validator import validate_code

    ok, issues = validate_code("import isaacsim.ros2.nodes\n", profile="6.2")
    assert ok, issues
    bad, bad_issues = validate_code(
        "node_type = 'isaacsim.ros2.bridge.ROS2PublishClock'\n",
        profile="isaacsim-6.2",
    )
    assert not bad
    assert any(item["severity"] == "version_mismatch" for item in bad_issues)


def test_extension_copy_targets_62_and_leaves_60_untouched():
    toml_62 = (REPO / "exts/isaac_6.2/omni.isaac.assist/config/extension.toml").read_text(encoding="utf-8")
    toml_60 = (REPO / "exts/isaac_6.0/omni.isaac.assist/config/extension.toml").read_text(encoding="utf-8")
    assert 'version = "6.2.0"' in toml_62
    assert "Python 3.12" in toml_62
    assert 'version = "1.0.0"' in toml_60
    gate_text = (
        REPO / "exts/isaac_6.2/omni.isaac.assist/omni/isaac/assist/version_gate.py"
    ).read_text(encoding="utf-8")
    assert 'TARGET_VERSION = "6.2.0"' in gate_text
    assert 'PYTHON_RUNTIME = "3.12"' in gate_text
    assert 'ROS2_OMNIGRAPH_NAMESPACE = "isaacsim.ros2.nodes"' in gate_text
    chat = (
        REPO / "exts/isaac_6.2/omni.isaac.assist/omni/isaac/assist/ui/chat_view.py"
    ).read_text(encoding="utf-8")
    assert "mount_sticky_note_panel" in chat
    assert "_build_sticky_notes" in chat
    launch = (REPO / "launch_isaac.sh").read_text(encoding="utf-8")
    assert "exts/isaac_6.2" in launch
    assert "--version 6.2" in launch
    policy = json.loads((REPO / "workspace/knowledge/runtime_scopes.json").read_text(encoding="utf-8"))
    assert policy["profiles"]["isaacsim-6.2"]["extension_folder"] == "exts/isaac_6.2"
    assert policy["profiles"]["isaacsim-6.0"]["extension_folder"] == "exts/isaac_6.0"


def test_sticky_panel_is_import_safe_and_wires_buttons():
    client = FakeNotes()
    controller = sticky_notes.StickyNoteController(
        client,
        stage_path="/tmp/scene.usd",
        selection_reader=lambda: ["/World/Cube"],
        prim_reader=lambda path: {
            "prim_type": "Cube",
            "key_attributes": {"size": 2},
            "world_transform": {"translate": [1, 0, 0], "rotate": [0, 0, 0], "scale": [1, 1, 1]},
        },
    )
    assert controller.toggle() is True
    assert controller.capture_selection() == ["/World/Cube"]
    controller.pending_region = {"x": 4, "y": 5, "width": 6, "height": 7}
    assert controller.mark_region()["width"] == 6
    controller.comment = "raise it"
    note = controller.add_draft()
    assert note["status"] == "draft"
    assert client.created[0]["prim_path"] == "/World/Cube"
    assert client.created[0]["comment"] == "raise it"
    sent = controller.send_batch()
    assert client.sent == [[note["id"]]]
    assert controller.notes[0]["status"] == "proposed"
    controller.confirm(note["id"])
    assert client.confirmed == [note["id"]]
    assert controller.notes[0]["status"] == "applied"
    controller.reject(note["id"])
    assert client.rejected == [note["id"]]
    assert controller.notes[0]["status"] == "rejected"

    rows = sticky_notes.sticky_panel_rows(controller)
    texts = [row["text"] for row in rows]
    assert "Sticky Note" in texts
    assert "Sticky Note: on" in texts
    assert any(row["kind"] == "note" and "Confirm" in row["actions"] for row in rows)
    assert any(row.get("marker") == "PIN /World/Cube" for row in rows)

    ui = RecordingUI()
    sticky_notes.mount_sticky_note_panel(ui, controller=controller)
    buttons = [event[1] for event in ui.events if event[0] == "Button"]
    assert "Use selection" in buttons
    assert "Mark region" in buttons
    assert "Add note" in buttons
    assert "Send" in buttons
    assert "Confirm" in buttons
    assert "Reject" in buttons
    assert NOTE_STATUSES_MATCH()


def NOTE_STATUSES_MATCH():
    from service.isaac_assist_service.notes.store import NOTE_STATUSES

    return sticky_notes.NOTE_STATUSES == NOTE_STATUSES


def test_selection_reader_uses_mocked_omni_usd():
    usd = types.ModuleType("omni.usd")
    omni_mod = types.ModuleType("omni")
    omni_mod.__path__ = []
    omni_mod.usd = usd

    class Prim:
        def IsValid(self):
            return True

        def GetTypeName(self):
            return "Xform"

        def get_key_attributes(self):
            return {"purpose": "render"}

        world_transform = {"matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}

    class Stage:
        def GetPrimAtPath(self, path):
            return Prim()

    class Selection:
        def get_selected_prim_paths(self):
            return ["/World/Robot"]

    class Context:
        def get_selection(self):
            return Selection()

        def get_stage(self):
            return Stage()

    usd.get_context = lambda: Context()
    sys.modules["omni"] = omni_mod
    sys.modules["omni.usd"] = usd
    try:
        importlib.reload(sticky_notes)
        assert sticky_notes.read_stage_selection() == ["/World/Robot"]
        snapshot = sticky_notes.read_prim_snapshot("/World/Robot")
        assert snapshot["prim_type"] == "Xform"
        assert snapshot["key_attributes"]["purpose"] == "render"
        assert snapshot["world_transform"]["matrix"][0][0] == 1
    finally:
        sys.modules.pop("omni.usd", None)
        sys.modules.pop("omni", None)
        importlib.reload(sticky_notes)


def test_notes_client_transport_builds_requests_without_network():
    seen = []

    def transport(method, path, payload, query):
        seen.append((method, path, payload, query))
        if method == "POST" and path == "/api/v1/notes":
            return {"note": {"id": "abc", "status": "draft"}}
        if method == "GET":
            return {"notes": [{"id": "abc"}]}
        return {"ok": True}

    client = NotesClient("http://127.0.0.1:8000", transport=transport)
    assert client.create({"comment": "hi"})["id"] == "abc"
    assert client.list_notes("/tmp/scene.usd")[0]["id"] == "abc"
    client.send("/tmp/scene.usd", ["abc"])
    client.confirm("/tmp/scene.usd", "abc")
    client.reject("/tmp/scene.usd", "abc")
    assert seen[2][0] == "POST" and seen[2][1] == "/api/v1/notes/send"
    assert seen[3][1] == "/api/v1/notes/abc/confirm"
    assert seen[4][1] == "/api/v1/notes/abc/reject"
    assert seen[3][3]["stage_path"] == "/tmp/scene.usd"
