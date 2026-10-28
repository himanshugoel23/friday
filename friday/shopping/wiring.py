# ruff: noqa: E501
"""Build the shopping assistant for the planner gateway. None unless FRIDAY_SHOPPING_ASSISTANT_ENABLED."""

from __future__ import annotations

from typing import Any

from friday.shopping.agent import ShoppingAgent
from friday.shopping.assistant import ShoppingAssistant
from friday.shopping.images import HttpOgImages


def build_shopping(pipeline: Any, provider: Any) -> ShoppingAssistant | None:
    s = pipeline.c.settings
    if not getattr(s, "shopping_assistant_enabled", False):
        return None
    agent = ShoppingAgent(
        provider,
        images=HttpOgImages() if getattr(s, "shopping_images_enabled", True) else None,
        overrides=_site_mcp_overrides(pipeline, provider),
        timeout_s=s.approach_web_timeout_s,
        cache_ttl_s=s.approach_web_cache_ttl_s,
        cost_per_search_inr=getattr(s, "team_cost_per_search_inr", 1.0),
        now=pipeline.clock.now,
    )
    return ShoppingAssistant(pipeline, agent)


def _site_mcp_overrides(pipeline: Any, provider: Any) -> dict[str, Any]:
    """Browser-first providers for Zepto / Blinkit / Instamart when FRIDAY_SITE_MCP_ENABLED (docs/SITE_MCP_DESIGN.md); else {}."""
    s = pipeline.c.settings
    if not getattr(s, "site_mcp_enabled", False):
        return {}
    try:
        from friday.sitemcp.wiring import shopping_overrides

        return shopping_overrides(s, provider, browser_stack=getattr(pipeline, "browser", None),
                                  timeout_s=s.approach_web_timeout_s, now=pipeline.clock.now)
    except Exception:  # noqa: BLE001 - the browser servers must never stop shopping from working
        from friday.core.logging import get_logger

        get_logger(__name__).exception("site mcp providers failed to build; using web search only")
        return {}
