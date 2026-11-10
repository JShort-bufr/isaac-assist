# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Phase 2 sticky notes: region crops, batch review, customData, Nucleus, undo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.isaac_assist_service.chat.llm_openai_compat import LLMResponse
from service.isaac_assist_service.notes.store import NoteStore

pytestmark = pytest.mark.l1


def _stage(tmp_path: Path) -> str:
    return str(tmp_path / "scene.usd")


def _body(stage: str, prim: str, comment: str, **extra) -> dict:
    payload = {
        "stage_path": stage,
        "prim_path": prim,
        "prim_type": "Cube",
        "key_attributes": {"size": 1},
        "comment": comment,
    }
    payload.update(extra)
    return payload


def _llm(text: str):
    async def _complete(messages, context=None):
        return LLMResponse(text=text, actions=[], tool_calls=None)

    return _complete


def _llm_by_comment():
    async def _complete(messages, context=None):
        content = messages[0]["content"]
        if "bad-scale" in content:
            text = '{"op":"set_attribute","prim_path":"/World/Cube","payload":{"xformOp:scale":"wide"}}'
        elif "scalar-scale" in content:
            text = '{"op":"set_attribute","prim_path":"/World/Cube","payload":{"xformOp:scale":2.0}}'
        elif "scalar-translate" in content:
            text = '{"op":"set_transform","prim_path":"/World/Cube","translate":1.0}'
        elif "uniform-scale" in content:
            text = '{"op":"set_transform","prim_path":"/World/Cube","scale":2}'
        elif "miss" in content:
            text = '{"op":"set_attribute","prim_path":"/World/Miss","payload":{"size":1}}'
        else:
            text = '{"op":"set_attribute","prim_path":"/World/A","payload":{"size":2}}'
        return LLMResponse(text=text, actions=[], tool_calls=None)

    return _complete


@pytest.fixture()
def notes_dir(tmp_path, monkeypatch):
    root = tmp_path / "bufrai-notes"
    monkeypatch.setenv("BUFRAI_NOTES_DIR", str(root))
    return root


async def _propose(client, stage: str, prim: str, comment: str, **extra) -> str:
    created = await client.post("/api/v1/notes", json=_body(stage, prim, comment, **extra))
    assert created.status_code == 200
    note_id = created.json()["note"]["id"]
    sent = await client.post("/api/v1/notes/send", json={"stage_path": stage, "ids": [note_id]})
    assert sent.status_code == 200
    return note_id


async def test_region_stores_viewport_and_crop_path(client, tmp_path):
    stage = _stage(tmp_path)
    created = await client.post(
        "/api/v1/notes",
        json=_body(
            stage,
            "/World/Cube",
            "crop",
            region={"x": 10, "y": 20, "w": 30, "h": 40, "viewport": {"width": 800, "height": 600}},
        ),
    )
    assert created.status_code == 200
    note = created.json()["note"]
    assert note["region"]["w"] == 30
    assert note["region"]["h"] == 40
    assert note["region"]["width"] == 30
    assert note["region"]["viewport"] == {"width": 800, "height": 600}
    assert note["crop_path"].endswith(f"{note['id']}.png")
    assert note["crop_path"].endswith(f".notes/{note['id']}.png")
    assert created.json()["custom_data_allowed"] is True
    assert created.json()["custom_data"]["/World/Cube"][note["id"]]["comment"] == "crop"

    missing = await client.post(
        "/api/v1/notes",
        json=_body(stage, "/World/Cube", "bad", region={"x": 1, "y": 2}),
    )
    assert missing.status_code == 400
    relative = await client.post("/api/v1/notes", json=_body("scene.usd", "/World/Cube", "rel"))
    assert relative.status_code == 400
    empty = await client.post("/api/v1/notes", json=_body("  ", "/World/Cube", "empty"))
    assert empty.status_code == 400


