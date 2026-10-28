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
        timeout_s=s.approach_web_timeout_s,
        cache_ttl_s=s.approach_web_cache_ttl_s,
        cost_per_search_inr=getattr(s, "team_cost_per_search_inr", 1.0),
        now=pipeline.clock.now,
    )
    return ShoppingAssistant(pipeline, agent)
