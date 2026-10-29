# ruff: noqa: E501
"""The browser agent as an A2A specialist (skill ``browser.task``) for 'do this on a website for me' tasks when no site MCP or
connector exists. The same agent, the same policy: A2A only carries the request.

Request data: ``{"goal", "domains": [...], "user_id", "start_url"?, "lang"?}``. Replies:
completed -> result in data;  input-required -> the question (continue with the SAME task id and the user's answer as text);
failed -> blocked / payment stop / gave up / busy, with the plain-language message (never page text).

Not wired into the project manager's automatic delegation: a run takes minutes and the PM's budget is 40 s, so the planner
owns the user entry (docs/BROWSER_AGENT_DESIGN.md)."""

from __future__ import annotations

from friday.a2a.server import AgentReply, IncomingCall
from friday.a2a.types import AgentCard, Skill, TaskState
from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.types import RunOutcome, RunSpec, Status

BROWSER_SKILL = "browser.task"


class BrowserAgentSpecialist:
    name = "browser_agent"

    def __init__(self, agent: BrowserAgent, *, cost_per_run_inr: float = 6.0) -> None:
        self.agent, self.cost = agent, cost_per_run_inr
        self._runs: dict[str, str] = {}  # a2a task id -> run id

    def card(self, url: str | None = None) -> AgentCard:
        return AgentCard(
            name=self.name, url=url or f"inproc://{self.name}", version="1",
            description="Does a task on a website in a browser (read, fill, stop before payment). Asks the user when it needs details; every irreversible step needs the user's yes.",
            skills=[Skill(id=BROWSER_SKILL, name="Do a task on a website", description="goal + allowed domains -> result",
                          tags=["browser", "web"], examples=["download my October bill from example-telecom.com"])],
        )

    def _reply(self, call: IncomingCall, out: RunOutcome) -> AgentReply:
        data = {"run_id": out.run_id, "status": out.status.value, "message": out.message, "proofs": [p.model_dump() for p in out.proofs]}
        if out.status in (Status.WAITING_USER, Status.WAITING_CONFIRM):
            self._runs[call.task_id] = out.run_id
            return AgentReply(TaskState.INPUT_REQUIRED, out.question or out.message, data, cost_inr=self.cost)
        if out.status == Status.DONE:
            return AgentReply(TaskState.COMPLETED, "", data, cost_inr=self.cost)
        return AgentReply(TaskState.FAILED, out.status.value, data, cost_inr=self.cost)

    async def handle(self, call: IncomingCall) -> AgentReply:
        run_id = self._runs.get(call.task_id)
        if run_id is not None:  # the answer to the question this task is waiting on
            out = await self.agent.reply(run_id, call.text)
            if out is None:
                return AgentReply(TaskState.FAILED, "run_closed", {"status": "closed"})
            return self._reply(call, out)
        d = call.data
        goal, doms, user = str(d.get("goal") or call.text or "").strip(), [str(x) for x in d.get("domains") or []], str(d.get("user_id") or "")
        if not goal or not doms or not user:
            return AgentReply(TaskState.INPUT_REQUIRED, "which_site", {"need": ["goal", "domains", "user_id"]})
        spec = RunSpec(goal=goal[:500], allowed_domains=doms, start_url=d.get("start_url"), lang=str(d.get("lang") or "hinglish"))
        return self._reply(call, await self.agent.start(user, spec))