async def test_scalar_scale_is_normalized_and_type_mismatch_is_not_applied(client, tmp_path, monkeypatch):
    from service.isaac_assist_service.notes import kit_apply

    calls = []

    async def kit_up():
        return True

    async def exec_sync(code, timeout=30):
        calls.append(code)
        return {
            "success": True,
            "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "changed": true, "detail": "set_attribute", "before": {"op": "set_attribute"}}',
        }

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_up)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm_by_comment(),
    )
    stage = _stage(tmp_path)
    scalar = await _propose(client, stage, "/World/Cube", "scalar-scale")
    confirmed = await client.post(f"/api/v1/notes/{scalar}/confirm", params={"stage_path": stage})
    assert confirmed.status_code == 200
    assert confirmed.json()["applied"] is True
    assert confirmed.json()["note"]["status"] == "applied"
    assert confirmed.json()["note"]["proposal"]["payload"]["xformOp:scale"] == [2.0, 2.0, 2.0]
    assert "[2.0,2.0,2.0]" in calls[0]

    uniform = await _propose(client, stage, "/World/Cube", "uniform-scale")
    calls.clear()
    confirmed = await client.post(f"/api/v1/notes/{uniform}/confirm", params={"stage_path": stage})
    assert confirmed.json()["applied"] is True
    assert confirmed.json()["note"]["proposal"]["scale"] == [2.0, 2.0, 2.0]

    bad = await _propose(client, stage, "/World/Cube", "bad-scale")
    calls.clear()
    refused = await client.post(f"/api/v1/notes/{bad}/confirm", params={"stage_path": stage})
    assert refused.status_code == 200
    assert refused.json()["applied"] is False
    assert refused.json()["note"]["status"] == "rejected"
    assert "type mismatch" in refused.json()["note"]["error"]
    assert "xformOp:scale" in refused.json()["error"]
    assert calls == []

    translate = await _propose(client, stage, "/World/Cube", "scalar-translate")
    refused = await client.post(f"/api/v1/notes/{translate}/confirm", params={"stage_path": stage})
    assert refused.json()["applied"] is False
    assert refused.json()["note"]["status"] == "rejected"
    assert "translate" in refused.json()["note"]["error"]
    assert calls == []


async def test_batch_review_reports_partial_failures(client, tmp_path, monkeypatch):
    from service.isaac_assist_service.notes import kit_apply

    calls = []

    async def kit_up():
        return True

    async def exec_sync(code, timeout=30):
        calls.append(code)
        if "/World/Miss" in code:
            return {
                "success": True,
                "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": false, "changed": false, "detail": "prim is not on the stage"}',
            }
        return {
            "success": True,
            "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "changed": true, "detail": "set_attribute"}',
        }

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_up)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm_by_comment(),
    )
    stage = _stage(tmp_path)
    good = await _propose(client, stage, "/World/A", "good")
    bad = await _propose(client, stage, "/World/Cube", "bad-scale")
    missed = await _propose(client, stage, "/World/Miss", "miss")
    reviewed = await client.post(
        "/api/v1/notes/review",
        json={"stage_path": stage, "action": "confirm", "ids": [good, bad, missed]},
    )
    assert reviewed.status_code == 200
    by_id = {item["id"]: item for item in reviewed.json()["results"]}
    assert by_id[good]["applied"] is True
    assert by_id[good]["status"] == "applied"
    assert by_id[bad]["applied"] is False
    assert by_id[bad]["status"] == "rejected"
    assert "type mismatch" in by_id[bad]["detail"]
    assert by_id[missed]["applied"] is False
    assert by_id[missed]["status"] == "confirmed"
    assert by_id[missed]["detail"] == "prim is not on the stage"
    assert len(calls) == 2

    rejected = await client.post(
        "/api/v1/notes/review",
        json={"stage_path": stage, "action": "reject", "ids": [missed, "missing-id"]},
    )
    assert rejected.status_code == 200
    rows = {item["id"]: item for item in rejected.json()["results"]}
    assert rows[missed]["status"] == "rejected"
    assert rows[missed]["applied"] is False
    assert rows["missing-id"]["ok"] is False

    invalid = await client.post("/api/v1/notes/review", json={"stage_path": stage, "action": "drop", "ids": [good]})
    assert invalid.status_code == 400
    empty = await client.post("/api/v1/notes/review", json={"stage_path": stage, "action": "reject", "ids": []})
    assert empty.status_code == 400


