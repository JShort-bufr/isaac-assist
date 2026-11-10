# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Kit command undo and headless before-values for sticky notes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_bufrai_phase1_apply import _Attr, _Prim, _Stage, _Vec, _install_pxr, _load_note_apply

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


class _GfValue(tuple):
    def __new__(cls, *values):
        if len(values) == 1 and isinstance(values[0], (list, tuple)):
            values = tuple(values[0])
        return tuple.__new__(cls, tuple(float(item) for item in values))


class _Vec3d(_GfValue):
    pass


class _Vec3f(_GfValue):
    pass


class _Vec3h(_GfValue):
    pass


class _Quatd(_GfValue):
    pass


class _Quatf(_GfValue):
    pass


class _Matrix4d(_GfValue):
    pass


class _VtArray(tuple):
    def __new__(cls, values):
        return tuple.__new__(cls, tuple(values))


def _install_gf_types(note_apply):
    gf = note_apply.Gf
    gf.Vec3d = _Vec3d
    gf.Vec3f = _Vec3f
    gf.Vec3h = _Vec3h
    gf.Quatd = _Quatd
    gf.Quatf = _Quatf
    gf.Matrix4d = _Matrix4d
    names = note_apply.Sdf.ValueTypeNames
    names.Float3 = "float3"
    names.Half3 = "half3"
    names.Quatd = "quatd"
    names.Quatf = "quatf"
    names.Matrix4d = "matrix4d"
    names.Float = "float"
    names.DoubleArray = "double[]"
    names.Vec3dArray = "double3[]"
    note_apply.Vt = type(
        "Vt",
        (),
        {
            "DoubleArray": type("DoubleArray", (_VtArray,), {}),
            "FloatArray": type("FloatArray", (_VtArray,), {}),
            "IntArray": type("IntArray", (_VtArray,), {}),
            "BoolArray": type("BoolArray", (_VtArray,), {}),
            "Vec3dArray": type("Vec3dArray", (_VtArray,), {}),
            "Vec3fArray": type("Vec3fArray", (_VtArray,), {}),
            "Vec3hArray": type("Vec3hArray", (_VtArray,), {}),
        },
    )


class _TypedPrim(_Prim):
    def __init__(self, path, types):
        super().__init__(path)
        self._types = dict(types)

    def GetAttribute(self, name):
        if name not in self._types:
            return None
        attr = _Attr()
        token = self._types[name]
        attr.GetTypeName = lambda token=token: token
        return attr


def _wire(note_apply, stage, commands, undo):
    note_apply.omni_commands = commands
    note_apply.omni_undo = undo
    note_apply.omni_usd = type("Usd", (), {"get_context": staticmethod(lambda: _Context(stage))})()


def test_change_property_casts_python_values_to_gf_types():
    note_apply = _module()
    try:
        _install_gf_types(note_apply)
        _assert_gf_casts(note_apply)
    finally:
        _drop_pxr()


