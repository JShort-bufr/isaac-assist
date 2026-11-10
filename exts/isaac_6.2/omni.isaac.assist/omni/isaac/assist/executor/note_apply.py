# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# USD apply for a confirmed sticky-note plan. pxr and omni are optional at import.

"""Apply one sticky-note plan to a USD stage.

``apply_plan_on_open_stage`` is what Kit runs, on the main thread, through the
existing ``/exec_sync`` bridge. It edits the open stage inside one undo group.
``apply_note_file`` is the headless path used by ``scripts/bufrai_apply_note.py``.

A plan changes the stage only for ``set_transform``, ``set_attribute``, and
``add_prim``. Anything else returns ``changed: false``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
except Exception:
    Gf = None
    Sdf = None
    Usd = None
    UsdGeom = None

try:
    import omni.kit.undo as omni_undo
except Exception:
    omni_undo = None

try:
    import omni.usd as omni_usd
except Exception:
    omni_usd = None

_SUPPORTED = ("set_transform", "set_attribute", "add_prim")
_SKIP_ATTRS = {
    "attribute",
    "comment",
    "executable",
    "matrix",
    "name",
    "op",
    "payload",
    "prim_path",
    "prim_type",
    "rotate",
    "scale",
    "summary",
    "translate",
    "type",
    "value",
}


def _result(plan: Dict[str, Any], *, ok: bool, changed: bool, detail: str) -> Dict[str, Any]:
    return {
        "ok": ok,
        "changed": changed,
        "op": plan.get("op") or "",
        "prim_path": _prim_path(plan),
        "detail": detail,
    }


def _prim_path(plan: Dict[str, Any]) -> str:
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    return str(plan.get("prim_path") or payload.get("prim_path") or "")


def _pick(plan: Dict[str, Any], name: str) -> Any:
    if name in plan and plan.get(name) is not None:
        return plan.get(name)
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    return payload.get(name)


def _is_valid(obj: Any) -> bool:
    if obj is None:
        return False
    check = getattr(obj, "IsValid", None)
    if callable(check):
        return bool(check())
    return True


def _vec3(values: Any) -> Any:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError("expected 3 numbers")
    return Gf.Vec3d(float(values[0]), float(values[1]), float(values[2]))


def _prim(stage: Any, path: str) -> Any:
    if not path or not hasattr(stage, "GetPrimAtPath"):
        return None
    return stage.GetPrimAtPath(path)


def _xform_op(xform: Any, op_type: Any) -> Any:
    for existing in xform.GetOrderedXformOps():
        if existing.GetOpType() == op_type:
            return existing
    return xform.AddXformOp(op_type, UsdGeom.XformOp.PrecisionDouble)


def _set_transform(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    path = _prim_path(plan)
    prim = _prim(stage, path)
    if not _is_valid(prim):
        return _result(plan, ok=False, changed=False, detail="prim is not on the stage")
    scale = _pick(plan, "scale")
    translate = _pick(plan, "translate")
    rotate = _pick(plan, "rotate")
    matrix = _pick(plan, "matrix")
    if scale is None and translate is None and rotate is None and matrix is None:
        return _result(plan, ok=False, changed=False, detail="transform fields are missing")
    try:
        scale_value = None if scale is None else _vec3(scale)
        translate_value = None if translate is None else _vec3(translate)
        rotate_value = None if rotate is None else _vec3(rotate)
    except ValueError:
        return _result(plan, ok=False, changed=False, detail="transform vectors must be 3 numbers")
    if matrix is not None and not (
        isinstance(matrix, list)
        and len(matrix) == 4
        and all(isinstance(row, list) and len(row) == 4 for row in matrix)
    ):
        return _result(plan, ok=False, changed=False, detail="matrix must be 4x4")
    xform = UsdGeom.Xformable(prim)
    if scale_value is not None:
        _xform_op(xform, UsdGeom.XformOp.TypeScale).Set(scale_value)
    if translate_value is not None:
        _xform_op(xform, UsdGeom.XformOp.TypeTranslate).Set(translate_value)
    if rotate_value is not None:
        _xform_op(xform, UsdGeom.XformOp.TypeRotateXYZ).Set(rotate_value)
    if matrix is not None:
        flat = [float(value) for row in matrix for value in row]
        _xform_op(xform, UsdGeom.XformOp.TypeTransform).Set(Gf.Matrix4d(*flat))
    return _result(plan, ok=True, changed=True, detail="set_transform")


def _sdf_type(value: Any) -> Any:
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    if isinstance(value, str):
        return Sdf.ValueTypeNames.String
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return Sdf.ValueTypeNames.Double3
    return Sdf.ValueTypeNames.String


def _coerce(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 3 and not isinstance(value[0], (list, tuple)):
        return _vec3(value)
    return value


def _set_one(prim: Any, name: str, value: Any) -> bool:
    attr = prim.GetAttribute(name) if hasattr(prim, "GetAttribute") else None
    if not _is_valid(attr):
        if not hasattr(prim, "CreateAttribute"):
            return False
        attr = prim.CreateAttribute(name, _sdf_type(value))
    if not _is_valid(attr) or not hasattr(attr, "Set"):
        return False
    attr.Set(_coerce(value))
    return True


def _attribute_pairs(plan: Dict[str, Any]) -> Dict[str, Any]:
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    name = plan.get("attribute") or payload.get("attribute") or payload.get("name")
    if name:
        if "value" in plan:
            return {str(name): plan.get("value")}
        if "value" in payload:
            return {str(name): payload.get("value")}
    pairs = {}
    for source in (payload, plan):
        for key, value in source.items():
            if key in _SKIP_ATTRS or value is None:
                continue
            pairs[str(key)] = value
    return pairs


def _set_attribute(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    path = _prim_path(plan)
    prim = _prim(stage, path)
    if not _is_valid(prim):
        return _result(plan, ok=False, changed=False, detail="prim is not on the stage")
    pairs = _attribute_pairs(plan)
    if not pairs:
        return _result(plan, ok=False, changed=False, detail="attribute value is missing")
    wrote = False
    for name, value in pairs.items():
        wrote = _set_one(prim, name, value) or wrote
    if not wrote:
        return _result(plan, ok=False, changed=False, detail="attribute was not written")
    return _result(plan, ok=True, changed=True, detail="set_attribute")


def _schema_for(type_name: str) -> Any:
    mapping = {
        "Cube": UsdGeom.Cube,
        "Sphere": UsdGeom.Sphere,
        "Cylinder": UsdGeom.Cylinder,
        "Mesh": UsdGeom.Mesh,
        "Xform": UsdGeom.Xform,
    }
    return mapping.get(type_name)


def _add_prim(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    path = _prim_path(plan)
    if not path:
        return _result(plan, ok=False, changed=False, detail="prim_path is missing")
    existing = _prim(stage, path)
    if _is_valid(existing):
        return _result(plan, ok=False, changed=False, detail="prim already exists")
    type_name = str(_pick(plan, "prim_type") or _pick(plan, "type") or "Xform")
    schema = _schema_for(type_name)
    if schema is not None and hasattr(schema, "Define"):
        schema.Define(stage, path)
    elif hasattr(stage, "DefinePrim"):
        stage.DefinePrim(path, type_name)
    else:
        return _result(plan, ok=False, changed=False, detail="stage cannot define a prim")
    return _result(plan, ok=True, changed=True, detail="add_prim")


def apply_plan_to_stage(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Edit ``stage`` in place. Does not open a file and does not touch Kit."""
    if Gf is None or UsdGeom is None or Sdf is None:
        return _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="pxr is not available")
    if not isinstance(plan, dict):
        return _result({}, ok=False, changed=False, detail="plan must be an object")
    op = plan.get("op")
    if op == "set_transform":
        return _set_transform(stage, plan)
    if op == "set_attribute":
        return _set_attribute(stage, plan)
    if op == "add_prim":
        return _add_prim(stage, plan)
    if op not in _SUPPORTED:
        return _result(plan, ok=False, changed=False, detail="unsupported op")
    return _result(plan, ok=False, changed=False, detail="unsupported op")


def apply_plan_on_open_stage(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Edit the open Kit stage inside one undo group.

    Called on Kit's main thread via the existing ``/exec_sync`` bridge.
    """
    if omni_usd is None or omni_undo is None:
        return _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="omni.usd is not available")
    stage = omni_usd.get_context().get_stage()
    if stage is None:
        return _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="no open stage")
    omni_undo.begin_group()
    try:
        return apply_plan_to_stage(stage, plan)
    finally:
        omni_undo.end_group()


def apply_note_file(stage_path: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Open a ``.usd`` or ``.usda`` file, apply ``plan``, and save if it changed."""
    if Usd is None:
        result = _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="pxr is not available")
        result["saved"] = False
        return result
    stage = Usd.Stage.Open(stage_path)
    if stage is None:
        result = _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="stage file did not open")
        result["saved"] = False
        return result
    result = apply_plan_to_stage(stage, plan)
    result["saved"] = False
    if result.get("changed"):
        stage.Save()
        result["saved"] = True
    return result