async def test_custom_data_reconcile_lets_sidecar_win(client, tmp_path):
    stage = _stage(tmp_path)
    created = await client.post("/api/v1/notes", json=_body(stage, "/World/Cube", "from sidecar"))
    note = created.json()["note"]
    merged = await client.post(
        "/api/v1/notes/reconcile",
        json={
            "stage_path": stage,
            "prims": {
                "/World/Cube": {
                    note["id"]: {"comment": "prim copy", "status": "applied", "created_at": note["created_at"]},
                    "only-on-prim": {"comment": "recovered", "status": "draft", "created_at": "2026-11-10T00:00:00+00:00"},
                }
            },
        },
    )
    assert merged.status_code == 200
    notes = {item["id"]: item for item in merged.json()["notes"]}
    assert notes[note["id"]]["comment"] == "from sidecar"
    assert notes[note["id"]]["status"] == "draft"
    assert notes["only-on-prim"]["comment"] == "recovered"
    assert notes["only-on-prim"]["prim_path"] == "/World/Cube"
    custom = merged.json()["custom_data"]["/World/Cube"]
    assert custom[note["id"]]["status"] == "draft"
    assert custom[note["id"]]["comment"] == "from sidecar"
    assert NoteStore(stage).get("only-on-prim")["comment"] == "recovered"


async def test_nucleus_and_readonly_fail_closed_unless_session_layer(client, tmp_path, monkeypatch, notes_dir):
    from service.isaac_assist_service.notes import kit_apply

    calls = []

    async def kit_up():
        return True

    async def exec_sync(code, timeout=30):
        calls.append(code)
        return {
            "success": True,
            "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "changed": true, "detail": "set_attribute"}',
        }

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_up)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm('{"op":"set_attribute","prim_path":"/World/Cube","payload":{"size":2}}'),
    )
    url = "omniverse://localhost/Projects/scene.usd"
    created = await client.post("/api/v1/notes", json=_body(url, "/World/Cube", "nucleus"))
    assert created.status_code == 200
    assert created.json()["edits_allowed"] is False
    assert created.json()["custom_data"] is None
    assert created.json()["custom_data_allowed"] is False
    note_id = created.json()["note"]["id"]
    sidecar = next(notes_dir.glob("*.notes.json"))
    assert json.loads(sidecar.read_text(encoding="utf-8"))["notes"][0]["id"] == note_id
    assert NoteStore(url).path == sidecar

    await client.post("/api/v1/notes/send", json={"stage_path": url, "ids": [note_id]})
    refused = await client.post(f"/api/v1/notes/{note_id}/confirm", params={"stage_path": url})
    assert refused.status_code == 409
    assert "Nucleus" in refused.json()["detail"]
    assert calls == []
    assert NoteStore(url).get(note_id)["status"] == "proposed"

    allowed = await client.post(
        f"/api/v1/notes/{note_id}/confirm",
        params={"stage_path": url, "session_layer": "session", "session_layer_writable": "true"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["applied"] is True
    assert allowed.json()["custom_data"] is None
    assert "session_layer" in calls[0]

    locked = tmp_path / "locked.usd"
    locked.write_text("#usda 1.0\n", encoding="utf-8")
    locked_id = (
        await client.post(
            "/api/v1/notes",
            json=_body(str(locked), "/World/Cube", "locked", read_only=True),
        )
    ).json()["note"]["id"]
    await client.post(
        "/api/v1/notes/send",
        json={"stage_path": str(locked), "ids": [locked_id], "read_only": True},
    )
    calls.clear()
    readonly = await client.post(
        f"/api/v1/notes/{locked_id}/confirm",
        params={"stage_path": str(locked), "read_only": "true"},
    )
    assert readonly.status_code == 409
    assert "read-only" in readonly.json()["detail"]
    assert calls == []
    assert NoteStore(str(locked), read_only=True).kind == "readonly"


async def test_serializable_kit_failure_rejects_with_the_kit_error(client, tmp_path, monkeypatch):
    from service.isaac_assist_service.notes import kit_apply

    detail = "Type mismatch for </World/Cube.st>: expected 'GfVec2f', got 'vector<VtValue, allocator<VtValue> >'"
    payload = {
        "ok": False,
        "changed": False,
        "command_failed": True,
        "op": "set_attribute",
        "prim_path": "/World/Cube",
        "detail": detail,
        "before": {
            "op": "set_attribute",
            "prim_path": "/World/Cube",
            "attributes": {"st": {"existed": True, "value": [0.25, 0.5]}},
        },
    }
    encoded = json.dumps(payload)

    async def kit_up():
        return True

    async def exec_sync(code, timeout=30):
        return {"success": True, "output": "ISAAC_ASSIST_NOTE_RESULT " + encoded}

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_up)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm('{"op":"set_attribute","prim_path":"/World/Cube","payload":{"st":[0.25,0.5]}}'),
    )
    stage = _stage(tmp_path)
    note_id = await _propose(client, stage, "/World/Cube", "set st")
    refused = await client.post(f"/api/v1/notes/{note_id}/confirm", params={"stage_path": stage})
    assert refused.status_code == 200
    body = refused.json()
    assert body["applied"] is False
    assert body["note"]["status"] == "rejected"
    assert "GfVec2f" in body["note"]["error"]
    assert NoteStore(stage).get(note_id)["status"] == "rejected"


