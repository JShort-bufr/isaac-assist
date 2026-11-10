# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Service entry to the extension USD type gate. One implementation.

"""Load the extension's USD type gate.

Confirm and the Kit apply path share ``executor/usd_types.py`` so a scalar
scale is normalized once and a mismatched payload is refused in both places.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[3]
    / "exts"
    / "isaac_6.2"
    / "omni.isaac.assist"
    / "omni"
    / "isaac"
    / "assist"
    / "executor"
    / "usd_types.py"
)

_spec = importlib.util.spec_from_file_location("bufrai_usd_types", _PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"usd type gate is missing at {_PATH}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

attribute_type = _module.attribute_type
prepare_plan = _module.prepare_plan