def _assert_gf_casts(note_apply):
    assert note_apply.cast_usd_value(4, "double3") == _Vec3d(4.0, 4.0, 4.0)
    assert note_apply.cast_usd_value([4, 4, 4], note_apply.Sdf.ValueTypeNames.Double3) == _Vec3d(4.0, 4.0, 4.0)
    assert note_apply.cast_usd_value([1, 0, 0], "float3") == _Vec3f(1.0, 0.0, 0.0)
    assert note_apply.cast_usd_value(0.5, "half3") == _Vec3h(0.5, 0.5, 0.5)
    assert note_apply.cast_usd_value([0, 0, 0, 1], "quatd") == _Quatd(0.0, 0.0, 0.0, 1.0)
    assert note_apply.cast_usd_value([1, 0, 0, 0], "quatf") == _Quatf(1.0, 0.0, 0.0, 0.0)
    matrix = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    assert note_apply.cast_usd_value(matrix, "matrix4d") == _Matrix4d(*[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    assert note_apply.cast_usd_value(2, "double") == 2.0
    assert note_apply.cast_usd_value(3, "int") == 3
    assert note_apply.cast_usd_value(True, "bool") is True
    doubles = note_apply.cast_usd_value([1, 2], "double[]")
    assert type(doubles).__name__ == "DoubleArray"
    assert doubles == (1.0, 2.0)
    vectors = note_apply.cast_usd_value([[1, 0, 0], [0, 1, 0]], "double3[]")
    assert type(vectors).__name__ == "Vec3dArray"
    assert vectors[0] == _Vec3d(1.0, 0.0, 0.0)

    stage = _Stage()
    stage.prims["/World/Cube"] = _TypedPrim(
        "/World/Cube",
        {"displayColor": "float3", "xformOp:orient": "quatd"},
    )
    commands = _Commands()
    _wire(note_apply, stage, commands, _Undo())
    scalar = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"xformOp:scale": 4},
            "executable": True,
        }
    )
    listed = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"xformOp:scale": [4, 4, 4]},
            "executable": True,
        }
    )
    colored = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"displayColor": [0.2, 0.4, 0.6]},
            "executable": True,
        }
    )
    assert scalar["changed"] is True
    assert listed["changed"] is True
    assert colored["changed"] is True
    scale_values = [kwargs["value"] for name, kwargs in commands.calls if kwargs.get("prop_path", "").endswith("xformOp:scale")]
    assert scale_values == [_Vec3d(4.0, 4.0, 4.0), _Vec3d(4.0, 4.0, 4.0)]
    assert all(not isinstance(value, list) for value in scale_values)
    assert scale_values[0].__class__ is _Vec3d
    color = next(kwargs["value"] for name, kwargs in commands.calls if kwargs.get("prop_path", "").endswith("displayColor"))
    assert color == _Vec3f(0.2, 0.4, 0.6)
    transform = note_apply.apply_plan_on_open_stage(
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": 3, "executable": True}
    )
    assert transform["changed"] is True
    srt = next(kwargs for name, kwargs in commands.calls if name == "TransformPrimSRT")
    assert srt["new_scale"] == _Vec3d(3.0, 3.0, 3.0)


def test_failed_kit_command_rolls_back_and_leaves_the_stage_unchanged():
    note_apply = _module()
    try:
        _install_gf_types(note_apply)
        _assert_failed_command_rolls_back(note_apply)
    finally:
        _drop_pxr()


def _assert_failed_command_rolls_back(note_apply):
    stage = _Stage()
    prim = _Prim("/World/Cube")
    original = _Vec3d(3.0, 3.0, 3.0)
    prim.attrs["xformOp:scale"] = type("Attr", (), {"value": original, "IsValid": lambda self: True})()
    stage.prims["/World/Cube"] = prim
    class _RestoringUndo(_Undo):
        def __init__(self):
            super().__init__()
            self.stack = []

        def undo(self):
            super().undo()
            if self.stack:
                self.stack.pop()()

    commands = _Commands()
    undo = _RestoringUndo()
    message = "Type mismatch for </World/Cube.xformOp:scale>: expected 'GfVec3d', got 'vector<VtValue, allocator<VtValue> >'"

    def execute(name, **kwargs):
        commands.calls.append((name, kwargs))
        if name != "ChangeProperty":
            return (True, name)
        old = prim.attrs["xformOp:scale"].value
        prim.attrs["xformOp:scale"].value = kwargs["value"]

        def restore(previous=old):
            prim.attrs["xformOp:scale"].value = previous

        undo.stack.append(restore)
        raise RuntimeError(message)

    commands.execute = execute
    _wire(note_apply, stage, commands, undo)
    result = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"xformOp:scale": 4},
            "executable": True,
        }
    )
    assert result["changed"] is False
    assert result["command_failed"] is True
    assert result["rolled_back"] is True
    assert message in result["detail"]
    assert undo.groups == ["begin", "end"]
    assert undo.undos == 1
    assert prim.attrs["xformOp:scale"].value == original
    assert commands.calls[0][1]["value"] == _Vec3d(4.0, 4.0, 4.0)

    refused = _Commands()

    def refuse(name, **kwargs):
        refused.calls.append((name, kwargs))
        return (False, message)

    refused.execute = refuse
    quiet = _RestoringUndo()
    _wire(note_apply, stage, refused, quiet)
    missed = note_apply.apply_plan_on_open_stage(
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"xformOp:scale": [4, 4, 4]},
            "executable": True,
        }
    )
    assert missed["command_failed"] is True
    assert missed["changed"] is False
    assert message in missed["detail"]
    assert quiet.groups == ["begin", "end"]
    assert quiet.undos == 0
    assert prim.attrs["xformOp:scale"].value == original


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
