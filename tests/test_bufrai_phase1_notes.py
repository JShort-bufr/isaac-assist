# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Sticky note CRUD, sidecar round trip, proposals, and confirm-before-apply."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.isaac_assist_service.chat.llm_openai_compat import LLMResponse
from service.isaac_assist_service.notes import apply as apply_mod
from service.isaac_assist_service.notes.store import NoteStore
from service.isaac_assist_service.providers.chain import OFFLINE_TEXT, OfflineProvider

pytestmark = pytest.mark.l1


def _stage(tmp_path: Path) -> str:
    return str(tmp_path / "scene.usd")


def _note_body(stage: str, prim: str, comment: str) -> dict:
    return {
        "stage_path": stage,
        "prim_path": prim,
        "prim_type": "Cube",
        "key_attributes": {"size": 1},
        "world_transform": {"translate": [0, 1, 0], "rotate": [0, 0, 0], "scale": [1, 1, 1]},
        "region": {"x": 1, "y": 2, "width": 3, "height": 4},
        "comment": comment,
        "status": "applied",
        "proposal": {"op": "add_prim", "executable": True},
    }


async def _fake_plan(messages, context=None):
    return LLMResponse(
        text='{"op":"set_attribute","prim_path":"/World/Cube","payload":{"size":2}}',
        actions=[],
        tool_calls=None,
    )


async def _fake_offline(messages, context=None):
    return await OfflineProvider().complete(messages, context)


@pytest.fixture()
def spy(monkeypatch):
    calls = []

    def _apply(plan):
        calls.append(plan)
        return {"ok": True, "op": plan.get("op"), "prim_path": plan.get("prim_path", "")}

    monkeypatch.setattr(apply_mod, "apply_scene_edit", _apply)
    return calls


async def test_notes_crud_and_sidecar_round_trip(client, tmp_path, spy):
    stage = _stage(tmp_path)
    created = await client.post("/api/v1/notes", json=_note_body(stage, "/World/Cube", "make it red"))
    assert created.status_code == 200
    note = created.json()["note"]
    assert note["status"] == "draft"
    assert note["proposal"] is None
    assert note["prim_path"] == "/World/Cube"
    assert note["world_transform"]["translate"] == [0, 1, 0]
    assert note["region"]["width"] == 3
    assert spy == []

    listed = await client.get("/api/v1/notes", params={"stage_path": stage})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["notes"]] == [note["id"]]

    sidecar = Path(stage + ".notes.json")
    assert sidecar.is_file()
    on_disk = json.loads(sidecar.read_text(encoding="utf-8"))
    assert on_disk["notes"][0]["comment"] == "make it red"
    reloaded = NoteStore(stage)
    assert reloaded.get(note["id"])["key_attributes"] == {"size": 1}

    missing = await client.delete("/api/v1/notes", params={"stage_path": stage, "id": "missing"})
    assert missing.status_code == 404
    deleted = await client.delete("/api/v1/notes", params={"stage_path": stage, "id": note["id"]})
    assert deleted.status_code == 200
    assert NoteStore(stage).list_notes() == []
    assert spy == []


async def test_batch_send_proposes_each_note_without_applying(client, tmp_path, monkeypatch, spy):
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _fake_plan,
    )
    stage = _stage(tmp_path)
    ids = []
    for prim in ("/World/Cube", "/World/Sphere"):
        response = await client.post("/api/v1/notes", json=_note_body(stage, prim, f"edit {prim}"))
        ids.append(response.json()["note"]["id"])

    sent = await client.post("/api/v1/notes/send", json={"stage_path": stage, "ids": ids})
    assert sent.status_code == 200
    notes = sent.json()["notes"]
    assert len(notes) == 2
    assert spy == []
    for note in notes:
        assert note["status"] == "proposed"
        assert note["proposal"]["op"] == "set_attribute"
        assert note["proposal"]["executable"] is True
    stored = NoteStore(stage).list_notes()
    assert [item["status"] for item in stored] == ["proposed", "proposed"]


async def test_confirm_applies_once_and_reject_never_applies(client, tmp_path, monkeypatch, spy):
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _fake_plan,
    )
    stage = _stage(tmp_path)
    first = (await client.post("/api/v1/notes", json=_note_body(stage, "/World/A", "a"))).json()["note"]["id"]
    second = (await client.post("/api/v1/notes", json=_note_body(stage, "/World/B", "b"))).json()["note"]["id"]
    await client.post("/api/v1/notes/send", json={"stage_path": stage, "ids": [first, second]})
    assert spy == []

    rejected = await client.post(f"/api/v1/notes/{first}/reject", params={"stage_path": stage})
    assert rejected.status_code == 200
    assert rejected.json()["applied"] is False
    assert rejected.json()["note"]["status"] == "rejected"
    assert spy == []

    blocked = await client.post(f"/api/v1/notes/{first}/confirm", params={"stage_path": stage})
    assert blocked.status_code == 409
    assert spy == []

    confirmed = await client.post(f"/api/v1/notes/{second}/confirm", params={"stage_path": stage})
    assert confirmed.status_code == 200
    assert confirmed.json()["applied"] is True
    assert confirmed.json()["note"]["status"] == "applied"
    assert len(spy) == 1
    assert spy[0]["op"] == "set_attribute"
    assert spy[0]["executable"] is True

    again = await client.post(f"/api/v1/notes/{second}/confirm", params={"stage_path": stage})
    assert again.status_code == 409
    assert len(spy) == 1
    assert NoteStore(stage).get(second)["status"] == "applied"
    assert NoteStore(stage).get(first)["status"] == "rejected"


async def test_offline_send_and_confirm_never_edit(client, tmp_path, monkeypatch, spy):
    monkeypatch.setattr(
        "service.isaac_assist_service.notes.proposals.complete_with_chain",
        _fake_offline,
    )
    stage = _stage(tmp_path)
    note_id = (await client.post("/api/v1/notes", json=_note_body(stage, "/World/Cube", "move it"))).json()["note"]["id"]
    sent = await client.post("/api/v1/notes/send", json={"stage_path": stage, "ids": [note_id]})
    proposal = sent.json()["notes"][0]["proposal"]
    assert sent.json()["notes"][0]["status"] == "proposed"
    assert proposal["executable"] is False
    assert proposal["op"] == "none"
    assert "assistant is offline" in proposal["summary"]
    assert OFFLINE_TEXT in proposal["summary"]
    assert spy == []

    confirmed = await client.post(f"/api/v1/notes/{note_id}/confirm", params={"stage_path": stage})
    assert confirmed.status_code == 200
    assert confirmed.json()["applied"] is False
    assert confirmed.json()["note"]["status"] == "confirmed"
    assert spy == []


def test_apply_refuses_non_executable_plans():
    with pytest.raises(RuntimeError):
        apply_mod.apply_scene_edit({"op": "set_attribute", "executable": False})
    with pytest.raises(RuntimeError):
        apply_mod.apply_scene_edit({"op": "none", "executable": True})
