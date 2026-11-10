# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Mocked pxr/omni coverage for sticky-note USD apply."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.l0

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "exts"
    / "isaac_6.2"
    / "omni.isaac.assist"
    / "omni"
    / "isaac"
    / "assist"
    / "executor"
    / "note_apply.py"
)
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bufrai_apply_note.py"


class _Vec:
    def __init__(self, *values):
        self.values = values

    def __eq__(self, other):
        return isinstance(other, _Vec) and self.values == other.values


class _Op:
    def __init__(self, op_type):
        self.op_type = op_type
        self.value = None

    def GetOpType(self):
        return self.op_type

    def Set(self, value):
        self.value = value


class _Prim:
    def __init__(self, path, valid=True):
        self.path = path
        self.valid = valid
        self.attrs = {}
        self.xform_ops = []
        self.type_name = "Xform"

    def IsValid(self):
        return self.valid

    def GetAttribute(self, name):
        return self.attrs.get(name)

    def CreateAttribute(self, name, type_name):
        attr = _Attr()
        attr.type_name = type_name
        self.attrs[name] = attr
        return attr


class _Attr:
    def __init__(self, valid=True):
        self.valid = valid
        self.value = None
        self.type_name = None

    def IsValid(self):
        return self.valid

    def Set(self, value):
        self.value = value


class _Xformable:
    def __init__(self, prim):
        self._prim = prim

    def GetOrderedXformOps(self):
        return list(self._prim.xform_ops)

    def AddXformOp(self, op_type, precision):
        op = _Op(op_type)
        op.precision = precision
        self._prim.xform_ops.append(op)
        return op


class _Define:
    def __init__(self, type_name):
        self.type_name = type_name

    def Define(self, stage, path):
        prim = _Prim(path)
        prim.type_name = self.type_name
        stage.prims[path] = prim
        stage.defined.append((self.type_name, path))
        return prim


class _Stage:
    def __init__(self):
        self.prims = {}
        self.defined = []
        self.saved = False

    def GetPrimAtPath(self, path):
        return self.prims.get(path)

    def DefinePrim(self, path, type_name):
        prim = _Prim(path)
        prim.type_name = type_name
        self.prims[path] = prim
        self.defined.append((type_name, path))
        return prim

    def Save(self):
        self.saved = True


class _Names:
    Bool = "bool"
    Int = "int"
    Double = "double"
    String = "string"
    Double3 = "double3"


def _install_pxr():
    pxr = types.ModuleType("pxr")
    gf = types.ModuleType("pxr.Gf")
    gf.Vec3d = _Vec
    gf.Matrix4d = _Vec
    sdf = types.ModuleType("pxr.Sdf")
    sdf.ValueTypeNames = _Names
    usd = types.ModuleType("pxr.Usd")
    usdgeom = types.ModuleType("pxr.UsdGeom")
    usdgeom.Xformable = _Xformable

    class _XformOp:
        TypeScale = "scale"
        TypeTranslate = "translate"
        TypeRotateXYZ = "rotate"
        TypeTransform = "matrix"
        PrecisionDouble = "double"

    usdgeom.XformOp = _XformOp
    usdgeom.Cube = _Define("Cube")
    usdgeom.Sphere = _Define("Sphere")
    usdgeom.Cylinder = _Define("Cylinder")
    usdgeom.Mesh = _Define("Mesh")
    usdgeom.Xform = _Define("Xform")
    pxr.Gf = gf
    pxr.Sdf = sdf
    pxr.Usd = usd
    pxr.UsdGeom = usdgeom
    sys.modules["pxr"] = pxr
    sys.modules["pxr.Gf"] = gf
    sys.modules["pxr.Sdf"] = sdf
    sys.modules["pxr.Usd"] = usd
    sys.modules["pxr.UsdGeom"] = usdgeom
    return usd


def _load_note_apply():
    spec = importlib.util.spec_from_file_location("bufrai_note_apply_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def note_apply():
    usd = _install_pxr()
    module = _load_note_apply()
    stage_box = {"stage": None}

    def open_stage(path):
        stage_box["path"] = path
        return stage_box["stage"]

    usd.Stage = types.SimpleNamespace(Open=open_stage)
    module.Usd = usd
    module._stage_box = stage_box
    try:
        yield module
    finally:
        for name in ("pxr", "pxr.Gf", "pxr.Sdf", "pxr.Usd", "pxr.UsdGeom"):
            sys.modules.pop(name, None)


def test_set_transform_scale_matches_legion_payload(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")
    result = note_apply.apply_plan_to_stage(
        stage,
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2], "executable": True},
    )
    assert result["changed"] is True
    assert result["detail"] == "set_transform"
    ops = stage.prims["/World/Cube"].xform_ops
    assert len(ops) == 1
    assert ops[0].op_type == "scale"
    assert ops[0].value == _Vec(2.0, 2.0, 2.0)


