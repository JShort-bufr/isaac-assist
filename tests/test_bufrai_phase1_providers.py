# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).

"""Provider order, 0600 key file, log redaction, and /providers/status."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytestmark = pytest.mark.l0

SECRET = "unit-test-nvidia-key-value"


def _write_key(path: Path, mode: int) -> None:
    path.write_text(f"NVIDIA_API_KEY={SECRET}\n", encoding="utf-8")
    path.chmod(mode)


def test_default_provider_order(monkeypatch):
    from service.isaac_assist_service.providers.chain import provider_order

    monkeypatch.delenv("ISAAC_ASSIST_PROVIDER_ORDER", raising=False)
    assert provider_order() == ["legion-ollama", "nvidia", "offline"]


def test_custom_provider_order_skips_unknown(monkeypatch):
    from service.isaac_assist_service.providers.chain import provider_order

    monkeypatch.setenv("ISAAC_ASSIST_PROVIDER_ORDER", "offline, nope, legion-ollama")
    assert provider_order() == ["offline", "legion-ollama"]


@pytest.mark.asyncio
async def test_fallback_uses_first_reachable_provider():
    from service.isaac_assist_service.chat.llm_openai_compat import LLMResponse
    from service.isaac_assist_service.providers.chain import FallbackChainProvider

    class Fake:
        def __init__(self, name, up, text):
            self.name = name
            self.enabled = True
            self.model = name
            self.calls = 0
            self._up = up
            self._text = text

        async def reachable(self):
            return self._up

        async def complete(self, messages, context=None):
            self.calls += 1
            return LLMResponse(text=self._text, actions=[], tool_calls=[{"id": "t", "type": "function", "function": {"name": "ping", "arguments": "{}"}}])

    first = Fake("legion-ollama", False, "local")
    second = Fake("nvidia", True, "cloud")
    chain = FallbackChainProvider([first, second])
    response = await chain.complete([{"role": "user", "content": "hi"}], {})
    assert response.text == "cloud"
    assert response.tool_calls[0]["function"]["name"] == "ping"
    assert first.calls == 0
    assert second.calls == 1


@pytest.mark.asyncio
async def test_unreachable_provider_falls_through_after_error():
    from service.isaac_assist_service.chat.llm_openai_compat import LLMResponse
    from service.isaac_assist_service.providers.chain import FallbackChainProvider, OFFLINE_TEXT

    class Down:
        name = "legion-ollama"
        enabled = True
        model = "codey-builder-64k"

        async def reachable(self):
            return True

        async def complete(self, messages, context=None):
            raise RuntimeError("down")

    class Up:
        name = "nvidia"
        enabled = True
        model = "nvidia-model"
        calls = 0

        async def reachable(self):
            return True

        async def complete(self, messages, context=None):
            self.calls += 1
            return LLMResponse(text="nvidia-ok", actions=[], tool_calls=None)

    nvidia = Up()
    response = await FallbackChainProvider([Down(), nvidia]).complete([{"role": "user", "content": "x"}], {})
    assert response.text == "nvidia-ok"
    assert nvidia.calls == 1
    assert OFFLINE_TEXT not in response.text


@pytest.mark.asyncio
async def test_offline_when_nothing_is_reachable_never_edits(monkeypatch):
    from service.isaac_assist_service.notes import apply as apply_mod
    from service.isaac_assist_service.providers.chain import OFFLINE_TEXT, FallbackChainProvider

    calls = []

    def spy(plan):
        calls.append(plan)
        return {"ok": True}

    monkeypatch.setattr(apply_mod, "apply_scene_edit", spy)

    class Down:
        def __init__(self, name):
            self.name = name
            self.enabled = True
            self.model = name

        async def reachable(self):
            return False

        async def complete(self, messages, context=None):
            raise AssertionError("complete should not run")

    response = await FallbackChainProvider(
        [Down("legion-ollama"), Down("nvidia")]
    ).complete([{"role": "user", "content": "edit the stage"}], {"tools": [{"type": "function"}]})
    assert response.text == OFFLINE_TEXT
    assert "scene edit" in response.text
    assert response.actions == []
    assert response.tool_calls is None
    assert calls == []


def test_key_file_mode_must_be_0600(tmp_path, caplog):
    from service.isaac_assist_service.providers.keyfile import load_nvidia_api_key

    path = tmp_path / "nvidia-api.env"
    _write_key(path, 0o644)
    with caplog.at_level(logging.DEBUG, logger="isaac_assist.providers"):
        loaded = load_nvidia_api_key(path)
    assert loaded is None
    assert SECRET not in caplog.text
    assert "key present: no" in caplog.text


def test_key_file_0600_loads_without_logging_the_value(tmp_path, caplog):
    from service.isaac_assist_service.providers.keyfile import load_nvidia_api_key

    path = tmp_path / "nvidia-api.env"
    _write_key(path, 0o600)
    with caplog.at_level(logging.DEBUG, logger="isaac_assist.providers"):
        loaded = load_nvidia_api_key(path)
    assert loaded == SECRET
    assert SECRET not in caplog.text
    assert "key present: yes" in caplog.text


def test_symlink_key_file_is_refused(tmp_path, caplog):
    from service.isaac_assist_service.providers.keyfile import load_nvidia_api_key

    target = tmp_path / "real.env"
    _write_key(target, 0o600)
    link = tmp_path / "link.env"
    link.symlink_to(target)
    with caplog.at_level(logging.DEBUG, logger="isaac_assist.providers"):
        loaded = load_nvidia_api_key(link)
    assert loaded is None
    assert SECRET not in caplog.text
    assert "key present: no" in caplog.text


def test_nvidia_provider_disabled_when_mode_is_not_0600(tmp_path, monkeypatch):
    from service.isaac_assist_service.providers.chain import build_providers

    path = tmp_path / "nvidia-api.env"
    _write_key(path, 0o644)
    monkeypatch.setenv("NVIDIA_API_KEY_FILE", str(path))
    monkeypatch.setenv("NVIDIA_MODEL", "unit-model")
    nvidia = next(item for item in build_providers(["nvidia"]) if item.name == "nvidia")
    assert nvidia.enabled is False
    assert nvidia.api_key == ""
    assert nvidia.model == "unit-model"


def test_nvidia_provider_enabled_only_with_0600_and_model(tmp_path, monkeypatch):
    from service.isaac_assist_service.providers.chain import build_providers

    path = tmp_path / "nvidia-api.env"
    _write_key(path, 0o600)
    monkeypatch.setenv("NVIDIA_API_KEY_FILE", str(path))
    monkeypatch.setenv("NVIDIA_MODEL", "unit-model")
    nvidia = next(item for item in build_providers(["nvidia"]) if item.name == "nvidia")
    assert nvidia.enabled is True
    assert nvidia.api_key == SECRET
    assert nvidia.model == "unit-model"
    assert nvidia.base_url == "https://integrate.api.nvidia.com/v1"


def test_llm_mode_local_stays_on_the_upstream_provider(monkeypatch):
    from service.isaac_assist_service.chat import provider_factory
    from service.isaac_assist_service.chat.llm_openai_compat import OpenAICompatProvider

    monkeypatch.setattr(provider_factory.config, "llm_mode", "local")
    monkeypatch.setattr(provider_factory.config, "local_model_name", "test-model")
    monkeypatch.setattr(provider_factory.config, "ollama_openai_base", "http://127.0.0.1:11434/v1")
    provider = provider_factory.get_llm_provider()
    assert isinstance(provider, OpenAICompatProvider)


def test_llm_mode_chain_selects_fallback(monkeypatch, tmp_path):
    from service.isaac_assist_service.chat import provider_factory
    from service.isaac_assist_service.providers.chain import FallbackChainProvider

    monkeypatch.setattr(provider_factory.config, "llm_mode", "chain")
    monkeypatch.setenv("NVIDIA_API_KEY_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("ISAAC_ASSIST_PROVIDER_ORDER", "legion-ollama,nvidia,offline")
    provider = provider_factory.get_llm_provider()
    assert isinstance(provider, FallbackChainProvider)
    assert [item.name for item in provider.providers] == ["legion-ollama", "nvidia", "offline"]


@pytest.mark.asyncio
async def test_providers_status_has_no_secrets(client, monkeypatch, tmp_path, caplog):
    from service.isaac_assist_service.providers import http as http_mod

    path = tmp_path / "nvidia-api.env"
    _write_key(path, 0o600)
    monkeypatch.setenv("NVIDIA_API_KEY_FILE", str(path))
    monkeypatch.setenv("NVIDIA_MODEL", "unit-model")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "codey-builder-64k")
    monkeypatch.setenv("OLLAMA_OPENAI_BASE", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("ISAAC_ASSIST_PROVIDER_ORDER", "legion-ollama,nvidia,offline")

    async def fake_probe(base_url, api_key, timeout_s):
        assert SECRET not in base_url
        return False

    monkeypatch.setattr(http_mod, "probe_base", fake_probe)
    with caplog.at_level(logging.DEBUG, logger="isaac_assist.providers"):
        response = await client.get("/api/v1/providers/status")
    assert response.status_code == 200
    body = response.json()
    assert body["order"] == ["legion-ollama", "nvidia", "offline"]
    assert SECRET not in response.text
    assert "api_key" not in response.text
    by_name = {item["name"]: item for item in body["providers"]}
    assert set(by_name) == {"legion-ollama", "nvidia", "offline"}
    for item in body["providers"]:
        assert set(item) == {"name", "enabled", "reachable", "model"}
    assert by_name["legion-ollama"]["model"] == "codey-builder-64k"
    assert by_name["legion-ollama"]["enabled"] is True
    assert by_name["legion-ollama"]["reachable"] is False
    assert by_name["nvidia"]["enabled"] is True
    assert by_name["nvidia"]["model"] == "unit-model"
    assert by_name["nvidia"]["reachable"] is False
    assert by_name["offline"]["reachable"] is True
    assert SECRET not in caplog.text
    assert "key present: yes" in caplog.text
