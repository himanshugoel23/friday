# ruff: noqa: E501
"""Generic web lookup as an A2A agent (skill ``web.lookup``): wraps the existing WebLookupAgent, so prices,
stock and facts for non-food goals use the same sourced, time-stamped, cached lookup as the approach planner."""

from __future__ import annotations

from friday.a2a.server import AgentReply, IncomingCall
from friday.a2a.types import AgentCard, Skill, TaskState
from friday.planner.agents.web_lookup import WebLookupAgent, WebLookupInput

WEB_SKILL = "web.lookup"


class WebLookupSpecialist:
    name = "web_lookup"

    def __init__(self, agent: WebLookupAgent, *, cost_per_search_inr: float = 1.0) -> None:
        self.agent, self.cost = agent, cost_per_search_inr

    def card(self, url: str | None = None) -> AgentCard:
        return AgentCard(
            name=self.name, url=url or f"inproc://{self.name}", version="1",
            description="Looks up prices, availability, timings and facts on public web pages. Always with sources and an as-of time.",
            skills=[Skill(id=WEB_SKILL, name="Web lookup", description="query (+ retailer, pincode) -> sourced answer",
                          tags=["web", "price"], examples=["price of 5 kg Aashirvaad atta on Zepto"])],
        )

    async def handle(self, call: IncomingCall) -> AgentReply:
        d = call.data
        query = str(d.get("query") or call.text or "").strip()
        if not query:
            return AgentReply(TaskState.INPUT_REQUIRED, "what_lookup")
        out = await self.agent.run(WebLookupInput(query=query, retailer=d.get("retailer"), pincode=d.get("pincode"),
                                                  lang=str(d.get("lang") or "hinglish")))
        cost = 0.0 if out.from_cache else self.cost
        data = out.model_dump(mode="json")
        if out.status in ("timeout", "unavailable"):
            return AgentReply(TaskState.FAILED, out.status, data, cost_inr=cost)
        return AgentReply(TaskState.COMPLETED, "", data, cost_inr=cost)
