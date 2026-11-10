# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# Ordered fallback: legion-ollama, NVIDIA integrate, offline.

"""Provider chain used when ``LLM_MODE=chain``.

Default order is ``legion-ollama,nvidia,offline``. The first enabled and
reachable provider handles the turn. Offline is deterministic and never
returns tool calls or code actions, so it cannot edit a stage.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from ..chat.llm_openai_compat import LLMResponse, SYSTEM_PROMPT, build_payload
from . import http as http_mod
from .keyfile import load_nvidia_api_key, nvidia_key_path

logger = logging.getLogger("isaac_assist.providers")

DEFAULT_ORDER = "legion-ollama,nvidia,offline"
LEGION_DEFAULT_BASE = "http://127.0.0.1:11434/v1"
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
OFFLINE_TEXT = "The assistant is offline and will not execute any scene edit."

_KNOWN = {"legion-ollama", "nvidia", "offline"}


def provider_order() -> List[str]:
    raw = os.environ.get("ISAAC_ASSIST_PROVIDER_ORDER", "").strip()
    if not raw:
        raw = DEFAULT_ORDER
    order = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        if name not in _KNOWN:
            logger.info("unknown provider skipped; name=%s", name)
            continue
        order.append(name)
    return order or [item.strip() for item in DEFAULT_ORDER.split(",")]


def _timeout(env_name: str, default: float, upper: float) -> float:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.1, min(value, upper))


def probe_timeout() -> float:
    return _timeout("ISAAC_ASSIST_PROVIDER_PROBE_TIMEOUT", 0.5, 5.0)


def chat_timeout() -> float:
    return _timeout("ISAAC_ASSIST_PROVIDER_CHAT_TIMEOUT", 60.0, 300.0)


def _with_system(messages: List[Dict]) -> List[Dict]:
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)
    return list(messages)


def _parse_actions(text: str) -> List[Dict]:
    actions = []
    if text and "```python" in text:
        for block in text.split("```python")[1:]:
            code = block.split("```")[0].strip()
            if code:
                actions.append({"type": "code_snippet", "content": code})
    return actions


def _parse_chat_response(data: Dict) -> LLMResponse:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("parse_failed") from exc
    reply = message.get("content") or message.get("reasoning_content") or ""
    raw_tool_calls = message.get("tool_calls")
    tool_calls = None
    if raw_tool_calls:
        tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in raw_tool_calls
        ]
    reported = data.get("usage") or {}
    return LLMResponse(
        text=reply or "",
        actions=_parse_actions(reply or ""),
        tool_calls=tool_calls,
        usage=(
            int(reported.get("prompt_tokens", 0)),
            int(reported.get("completion_tokens", 0)),
        ),
    )


class OpenAICompatibleProvider:
    """One OpenAI-compatible chat endpoint. Tool calls are passed through."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str, enabled: bool):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.enabled = enabled

    async def reachable(self) -> bool:
        if not self.enabled:
            return False
        return await http_mod.probe_base(self.base_url, self.api_key, probe_timeout())

    async def complete(self, messages: List[Dict], context: Optional[Dict] = None) -> LLMResponse:
        if not self.enabled:
            raise RuntimeError(f"{self.name} disabled")
        payload = build_payload(self.model, _with_system(messages), context or {})
        data = await http_mod.post_json(
            self.base_url + "/chat/completions",
            self.api_key,
            payload,
            chat_timeout(),
        )
        return _parse_chat_response(data)


class OfflineProvider:
    """Deterministic local reply. Does not call tools or scene edits."""

    name = "offline"
    enabled = True
    model = "offline"
    api_key = ""

    async def reachable(self) -> bool:
        return True

    async def complete(self, messages: List[Dict], context: Optional[Dict] = None) -> LLMResponse:
        del messages, context
        return LLMResponse(text=OFFLINE_TEXT, actions=[], tool_calls=None)


def _legion_model() -> str:
    return (
        os.environ.get("LOCAL_MODEL_NAME")
        or os.environ.get("OLLAMA_MODEL")
        or "qwen3.5:35b"
    )


def _legion_base() -> str:
    return (os.environ.get("OLLAMA_OPENAI_BASE") or LEGION_DEFAULT_BASE).rstrip("/")


def build_providers(order: Optional[Sequence[str]] = None) -> List[Any]:
    """Build the configured providers. Disabled providers stay in the list."""
    names = list(order) if order is not None else provider_order()
    nvidia_key = None
    providers = []
    for name in names:
        if name == "legion-ollama":
            providers.append(
                OpenAICompatibleProvider(
                    name="legion-ollama",
                    base_url=_legion_base(),
                    model=_legion_model(),
                    api_key="ollama",
                    enabled=True,
                )
            )
        elif name == "nvidia":
            if nvidia_key is None:
                nvidia_key = load_nvidia_api_key(nvidia_key_path()) or ""
            model = os.environ.get("NVIDIA_MODEL", "").strip()
            enabled = bool(nvidia_key) and bool(model)
            if nvidia_key and not model:
                logger.info("nvidia provider disabled; model present: no; key present: yes")
            providers.append(
                OpenAICompatibleProvider(
                    name="nvidia",
                    base_url=NVIDIA_BASE,
                    model=model,
                    api_key=nvidia_key,
                    enabled=enabled,
                )
            )
        elif name == "offline":
            providers.append(OfflineProvider())
    return providers


class FallbackChainProvider:
    """Try providers in order. The first success wins. Offline is a success."""

    name = "chain"

    def __init__(self, providers: Optional[Sequence[Any]] = None):
        self.providers = list(providers) if providers is not None else build_providers()

    async def complete(self, messages: List[Dict], context: Optional[Dict] = None) -> LLMResponse:
        context = context or {}
        for provider in self.providers:
            if not getattr(provider, "enabled", False):
                logger.info("provider skipped; name=%s enabled=no", provider.name)
                continue
            if provider.name != "offline":
                try:
                    up = await provider.reachable()
                except Exception:
                    up = False
                if not up:
                    logger.info("provider skipped; name=%s reachable=no", provider.name)
                    continue
            try:
                return await provider.complete(messages, context)
            except Exception:
                logger.warning("provider failed; name=%s; falling back", provider.name)
        logger.info("provider chain exhausted; using offline")
        return await OfflineProvider().complete(messages, context)
