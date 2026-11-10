# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# OpenAI-compatible HTTP helpers that do not log response bodies or keys.

"""Small HTTP helpers for the provider chain.

Response bodies are not logged. Error text from a provider can echo request
headers, so failures are reported as a status code or exception type only.
"""

from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger("isaac_assist.providers")


def _headers(api_key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    return headers


async def probe_base(base_url: str, api_key: str, timeout_s: float) -> bool:
    """True when the OpenAI-compatible ``/models`` endpoint answers."""
    url = base_url.rstrip("/") + "/models"
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=_headers(api_key)) as response:
                return 200 <= response.status < 500
    except Exception:
        return False


async def post_json(url: str, api_key: str, payload: dict, timeout_s: float) -> dict:
    """POST JSON. Raises RuntimeError without including the response body."""
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=_headers(api_key)) as response:
                if response.status != 200:
                    await response.read()
                    logger.warning("provider http failure; http_status=%s", response.status)
                    raise RuntimeError(f"http_status={response.status}")
                data = await response.json(content_type=None)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("provider connection failure; error_type=%s", type(exc).__name__)
        raise RuntimeError(f"connection_failed={type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("parse_failed")
    return data
