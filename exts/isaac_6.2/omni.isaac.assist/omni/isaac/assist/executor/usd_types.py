# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Fail-closed USD type gate for sticky-note proposals.

"""Normalize and validate a sticky-note plan before any stage edit.

A scalar scale is a uniform double3. Every other known attribute must
already match its USD type. A mismatch is not applied.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional, Tuple

_SKIP = {
    "attribute",
    "arguments",
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
    "session_layer",
    "session_layer_writable",
    "stage_read_only",
    "summary",
    "tool",
    "translate",
    "type",
    "value",
}

_DOUBLE3 = {
    "xformOp:scale",
    "xformOp:translate",
    "xformOp:rotateXYZ",
    "xformOp:rotateXZY",
    "xformOp:rotateYXZ",
    "xformOp:rotateYZX",
    "xformOp:rotateZXY",
    "xformOp:rotateZYX",
}

_DOUBLE = {
    "xformOp:rotateX",
    "xformOp:rotateY",
    "xformOp:rotateZ",
    "size",
    "radius",
    "height",
    "focalLength",
}

_TOKEN = {"visibility", "purpose", "orientation", "axis"}

_OPS = {"set_attribute", "set_transform", "add_prim"}


def attribute_type(name: str) -> Optional[str]:
    """USD type name for a known attribute, or None when the name is unknown."""
    if name in _DOUBLE3:
        return "double3"
    if name in _DOUBLE:
        return "double"
    if name in _TOKEN:
        return "token"
    if name == "xformOp:transform":
        return "matrix4d"
    if name == "xformOp:orient":
        return "quatd"
    if name == "doubleSided":
        return "bool"
    return None


def prepare_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{ok, plan, error}``.

    ``ok`` is false when the plan must not be applied. Scalar scale values
    are rewritten to ``[s, s, s]`` on the returned copy.
    """
    if not isinstance(plan, dict):
        return {"ok": False, "plan": {}, "error": "type mismatch: plan must be an object"}
    copied = copy.deepcopy(plan)
    op = copied.get("op")
    if op not in _OPS:
        return {"ok": True, "plan": copied, "error": ""}
    if op == "set_transform":
        return _prepare_transform(copied)
    if op == "set_attribute":
        return _prepare_attribute(copied)
    return _prepare_add(copied)


def _prepare_transform(plan: Dict[str, Any]) -> Dict[str, Any]:
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else None
    holders = [plan] if payload is None else [plan, payload]
    for key in ("scale", "translate", "rotate", "matrix"):
        for holder in holders:
            if key not in holder or holder.get(key) is None:
                continue
            if key == "scale":
                normalized, error = _check_scale(holder[key])
            elif key == "matrix":
                normalized, error = _check_matrix(holder[key])
            else:
                normalized, error = _check_vec3(holder[key], f"set_transform {key}")
            if error:
                return {"ok": False, "plan": plan, "error": error}
            holder[key] = normalized
    return {"ok": True, "plan": plan, "error": ""}


def _prepare_attribute(plan: Dict[str, Any]) -> Dict[str, Any]:
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else None
    name = plan.get("attribute") or (payload or {}).get("attribute") or (payload or {}).get("name")
    if name and ("value" in plan or (isinstance(payload, dict) and "value" in payload)):
        if "value" in plan:
            normalized, error = _check_attr(str(name), plan.get("value"))
            if error:
                return {"ok": False, "plan": plan, "error": error}
            plan["value"] = normalized
        else:
            normalized, error = _check_attr(str(name), payload.get("value"))
            if error:
                return {"ok": False, "plan": plan, "error": error}
            payload["value"] = normalized
        return {"ok": True, "plan": plan, "error": ""}

    for holder in (payload, plan):
        if not isinstance(holder, dict):
            continue
        for key, value in list(holder.items()):
            if key in _SKIP or value is None or key == "payload":
                continue
            normalized, error = _check_attr(str(key), value)
            if error:
                return {"ok": False, "plan": plan, "error": error}
            holder[key] = normalized
    return {"ok": True, "plan": plan, "error": ""}


def _prepare_add(plan: Dict[str, Any]) -> Dict[str, Any]:
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    type_name = plan.get("prim_type")
    if type_name is None:
        type_name = payload.get("prim_type") or payload.get("type")
    if type_name is not None and not isinstance(type_name, str):
        return {
            "ok": False,
            "plan": plan,
            "error": f"type mismatch: prim_type expects a string, got {_describe(type_name)}",
        }
    return {"ok": True, "plan": plan, "error": ""}


def _check_attr(name: str, value: Any) -> Tuple[Any, Optional[str]]:
    kind = attribute_type(name)
    if kind is None:
        if name.startswith("xformOp:"):
            return None, f"type mismatch: unknown xform op {name}"
        return value, None
    if kind == "double3":
        if name == "xformOp:scale":
            return _check_scale(value, label=name)
        return _check_vec3(value, name)
    if kind == "double":
        if _is_number(value):
            return float(value), None
        return None, f"type mismatch: {name} expects double, got {_describe(value)}"
    if kind == "matrix4d":
        return _check_matrix(value, label=name)
    if kind == "quatd":
        if (
            isinstance(value, (list, tuple))
            and len(value) == 4
            and all(_is_number(item) for item in value)
        ):
            return [float(item) for item in value], None
        return None, f"type mismatch: {name} expects quatd, got {_describe(value)}"
    if kind == "bool":
        if isinstance(value, bool):
            return value, None
        return None, f"type mismatch: {name} expects bool, got {_describe(value)}"
    if kind == "token":
        if isinstance(value, str):
            return value, None
        return None, f"type mismatch: {name} expects token, got {_describe(value)}"
    return None, f"type mismatch: {name} has unsupported type {kind}"


def _check_scale(value: Any, label: str = "scale") -> Tuple[Any, Optional[str]]:
    if _is_number(value):
        number = float(value)
        return [number, number, number], None
    if _is_vec3(value):
        return [float(item) for item in value], None
    return None, f"type mismatch: {label} expects double3, got {_describe(value)}"


def _check_vec3(value: Any, label: str) -> Tuple[Any, Optional[str]]:
    if _is_vec3(value):
        return [float(item) for item in value], None
    return None, f"type mismatch: {label} expects double3, got {_describe(value)}"


def _check_matrix(value: Any, label: str = "matrix") -> Tuple[Any, Optional[str]]:
    if (
        isinstance(value, list)
        and len(value) == 4
        and all(
            isinstance(row, (list, tuple)) and len(row) == 4 and all(_is_number(item) for item in row)
            for row in value
        )
    ):
        return [[float(item) for item in row] for row in value], None
    return None, f"type mismatch: {label} expects matrix4d, got {_describe(value)}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_vec3(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_is_number(item) for item in value)
    )


def _describe(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, float):
        return f"float {value}"
    if isinstance(value, int):
        return f"int {value}"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return f"list[{len(value)}]"
    return type(value).__name__
