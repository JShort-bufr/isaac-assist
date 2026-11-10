# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Kit command undo and headless before-values for sticky notes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_bufrai_phase1_apply import _Prim, _Stage, _Vec, _install_pxr, _load_note_apply

pytestmark = pytest.mark.l0

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bufrai_apply_note.py"


class _Commands:
    def __init__(self):
        self.calls = []

    def execute(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return (True, name)


class _Undo:
    def __init__(self):
        self.groups = []
        self.undos = 0

    def begin_group(self):
        self.groups.append("begin")

    def end_group(self):
        self.groups.append("end")

    def undo(self):
        self.undos += 1


class _Context:
    def __init__(self, stage):
        self._stage = stage

    def get_stage(self):
        return self._stage

    def get_name(self):
        return ""


def _module():
    _install_pxr()
    module = _load_note_apply()
    module.omni_commands = None
    return module


def _drop_pxr():
    for name in ("pxr", "pxr.Gf", "pxr.Sdf", "pxr.Usd", "pxr.UsdGeom"):
        sys.modules.pop(name, None)


def test_open_stage_apply_uses_kit_commands_and_undo():
    note_apply = _module()
    try:
        _assert_commands_and_undo(note_apply)
    finally:
        _drop_pxr()


def _assert_commands_and_undo(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")
    commands = _Commands()
    undo = _Undo()
    note_apply.omni_commands = commands
    note_apply.omni_undo = undo
    note_apply.omni_usd = type("Usd", (), {"get_context": lambda self: _Context(stage)})()
    result = note_apply.apply_plan_on_open_stage(
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": 2, "executable": True}
    )
    assert result["changed"] is True
    assert result["undo_group"] is True
    assert undo.groups == ["begin", "end"]
    assert commands.calls[0][0] == "TransformPrimSRT"
    assert commands.calls[0][1]["new_scale"] == _Vec(2.0, 2.0, 2.0)
    assert commands.calls[0][1]["usd_context_name"] == ""
    assert stage.prims["/World/Cube"].xform_ops == []

    note_apply.undo_last_on_open_stage()
    assert undo.undos == 1

    mismatched = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"xformOp:translate": 1.0},
            "executable": True,
        }
    )
    assert mismatched["changed"] is False
    assert "type mismatch" in mismatched["detail"]
    assert len(commands.calls) == 1


def test_nucleus_stage_refuses_commands_unless_session_layer_is_writable():
    note_apply = _module()
    try:
        _assert_nucleus_gate(note_apply)
    finally:
        _drop_pxr()


def _assert_nucleus_gate(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")

    class _Layer:
        identifier = "omniverse://localhost/Projects/scene.usd"
        permissionToEdit = False

    stage.GetRootLayer = lambda: _Layer()
    session = {"target": None}
    stage.GetSessionLayer = lambda: "session-layer"
    stage.SetEditTarget = lambda layer: session.__setitem__("target", layer)
    commands = _Commands()
    note_apply.omni_commands = commands
    note_apply.omni_undo = _Undo()
    note_apply.omni_usd = type("Usd", (), {"get_context": staticmethod(lambda: _Context(stage))})()
    blocked = note_apply.apply_plan_on_open_stage(
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2], "executable": True}
    )
    assert blocked["changed"] is False
    assert "Nucleus" in blocked["detail"]
    assert commands.calls == []

    allowed = note_apply.apply_plan_on_open_stage(
        {
            "op": "add_prim",
            "prim_path": "/World/New",
            "prim_type": "Cube",
            "executable": True,
            "session_layer": "session",
            "session_layer_writable": True,
        }
    )
    assert allowed["changed"] is True
    assert [name for name, _kwargs in commands.calls] == ["CreatePrim", "CreateDefaultXformOnPrim"]
    assert session["target"] == "session-layer"


def test_headless_revert_restores_recorded_before_values(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bufrai_apply_note_phase2", _SCRIPT_PATH)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    sidecar = tmp_path / "scene.usda.notes.json"
    note = {
        "id": "n1",
        "status": "confirmed",
        "prim_path": "/World/Cube",
        "proposal": {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2], "executable": True},
    }
    sidecar.write_text(json.dumps({"notes": [note]}), encoding="utf-8")
    calls = []

    def fake_apply(path, plan):
        calls.append(("apply", plan))
        return {
            "ok": True,
            "changed": True,
            "saved": True,
            "before": {"op": "set_transform", "prim_path": "/World/Cube", "scale": [1, 1, 1]},
            "detail": "set_transform",
        }

    def fake_revert(path, before):
        calls.append(("revert", before))
        return {"ok": True, "changed": True, "saved": True, "detail": "set_transform"}

    monkeypatch.setattr(script, "apply_note_file", fake_apply)
    monkeypatch.setattr(script, "revert_note_file", fake_revert)
    assert script.run(["--stage", str(stage), "--note-id", "n1"]) == 0
    stored = json.loads(sidecar.read_text(encoding="utf-8"))["notes"][0]
    assert stored["status"] == "applied"
    assert stored["before"]["scale"] == [1, 1, 1]
    assert script.run(["--stage", str(stage), "--note-id", "n1", "--revert"]) == 0
    assert calls[1][0] == "revert"
    assert calls[1][1]["scale"] == [1, 1, 1]
    assert json.loads(sidecar.read_text(encoding="utf-8"))["notes"][0]["status"] == "reverted"
