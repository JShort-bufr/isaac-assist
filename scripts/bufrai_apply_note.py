# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Headless sticky-note apply. Run with Isaac Sim's ./python.sh so pxr imports.

"""Apply one confirmed sticky note to a USD file on disk.

Isaac's Python has pxr. From the repo root:

    ~/isaacsim/python.sh scripts/bufrai_apply_note.py --stage /path/scene.usda

The sidecar is ``<stage>.notes.json``. The note must already be ``confirmed``
and its proposal must be executable. A ``proposed`` note is refused. After the
file changes and saves, the sidecar status becomes ``applied``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EXT_ROOT = Path(__file__).resolve().parents[1] / "exts" / "isaac_6.2" / "omni.isaac.assist"
if str(_EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXT_ROOT))

from omni.isaac.assist.executor.note_apply import apply_note_file


def sidecar_for(stage_path: str) -> Path:
    path = Path(stage_path)
    return path.parent / f"{path.name}.notes.json"


def load_sidecar(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def select_confirmed_note(notes: list, note_id: str) -> dict:
    if note_id:
        matches = [note for note in notes if note.get("id") == note_id]
        if len(matches) != 1:
            raise ValueError("note id was not found")
        note = matches[0]
    else:
        matches = [note for note in notes if note.get("status") == "confirmed"]
        if len(matches) != 1:
            raise ValueError("pass --note-id; the sidecar does not have exactly one confirmed note")
        note = matches[0]
    if note.get("status") != "confirmed":
        raise ValueError("confirm the note before applying it")
    proposal = note.get("proposal") or {}
    if not proposal.get("executable"):
        raise ValueError("the confirmed note has no executable plan")
    return note


def mark_note_applied(path: Path, note_id: str) -> None:
    data = load_sidecar(path)
    notes = data.get("notes") or []
    for note in notes:
        if note.get("id") == note_id:
            note["status"] = "applied"
            break
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(argv: list) -> int:
    parser = argparse.ArgumentParser(description="Apply a confirmed sticky note to a USD file")
    parser.add_argument("--stage", required=True, help="Local .usd or .usda file")
    parser.add_argument("--note-id", default="", help="Sidecar note id. Required when several notes are confirmed.")
    parser.add_argument("--sidecar", default="", help="Override <stage>.notes.json")
    args = parser.parse_args(argv)
    stage_path = str(Path(args.stage).expanduser())
    sidecar = Path(args.sidecar).expanduser() if args.sidecar else sidecar_for(stage_path)
    if not sidecar.is_file():
        print(json.dumps({"ok": False, "changed": False, "detail": "sidecar is missing"}))
        return 1
    try:
        note = select_confirmed_note(load_sidecar(sidecar).get("notes") or [], args.note_id)
    except ValueError as exc:
        print(json.dumps({"ok": False, "changed": False, "detail": str(exc)}))
        return 2
    proposal = dict(note.get("proposal") or {})
    if not proposal.get("prim_path"):
        proposal["prim_path"] = note.get("prim_path") or ""
    result = apply_note_file(stage_path, proposal)
    if result.get("changed") and result.get("saved"):
        mark_note_applied(sidecar, note["id"])
        result["status"] = "applied"
        print(json.dumps(result))
        return 0
    result["status"] = note.get("status")
    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
