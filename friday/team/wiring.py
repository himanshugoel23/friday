# ruff: noqa: E501
"""Build the team for the live pipeline. Returns None unless a switch is on. Everything is in-process by
default (no sockets, no extra process); HTTP is only added when ``FRIDAY_A2A_HTTP_ENABLED``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import TaskBudget
from friday.a2a.server import A2AServer
from friday.a2a.transport import InProcessTransport
from friday.core.logging import get_logger
from friday.planner.agents.web_lookup import WebLookupAgent
from friday.planner.wiring import web_provider
from friday.speech.query_agent import QueryUnderstandingAgent
from friday.speech.userdict import UserDictionary
from friday.team.food import SiteAgent
from friday.team.gateway import TeamGateway
from friday.team.knowledge import KnowledgeStore
from friday.team.pm import ProjectManager
from friday.team.web_agent import WebLookupSpecialist

log = get_logger(__name__)


@dataclass
class Team:
    store: KnowledgeStore
    transport: InProcessTransport
    servers: dict[str, A2AServer]
    audit: A2AAudit
    pm: ProjectManager
    lookup: WebLookupAgent
    extras: dict[str, Any] = field(default_factory=dict)


def build_team(settings: Any, clock: Any, *, provider: Any | None = None, store: KnowledgeStore | None = None,
               audit: A2AAudit | None = None) -> Team:
    root = Path(settings.team_knowledge_dir)
    store = store or KnowledgeStore(root)
    audit = audit or A2AAudit(path=root / "a2a_audit.jsonl")
    provider = provider or web_provider(settings)
    lookup = WebLookupAgent(provider, timeout_s=settings.approach_web_timeout_s, cache_ttl_s=settings.approach_web_cache_ttl_s,
                            now=clock.now)
    servers: dict[str, A2AServer] = {}
    for site in store.sites():
        agent = SiteAgent(site, store, provider, timeout_s=min(20.0, settings.approach_web_timeout_s),
                          cost_per_search_inr=settings.team_cost_per_search_inr, now=clock.now)
        servers[site] = A2AServer(agent.card(), agent)
    spec = WebLookupSpecialist(lookup, cost_per_search_inr=settings.team_cost_per_search_inr)
    servers[spec.name] = A2AServer(spec.card(), spec)
    transport = InProcessTransport(servers)

    def budget() -> TaskBudget:
        return TaskBudget(settings.team_budget_steps, settings.team_budget_seconds, settings.team_budget_cost_inr)

    pm = ProjectManager(transport, audit=audit, big_threshold=settings.team_big_goal_threshold,
                        max_sub_pms=settings.team_max_sub_pms, budget_factory=budget)
    return Team(store, transport, servers, audit, pm, lookup)


def build_gateway(pipeline: Any) -> TeamGateway | None:
    s = pipeline.c.settings
    qu_on, team_on = bool(s.query_understanding_enabled), bool(s.agent_team_enabled)
    if not (qu_on or team_on):
        return None
    qu = None
    if qu_on:
        try:
            from friday.speech import SpeechUnderstander

            qu = QueryUnderstandingAgent(SpeechUnderstander(pipeline.c.get("llm"), s), UserDictionary(pipeline.repos), s)
        except Exception:  # noqa: BLE001 - no LLM component: the rules + fuzzy parts still work
            log.info("query understanding: no llm component; rules and dictionary only")
            qu = QueryUnderstandingAgent(None, UserDictionary(pipeline.repos), s)
    pm = team = None
    if team_on:
        team = build_team(s, pipeline.clock)
        pm = team.pm
    gw = TeamGateway(pipeline, qu=qu, pm=pm, web_render=(lambda data, lang: _render_web(team, data, lang)) if team else None,
                     ack_after_s=s.approach_ack_after_s)
    gw.team = team  # type: ignore[attr-defined]
    return gw


def _render_web(team: Team | None, data: dict[str, Any], lang: str) -> str:
    from friday.planner.agents.web_lookup import WebLookupOutput

    assert team is not None
    return team.lookup.render(WebLookupOutput.model_validate(data), lang)
