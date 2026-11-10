# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Nucleus and read-only stages fail closed. No Nucleus credentials.

"""Decide where a stage's notes live and whether an edit is allowed."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class StageAccessError(ValueError):
    """The stage path cannot be classified."""


class StageAccess:
    def __init__(
        self,
        stage_path: str,
        sidecar: Path,
        crop_dir: Path,
        kind: str,
        edits_allowed: bool,
        custom_data_allowed: bool,
        session_layer: str,
        session_layer_writable: bool,
        detail: str,
    ):
        self.stage_path = stage_path
        self.sidecar = sidecar
        self.crop_dir = crop_dir
        self.kind = kind
        self.edits_allowed = edits_allowed
        self.custom_data_allowed = custom_data_allowed
        self.session_layer = session_layer
        self.session_layer_writable = session_layer_writable
        self.detail = detail


def local_notes_root() -> Path:
    override = os.environ.get("BUFRAI_NOTES_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "bufrai" / "isaac-assist" / "notes"


def stage_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_stage(
    stage_path: str,
    *,
    read_only: bool = False,
    session_layer: str = "",
    session_layer_writable: bool = False,
) -> StageAccess:
    if not stage_path or not str(stage_path).strip():
        raise StageAccessError("stage_path is required")
    text = str(stage_path).strip()
    layer = (session_layer or "").strip()
    session_ok = bool(layer) and bool(session_layer_writable)
    if "://" in text:
        return _remote(text, layer, session_layer_writable, session_ok)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise StageAccessError("stage_path must be absolute")
    file_locked = path.exists() and not os.access(path, os.W_OK)
    if read_only or file_locked:
        detail = "" if session_ok else "stage is read-only; confirm and apply are refused"
        return _hashed(
            str(path),
            kind="readonly",
            layer=layer,
            session_layer_writable=bool(session_layer_writable),
            edits_allowed=session_ok,
            detail=detail,
        )
    return StageAccess(
        stage_path=str(path),
        sidecar=path.parent / f"{path.name}.notes.json",
        crop_dir=path.parent / f"{path.name}.notes",
        kind="local",
        edits_allowed=True,
        custom_data_allowed=True,
        session_layer=layer,
        session_layer_writable=bool(session_layer_writable),
        detail="",
    )


def _remote(text: str, layer: str, session_layer_writable: bool, session_ok: bool) -> StageAccess:
    if text.startswith("omniverse://"):
        detail = "" if session_ok else "Nucleus stage is read-only; confirm and apply are refused"
        kind = "nucleus"
    else:
        detail = "" if session_ok else "URL stage is read-only; confirm and apply are refused"
        kind = "url"
    return _hashed(
        text,
        kind=kind,
        layer=layer,
        session_layer_writable=session_layer_writable,
        edits_allowed=session_ok,
        detail=detail,
    )


def _hashed(
    text: str,
    *,
    kind: str,
    layer: str,
    session_layer_writable: bool,
    edits_allowed: bool,
    detail: str,
) -> StageAccess:
    digest = stage_digest(text)
    root = local_notes_root()
    return StageAccess(
        stage_path=text,
        sidecar=root / f"{digest}.notes.json",
        crop_dir=root / f"{digest}.notes",
        kind=kind,
        edits_allowed=edits_allowed,
        custom_data_allowed=False,
        session_layer=layer,
        session_layer_writable=bool(session_layer_writable),
        detail=detail,
    )
