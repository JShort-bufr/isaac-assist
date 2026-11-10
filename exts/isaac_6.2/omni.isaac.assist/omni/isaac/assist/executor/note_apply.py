# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# USD apply for a confirmed sticky-note plan. pxr and omni are optional at import.

"""Apply one sticky-note plan to a USD stage.

``apply_plan_on_open_stage`` is what Kit runs, on the main thread, through the
existing ``/exec_sync`` bridge. When ``omni.kit.commands`` is present the edit
is one undo group of Kit commands, so ``omni.kit.undo.undo()`` reverts it.
``apply_note_file`` is the headless path used by ``scripts/bufrai_apply_note.py``
and keeps raw ``pxr`` writes plus before-values for a later revert.

A plan changes the stage only for ``set_transform``, ``set_attribute``, and
``add_prim``. Anything else returns ``changed: false``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional

_usd_spec = importlib.util.spec_from_file_location(
    "bufrai_note_usd_types",
    Path(__file__).resolve().parent / "usd_types.py",
)
_usd_types = importlib.util.module_from_spec(_usd_spec)
_usd_spec.loader.exec_module(_usd_types)

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
    import omni.kit.commands as omni_commands
except Exception:
    omni_commands = None

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


def _checked_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    prepared = _usd_types.prepare_plan(plan)
    if not prepared["ok"]:
        return _result(plan, ok=False, changed=False, detail=prepared["error"])
    return prepared["plan"]


def _json_vec(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    values = getattr(value, "values", None)
    if values is not None:
        return [float(item) for item in values]
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        return None


def _read_op_value(op: Any) -> Any:
    getter = getattr(op, "Get", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return getattr(op, "value", None)


def capture_before(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Values to restore with raw pxr when Kit's undo stack is not available."""
    path = _prim_path(plan) if isinstance(plan, dict) else ""
    op = plan.get("op") if isinstance(plan, dict) else ""
    before: Dict[str, Any] = {"op": op, "prim_path": path}
    try:
        prim = _prim(stage, path)
        if op == "set_transform" and _is_valid(prim) and UsdGeom is not None:
            mapping = {
                UsdGeom.XformOp.TypeScale: "scale",
                UsdGeom.XformOp.TypeTranslate: "translate",
                UsdGeom.XformOp.TypeRotateXYZ: "rotate",
                UsdGeom.XformOp.TypeTransform: "matrix",
            }
            xform = UsdGeom.Xformable(prim)
            for existing in xform.GetOrderedXformOps():
                key = mapping.get(existing.GetOpType())
                if key:
                    before[key] = _json_vec(_read_op_value(existing))
        if op == "set_attribute" and _is_valid(prim):
            attrs: Dict[str, Any] = {}
            for name in _attribute_pairs(plan):
                attr = prim.GetAttribute(name) if hasattr(prim, "GetAttribute") else None
                if _is_valid(attr):
                    if hasattr(attr, "Get") and callable(attr.Get):
                        attrs[name] = {"existed": True, "value": attr.Get()}
                    elif hasattr(attr, "value"):
                        attrs[name] = {"existed": True, "value": attr.value}
                    else:
                        attrs[name] = {"existed": True, "value": None}
                else:
                    attrs[name] = {"existed": False}
            before["attributes"] = attrs
        if op == "add_prim":
            before["existed"] = _is_valid(prim)
    except Exception:
        return before
    return before


def _usd_context_name() -> str:
    if omni_usd is None:
        return ""
    try:
        context = omni_usd.get_context()
        getter = getattr(context, "get_name", None)
        if callable(getter):
            return str(getter() or "")
    except Exception:
        return ""
    return ""


def _command_succeeded(result: Any) -> bool:
    if isinstance(result, tuple):
        return bool(result[0]) if result else False
    if result is None:
        return True
    return bool(result)


def _execute_command(name: str, **kwargs: Any) -> None:
    result = omni_commands.execute(name, **kwargs)
    if not _command_succeeded(result):
        raise RuntimeError(f"{name} did not change the stage")


def _edit_blocked(stage: Any, plan: Dict[str, Any]) -> str:
    if plan.get("session_layer") and plan.get("session_layer_writable"):
        return ""
    root = None
    getter = getattr(stage, "GetRootLayer", None)
    if callable(getter):
        root = getter()
    if root is not None:
        identifier = str(getattr(root, "identifier", "") or "")
        if identifier.startswith("omniverse:"):
            return "Nucleus stage is read-only; confirm and apply are refused"
        if getattr(root, "permissionToEdit", True) is False:
            return "stage layer is read-only; confirm and apply are refused"
    if plan.get("stage_read_only"):
        return "stage is read-only; confirm and apply are refused"
    return ""


def _use_session_layer(stage: Any, plan: Dict[str, Any]) -> None:
    layer_name = str(plan.get("session_layer") or "").strip().lower()
    if layer_name not in ("session", "anon", "anonymous"):
        return
    if not plan.get("session_layer_writable"):
        return
    getter = getattr(stage, "GetSessionLayer", None)
    if not callable(getter):
        return
    layer = getter()
    setter = getattr(stage, "SetEditTarget", None)
    if layer is not None and callable(setter):
        setter(layer)


