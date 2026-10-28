# ruff: noqa: E501
"""Build the planner gateway for the live pipeline. Returns None while the switch is off."""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger
from friday.planner.agents.web_lookup import WebLookupAgent
from friday.planner.gateway import PlannerGateway
from friday.planner.planner import ApproachPlanner, LLMDecider
from friday.planner.web import OpenAIWebSearch, UnavailableWebSearch, WebSearchPort

log = get_logger(__name__)


def web_provider(settings: Any) -> WebSearchPort:
    key = getattr(settings, "openai_api_key", None)
    if key is None:
        return UnavailableWebSearch()
    model = settings.approach_web_model or settings.openai_default_purpose_model
    return OpenAIWebSearch(key.get_secret_value(), model=model)


def build_planner(pipeline: Any) -> PlannerGateway | None:
    s = pipeline.c.settings
    if not getattr(s, "approach_planner_enabled", False):
        return None
    llm_decider = None
    if s.approach_use_llm and s.resolve_llm() == "openai":
        try:
            llm_decider = LLMDecider(pipeline.c.get("llm"), timeout_s=s.approach_decide_timeout_s)
        except Exception:  # noqa: BLE001 - the heuristic alone is a valid planner
            log.info("approach planner: no LLM client; using the deterministic decider only")
    web = WebLookupAgent(
        web_provider(s),
        timeout_s=s.approach_web_timeout_s,
        cache_ttl_s=s.approach_web_cache_ttl_s,
        now=pipeline.clock.now,
    )
    from friday.shopping.wiring import build_shopping

    return PlannerGateway(
        pipeline, planner=ApproachPlanner(llm_decider=llm_decider), web=web, ack_after_s=s.approach_ack_after_s,
        shopping=build_shopping(pipeline, web.provider),
    )
