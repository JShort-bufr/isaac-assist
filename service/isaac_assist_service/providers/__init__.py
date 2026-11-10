# Modified work, 2026 — isaac-assist-frame phase 1 (Isaac Sim 6.2).
# Derived from k3street/Omniverse_Nemotron_Ext (Apache-2.0).
# New provider fallback chain for the house-build phase 2 frame.

"""Ordered LLM providers for Isaac Assist phase 1.

The chain is selected with ``LLM_MODE=chain`` and does not replace the
upstream ``local`` / ``anthropic`` / ``openai`` / ``grok`` / ``cloud`` modes.
"""

from .chain import FallbackChainProvider, build_providers, provider_order

__all__ = ["FallbackChainProvider", "build_providers", "provider_order"]
