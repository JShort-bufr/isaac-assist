# Modified work, 2026 — isaac-assist-frame phase 2 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Identical code_patch proposals collapse to one approval inside a turn."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from service.isaac_assist_service.chat.code_patches import dedupe_code_patches, same_code_patch

pytestmark = pytest.mark.l0


def test_whitespace_does_not_make_a_second_patch():
    first = {"code": "cube = 1\n", "description": "Make a cube"}
    spaced = {"code": "cube = 1", "description": "Make   a\ncube"}
    other = {"code": "cube = 2", "description": "Make a cube"}
    assert same_code_patch(first, spaced)
    assert not same_code_patch(first, other)
    kept = dedupe_code_patches([first, spaced, other, spaced])
    assert kept == [first, other]


async def test_message_actions_drop_duplicate_code_patches(client, monkeypatch):
    import service.isaac_assist_service.chat.routes as chat_routes

    mock_result = {
        "intent": "patch_request",
        "reply": "One cube.",
        "tool_calls": [],
        "code_patches": [
            {"code": "print('cube')\n", "description": "Create cube"},
            {"code": "print('cube')", "description": "Create   cube"},
            {"code": "print('sphere')", "description": "Create cube"},
        ],
    }
    monkeypatch.setattr(chat_routes.orchestrator, "handle_message", AsyncMock(return_value=mock_result))
    response = await client.post(
        "/api/v1/chat/message",
        json={"session_id": "s1", "message": "Add a cube"},
    )
    assert response.status_code == 200
    actions = response.json()["actions_to_approve"]
    assert len(actions) == 2
    assert actions[0]["type"] == "code_patch"
    assert actions[0]["code"] == "print('cube')\n"
    assert actions[1]["code"] == "print('sphere')"