async def test_kit_command_failure_rejects_the_note(client, tmp_path, monkeypatch):
    from service.isaac_assist_service.notes import kit_apply

    async def kit_up():
        return True

    async def exec_sync(code, timeout=30):
        detail = "Type mismatch for </World/Cube.xformOp:scale>: expected 'GfVec3d', got 'vector<VtValue, allocator<VtValue> >'"
        return {
            "success": True,
            "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": false, "changed": false, "command_failed": true, "detail": "%s"}' % detail,
        }

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_up)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm('{"op":"set_attribute","prim_path":"/World/Cube","payload":{"xformOp:scale":4}}'),
    )
    stage = _stage(tmp_path)
    note_id = await _propose(client, stage, "/World/Cube", "scale by 4")
    refused = await client.post(f"/api/v1/notes/{note_id}/confirm", params={"stage_path": stage})
    assert refused.status_code == 200
    body = refused.json()
    assert body["applied"] is False
    assert body["note"]["status"] == "rejected"
    assert "GfVec3d" in body["note"]["error"]
    assert body["note"]["status"] != "confirmed"
    assert NoteStore(stage).get(note_id)["status"] == "rejected"


async def test_undo_uses_kit_and_fails_closed(client, tmp_path, monkeypatch):
    from service.isaac_assist_service.notes import kit_apply

    alive = {"value": True}
    undos = []

    async def kit_alive():
        return alive["value"]

    async def exec_sync(code, timeout=30):
        if "undo_last_on_open_stage" in code:
            undos.append(code)
            if not alive["value"]:
                return {"success": False, "output": ""}
            return {
                "success": True,
                "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "reverted": true, "detail": "reverted"}',
            }
        return {
            "success": True,
            "output": 'ISAAC_ASSIST_NOTE_RESULT {"ok": true, "changed": true, "detail": "set_attribute"}',
        }

    monkeypatch.setattr(kit_apply.kit_tools, "is_kit_rpc_alive", kit_alive)
    monkeypatch.setattr(kit_apply.kit_tools, "exec_sync", exec_sync)
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _llm('{"op":"set_attribute","prim_path":"/World/Cube","payload":{"size":2}}'),
    )
    stage = _stage(tmp_path)
    first = await _propose(client, stage, "/World/A", "first")
    second = await _propose(client, stage, "/World/B", "second")
    await client.post(f"/api/v1/notes/{first}/confirm", params={"stage_path": stage})
    await client.post(f"/api/v1/notes/{second}/confirm", params={"stage_path": stage})

    draft = (await client.post("/api/v1/notes", json=_body(stage, "/World/C", "draft"))).json()["note"]["id"]
    not_applied = await client.post(f"/api/v1/notes/{draft}/undo", params={"stage_path": stage})
    assert not_applied.status_code == 409

    skipped = await client.post(f"/api/v1/notes/{first}/undo", params={"stage_path": stage})
    assert skipped.status_code == 409
    assert "last applied" in skipped.json()["detail"]
    assert undos == []

    alive["value"] = False
    down = await client.post(f"/api/v1/notes/{second}/undo", params={"stage_path": stage})
    assert down.status_code == 200
    assert down.json()["reverted"] is False
    assert down.json()["kit_connected"] is False
    assert NoteStore(stage).get(second)["status"] == "applied"

    alive["value"] = True
    undone = await client.post(f"/api/v1/notes/{second}/undo", params={"stage_path": stage})
    assert undone.status_code == 200
    assert undone.json()["reverted"] is True
    assert undone.json()["note"]["status"] == "reverted"
    assert "undo_last_on_open_stage" in undos[0]
    assert NoteStore(stage).get(second)["status"] == "reverted"

    previous = await client.post(f"/api/v1/notes/{first}/undo", params={"stage_path": stage})
    assert previous.status_code == 200
    assert previous.json()["note"]["status"] == "reverted"