def test_set_attribute_and_add_prim(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")
    attr = note_apply.apply_plan_to_stage(
        stage,
        {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "payload": {"size": 2},
            "executable": True,
        },
    )
    assert attr["changed"] is True
    assert stage.prims["/World/Cube"].attrs["size"].value == 2
    added = note_apply.apply_plan_to_stage(
        stage,
        {"op": "add_prim", "prim_path": "/World/New", "prim_type": "Cube", "executable": True},
    )
    assert added["changed"] is True
    assert stage.defined == [("Cube", "/World/New")]
    again = note_apply.apply_plan_to_stage(
        stage,
        {"op": "add_prim", "prim_path": "/World/New", "prim_type": "Cube", "executable": True},
    )
    assert again["changed"] is False
    missing = note_apply.apply_plan_to_stage(
        stage,
        {"op": "set_transform", "prim_path": "/World/Missing", "scale": [1, 1, 1]},
    )
    assert missing["changed"] is False
    assert missing["detail"] == "prim is not on the stage"


def test_open_stage_uses_one_undo_group(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")
    groups = []

    class _Undo:
        def begin_group(self):
            groups.append("begin")

        def end_group(self):
            groups.append("end")

    class _Usd:
        def get_context(self):
            return self

        def get_stage(self):
            return stage

    note_apply.omni_undo = _Undo()
    note_apply.omni_usd = _Usd()
    result = note_apply.apply_plan_on_open_stage(
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2]}
    )
    assert result["changed"] is True
    assert groups == ["begin", "end"]

    note_apply.omni_usd = types.SimpleNamespace(
        get_context=lambda: types.SimpleNamespace(get_stage=lambda: None)
    )
    empty = note_apply.apply_plan_on_open_stage(
        {"op": "set_attribute", "prim_path": "/World/Cube", "payload": {"size": 1}}
    )
    assert empty["changed"] is False
    assert empty["detail"] == "no open stage"
    assert groups == ["begin", "end"]


def test_file_apply_saves_only_when_the_stage_changes(note_apply):
    stage = _Stage()
    stage.prims["/World/Cube"] = _Prim("/World/Cube")
    note_apply._stage_box["stage"] = stage
    saved = note_apply.apply_note_file(
        "/tmp/scene.usda",
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2]},
    )
    assert saved["saved"] is True
    assert stage.saved is True
    assert note_apply._stage_box["path"] == "/tmp/scene.usda"

    stage.saved = False
    missed = note_apply.apply_note_file(
        "/tmp/scene.usda",
        {"op": "set_transform", "prim_path": "/World/Missing", "scale": [1, 1, 1]},
    )
    assert missed["changed"] is False
    assert missed["saved"] is False
    assert stage.saved is False


def test_headless_script_refuses_unconfirmed_and_marks_applied(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bufrai_apply_note_under_test", _SCRIPT_PATH)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    stage = tmp_path / "scene.usda"
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    sidecar = tmp_path / "scene.usda.notes.json"
    note = {
        "id": "n1",
        "status": "proposed",
        "prim_path": "/World/Cube",
        "proposal": {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2], "executable": True},
    }
    sidecar.write_text(json.dumps({"notes": [note]}), encoding="utf-8")
    calls = []

    def fake_apply(path, plan):
        calls.append((path, plan))
        return {"ok": True, "changed": True, "saved": True, "op": plan["op"], "prim_path": plan["prim_path"], "detail": "set_transform"}

    monkeypatch.setattr(script, "apply_note_file", fake_apply)
    refused = script.run(["--stage", str(stage)])
    assert refused == 2
    assert calls == []
    assert json.loads(sidecar.read_text(encoding="utf-8"))["notes"][0]["status"] == "proposed"

    note["status"] = "confirmed"
    sidecar.write_text(json.dumps({"notes": [note]}), encoding="utf-8")
    applied = script.run(["--stage", str(stage), "--note-id", "n1"])
    assert applied == 0
    assert calls[0][1]["scale"] == [2, 2, 2]
    assert json.loads(sidecar.read_text(encoding="utf-8"))["notes"][0]["status"] == "applied"


def test_kit_exec_code_carries_the_plan_without_marking_applied():
    from service.isaac_assist_service.notes.kit_apply import build_kit_exec_code, parse_kit_exec_output

    code = build_kit_exec_code(
        {"op": "set_transform", "prim_path": "/World/Cube", "scale": [2, 2, 2], "executable": True}
    )
    assert "apply_plan_on_open_stage" in code
    assert "[2,2,2]" in code
    parsed = parse_kit_exec_output(
        'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "changed": true, "detail": "set_transform"}'
    )
    assert parsed["changed"] is True
    assert parse_kit_exec_output("no marker") is None
