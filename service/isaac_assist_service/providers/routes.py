# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# GET /api/v1/providers/status — names, flags, and model ids only.

"""Provider status. The payload has no API keys and no key file contents."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..config import config
from .chain import FallbackChainProvider

logger = logging.getLogger("isaac_assist.providers")
router = APIRouter()


def _public_view(provider, reachable: bool) -> dict:
    return {
        "name": provider.name,
        "enabled": bool(provider.enabled),
        "reachable": bool(reachable),
        "model": provider.model or "",
    }


@router.get("/status")
async def providers_status():
    chain = FallbackChainProvider()
    views = []
    for provider in chain.providers:
        reachable = False
        if provider.enabled:
            try:
                reachable = bool(await provider.reachable())
            except Exception:
                reachable = False
        views.append(_public_view(provider, reachable))
    logger.info(
        "provider status; count=%s",
        len(views),
    )
    return {
        "llm_mode": config.llm_mode,
        "order": [provider.name for provider in chain.providers],
        "providers": views,
    }