def _dispatch_commands(plan: Dict[str, Any], context_name: str) -> str:
    op = plan.get("op")
    path = _prim_path(plan)
    if op == "set_transform":
        scale = _pick(plan, "scale")
        translate = _pick(plan, "translate")
        rotate = _pick(plan, "rotate")
        matrix = _pick(plan, "matrix")
        if scale is None and translate is None and rotate is None and matrix is None:
            raise RuntimeError("transform fields are missing")
        if matrix is not None:
            _execute_command(
                "ChangeProperty",
                prop_path=f"{path}.xformOp:transform",
                value=matrix,
                prev=None,
                usd_context_name=context_name,
            )
        if scale is not None or translate is not None or rotate is not None:
            kwargs: Dict[str, Any] = {"path": path, "usd_context_name": context_name}
            if scale is not None:
                kwargs["new_scale"] = _vec3(scale)
            if translate is not None:
                kwargs["new_translation"] = _vec3(translate)
            if rotate is not None:
                kwargs["new_rotation_euler"] = _vec3(rotate)
            _execute_command("TransformPrimSRT", **kwargs)
        return "set_transform"
    if op == "set_attribute":
        pairs = _attribute_pairs(plan)
        if not pairs:
            raise RuntimeError("attribute value is missing")
        for name, value in pairs.items():
            _execute_command(
                "ChangeProperty",
                prop_path=f"{path}.{name}",
                value=value,
                prev=None,
                usd_context_name=context_name,
            )
        return "set_attribute"
    if op == "add_prim":
        if not path:
            raise RuntimeError("prim_path is missing")
        type_name = str(_pick(plan, "prim_type") or _pick(plan, "type") or "Xform")
        _execute_command(
            "CreatePrim",
            prim_path=path,
            prim_type=type_name,
            select_new_prim=False,
            create_default_xform=False,
            usd_context_name=context_name,
        )
        _execute_command(
            "CreateDefaultXformOnPrim",
            prim_path=path,
            usd_context_name=context_name,
        )
        return "add_prim"
    raise RuntimeError("unsupported op")


def _apply_via_commands(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    before = capture_before(stage, plan)
    context_name = _usd_context_name()
    _use_session_layer(stage, plan)
    omni_undo.begin_group()
    try:
        detail = _dispatch_commands(plan, context_name)
        result = _result(plan, ok=True, changed=True, detail=detail)
    except Exception as exc:
        result = _result(plan, ok=False, changed=False, detail=str(exc))
    finally:
        omni_undo.end_group()
    result["before"] = before
    result["undo_group"] = True
    return result


def apply_plan_to_stage(stage: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Edit ``stage`` in place. Does not open a file and does not touch Kit."""
    if not isinstance(plan, dict):
        return _result({}, ok=False, changed=False, detail="plan must be an object")
    checked = _checked_plan(plan)
    if isinstance(checked, dict) and "changed" in checked and checked.get("ok") is False:
        return checked
    plan = checked
    if Gf is None or UsdGeom is None or Sdf is None:
        return _result(plan, ok=False, changed=False, detail="pxr is not available")
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
    Kit commands are used when ``omni.kit.commands`` is available so the
    group is a real entry on ``omni.kit.undo``.
    """
    if omni_usd is None or omni_undo is None:
        return _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="omni.usd is not available")
    stage = omni_usd.get_context().get_stage()
    if stage is None:
        return _result(plan if isinstance(plan, dict) else {}, ok=False, changed=False, detail="no open stage")
    if not isinstance(plan, dict):
        return _result({}, ok=False, changed=False, detail="plan must be an object")
    checked = _checked_plan(plan)
    if isinstance(checked, dict) and checked.get("ok") is False and "changed" in checked:
        return checked
    plan = checked
    blocked = _edit_blocked(stage, plan)
    if blocked:
        return _result(plan, ok=False, changed=False, detail=blocked)
    if omni_commands is not None:
        return _apply_via_commands(stage, plan)
    omni_undo.begin_group()
    try:
        return apply_plan_to_stage(stage, plan)
    finally:
        omni_undo.end_group()


def undo_last_on_open_stage() -> Dict[str, Any]:
    """Pop one Kit undo group. Does nothing to the stage when undo is absent."""
    if omni_undo is None or not callable(getattr(omni_undo, "undo", None)):
        return {"ok": False, "reverted": False, "detail": "omni.kit.undo is not available"}
    omni_undo.undo()
    return {"ok": True, "reverted": True, "detail": "reverted"}


def plan_from_before(before: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inverse plan for a headless revert. None when nothing was recorded."""
    if not isinstance(before, dict):
        return None
    op = before.get("op")
    path = before.get("prim_path") or ""
    if op == "set_transform":
        plan: Dict[str, Any] = {"op": "set_transform", "prim_path": path, "executable": True}
        found = False
        for key in ("scale", "translate", "rotate", "matrix"):
            if before.get(key) is not None:
                plan[key] = before[key]
                found = True
        return plan if found else None
    if op == "set_attribute":
        payload = {}
        for name, record in (before.get("attributes") or {}).items():
            if isinstance(record, dict) and record.get("existed") and "value" in record:
                payload[name] = record["value"]
        if not payload:
            return None
        return {"op": "set_attribute", "prim_path": path, "payload": payload, "executable": True}
    return None


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
    before = capture_before(stage, plan if isinstance(plan, dict) else {})
    result = apply_plan_to_stage(stage, plan)
    result["before"] = before
    result["saved"] = False
    if result.get("changed"):
        stage.Save()
        result["saved"] = True
    return result


def revert_note_file(stage_path: str, before: Dict[str, Any]) -> Dict[str, Any]:
    """Restore before-values on a ``.usd`` or ``.usda`` file and save."""
    inverse = plan_from_before(before)
    if inverse is None:
        result = _result(before if isinstance(before, dict) else {}, ok=False, changed=False, detail="before-values cannot be restored")
        result["saved"] = False
        return result
    return apply_note_file(stage_path, inverse)
