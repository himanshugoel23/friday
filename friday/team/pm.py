# ruff: noqa: E501
"""The team's project managers. They only MANAGE: split the request into goals, delegate over A2A, check
results, merge ONE reply. They never search, parse pages or touch a website themselves.

    small task (goals < threshold):   PM ──A2A──▶ specialists (zomato, swiggy, web_lookup)
    big task   (goals >= threshold):  lead PM ──A2A──▶ sub-PM 1..n ──A2A──▶ specialists
                                      (depth max 2; a sub-PM reaches ONLY specialists, never another sub-PM;
                                       it reports ONLY to the lead; one budget is shared down the tree)

Deterministic parts (no model): clause splitting, goal classification, the size rule, sub-PM cap, merge.
A failed sub-PM or specialist is reported up and the lead continues with the partial result; budget
exhaustion stops dispatching cleanly and the lead replies with what it has.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import BudgetExceeded, TaskBudget
from friday.a2a.client import A2AClient
from friday.a2a.server import A2AServer, AgentReply, IncomingCall
from friday.a2a.transport import InProcessTransport
from friday.a2a.types import AgentCard, Skill, Task, TaskState, new_id
from friday.core.logging import get_logger
from friday.planner import signals as sg
from friday.planner.planner import HeuristicDecider
from friday.planner.types import Approach, PlannerContext
from friday.team import wording
from friday.team.food import FOOD_SKILL, is_food_clause, parse_food

log = get_logger(__name__)
_IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_SKILL = "project.run"
_SPLIT = re.compile(r"\s*(?:[;\n]|\.\s+(?=[A-Za-z])|,\s*(?:and\s+|also\s+|then\s+)?|\s+(?:and\s+also|and\s+then|also|plus|aur\s+phir|aur\s+ek|phir)\s+|\s+and\s+(?=(?:also\s+)?(?:find|check|get|show|order|what|price|book|call|tell|bata|dekho)\b)|\s+aur\s+(?=(?:ek\s+)?(?:\w+\s+){0,3}(?:ka|ki|ke)\s+(?:price|daam|rate)))\s*", re.I)
_LEAD_NUM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s*")


@dataclass
class Goal:
    id: int
    text: str
    domain: str  # food | web | other
    approach: str = "answer"  # the planner's approach for this clause
    site: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def team_supported(self) -> bool:
        return self.domain in ("food", "web")


@dataclass
class GoalResult:
    goal: Goal
    status: str  # done | input_required | failed | skipped
    sites: list[dict[str, Any]] = field(default_factory=list)  # food: one per site; web: [web result]
    question: str | None = None
    pending: list[tuple[str, str]] = field(default_factory=list)  # (agent, task_id) waiting for input
    error: str | None = None
    group: int | None = None  # which sub-PM ran it


@dataclass
class TeamOutcome:
    root_task_id: str
    goals: list[Goal]
    results: list[GoalResult]
    big: bool
    sub_pms: int = 0
    budget: dict[str, object] = field(default_factory=dict)
    budget_exhausted: str | None = None
    children: list[dict[str, str]] = field(default_factory=list)  # {agent, task, parent}
    remaining_text: str = ""

    @property
    def partial(self) -> bool:
        return any(r.status != "done" for r in self.results)


# ---------------------------------------------------------------- deterministic decomposition
def split_clauses(text: str) -> list[str]:
    parts = [p.strip(" ,.;") for p in _SPLIT.split(_LEAD_NUM.sub("", text.strip()))]
    return [_LEAD_NUM.sub("", p).strip() for p in parts if p and len(p.strip()) > 2]


def classify_clause(clause: str, heuristic: HeuristicDecider) -> Goal:
    if is_food_clause(clause):
        p = parse_food(clause)
        return Goal(0, clause, "food", Approach.WEB_LOOKUP.value, p.site)
    d = heuristic.decide(PlannerContext(text=clause))
    if d.approach == Approach.WEB_LOOKUP and d.confidence >= 0.8:
        return Goal(0, clause, "web", d.approach.value, None, {"retailer": d.retailer, "query": d.query or clause})
    if d.approach in (Approach.CALL_VENDORS, Approach.APP_OR_CONNECTOR) or sg.has_local_signal(clause):
        return Goal(0, clause, "other", d.approach.value)
    return Goal(0, clause, "unlabelled", d.approach.value)


def decompose(text: str, heuristic: HeuristicDecider | None = None) -> list[Goal]:
    """Clauses -> goals. A clause with no domain of its own ('with extra raita') joins the goal before it."""
    h = heuristic or HeuristicDecider()
    goals: list[Goal] = []
    for clause in split_clauses(text) or [text.strip()]:
        g = classify_clause(clause, h)
        if g.domain == "unlabelled":
            if goals:
                goals[-1].text += " " + clause  # a modifier of the previous goal
                continue
            g.domain = "other"
        goals.append(g)
    for i, g in enumerate(goals, 1):
        g.id = i
    return goals


def is_big(goals: list[Goal], threshold: int) -> bool:
    """THE size rule: the number of independent team-handled goals reaches the threshold."""
    return sum(1 for g in goals if g.team_supported) >= max(2, threshold)


def group_goals(goals: list[Goal], max_sub_pms: int) -> list[list[Goal]]:
    """One sub-PM per goal, capped; goals beyond the cap join the last sub-PM (it runs them in turn)."""
    mine = [g for g in goals if g.team_supported]
    cap = max(1, max_sub_pms)
    groups: list[list[Goal]] = [[g] for g in mine[:cap]]
    for extra in mine[cap:]:
        groups[-1].append(extra)
    return groups


# ---------------------------------------------------------------- running ONE goal (shared by PM and sub-PM)
async def run_goal(client: A2AClient, goal: Goal, *, default_area: str | None, lang: str, budget: TaskBudget,
                   root: str, parent: str | None, outcome_children: list[dict[str, str]]) -> GoalResult:
    if goal.domain == "food":
        req = parse_food(goal.text, default_area)
        want = [goal.site] if goal.site else []
        agents = await client.agents_with_skill(FOOD_SKILL)
        picks = [a for a in agents if not want or a in want] or agents
        if not picks:
            return GoalResult(goal, "failed", error="no food agent available")
        coros = [client.delegate(a, data={**req.data(), "lang": lang}, root_task_id=root, parent_task_id=parent, budget=budget)
                 for a in picks]
        tasks = await asyncio.gather(*coros, return_exceptions=True)
        res = GoalResult(goal, "failed")
        stopped: str | None = None
        for agent, t in zip(picks, tasks, strict=True):
            if isinstance(t, BudgetExceeded):
                stopped = t.reason
                continue
            if isinstance(t, BaseException):
                res.error = type(t).__name__
                continue
            assert isinstance(t, Task)
            outcome_children.append({"agent": agent, "task": t.id, "parent": parent or root})
            if t.state == TaskState.COMPLETED:
                res.sites.append(t.result_data() or {"site": agent, "status": "no_result", "options": []})
            elif t.state == TaskState.INPUT_REQUIRED:
                res.pending.append((agent, t.id))
                res.question = t.status_text()
            else:
                res.error = t.status_text() or str((t.metadata or {}).get("error", "failed"))
        if res.sites:
            res.status = "done"
        elif res.pending:
            res.status = "input_required"
        if stopped and not res.sites and not res.pending:
            raise BudgetExceeded(stopped)
        return res
    if goal.domain == "web":
        t = await client.delegate("web_lookup", data={"query": goal.params.get("query") or goal.text,
                                                    "retailer": goal.params.get("retailer"), "lang": lang},
                                  root_task_id=root, parent_task_id=parent, budget=budget)
        outcome_children.append({"agent": "web_lookup", "task": t.id, "parent": parent or root})
        if t.state == TaskState.COMPLETED:
            return GoalResult(goal, "done", sites=[t.result_data()])
        return GoalResult(goal, "failed", error=t.status_text() or str((t.metadata or {}).get("error", "failed")))
    return GoalResult(goal, "skipped", error="not handled by the team")


# ---------------------------------------------------------------- sub-PM as an A2A agent
class SubPMAgent:
    """An A2A agent whose job is one sub-project. It owns an A2A client that can reach ONLY specialists."""

    def __init__(self, name: str, specialists: InProcessTransport, *, budget: TaskBudget, audit: A2AAudit,
                 root: str, default_area: str | None, lang: str) -> None:
        self.name = name
        self.client = A2AClient(specialists, name=name, depth=1, audit=audit)
        self.budget, self.root, self.default_area, self.lang = budget, root, default_area, lang

    def card(self) -> AgentCard:
        return AgentCard(name=self.name, url=f"inproc://{self.name}", description="Runs one sub-project for the lead PM using specialist agents.",
                         skills=[Skill(id=PROJECT_SKILL, name="Run a sub-project", description="goals -> results", tags=["pm"])])

    async def handle(self, call: IncomingCall) -> AgentReply:
        goals = [Goal(**g) for g in call.data.get("goals", [])]
        children: list[dict[str, str]] = []
        results: list[GoalResult] = []
        stop: str | None = None
        for g in goals:
            if stop:
                results.append(GoalResult(g, "skipped", error=f"budget:{stop}"))
                continue
            try:
                results.append(await run_goal(self.client, g, default_area=self.default_area, lang=self.lang,
                                              budget=self.budget, root=self.root, parent=call.task_id, outcome_children=children))
            except BudgetExceeded as e:
                stop = e.reason
                results.append(GoalResult(g, "skipped", error=f"budget:{e.reason}"))
        data = {"results": [_pack(r) for r in results], "children": children, "budget_exhausted": stop}
        state = TaskState.COMPLETED if any(r.status in ("done", "input_required") for r in results) else TaskState.FAILED
        return AgentReply(state, "" if state == TaskState.COMPLETED else "sub-project failed", data)


def _pack(r: GoalResult) -> dict[str, Any]:
    return {"goal": vars(r.goal), "status": r.status, "sites": r.sites, "question": r.question, "pending": r.pending, "error": r.error}


def _unpack(d: dict[str, Any], group: int | None = None) -> GoalResult:
    return GoalResult(Goal(**d["goal"]), d["status"], d.get("sites", []), d.get("question"),
                      [tuple(p) for p in d.get("pending", [])], d.get("error"), group)


# ---------------------------------------------------------------- the PM
class ProjectManager:
    """Small task: this class is the PM. Big task: it becomes the LEAD PM and spawns sub-PMs."""

    def __init__(self, specialists: InProcessTransport, *, audit: A2AAudit | None = None, big_threshold: int = 3,
                 max_sub_pms: int = 4, budget_factory: Callable[[], TaskBudget] | None = None,
                 heuristic: HeuristicDecider | None = None) -> None:
        self.specialists = specialists
        self.audit = audit or A2AAudit()
        self.big_threshold, self.max_sub_pms = big_threshold, max_sub_pms
        self.budget_factory = budget_factory or TaskBudget
        self.heuristic = heuristic or HeuristicDecider()

    def plan(self, text: str) -> list[Goal]:
        return decompose(text, self.heuristic)

    async def run(self, text: str, *, default_area: str | None = None, lang: str = "hinglish",
                  goals: list[Goal] | None = None) -> TeamOutcome:
        goals = goals if goals is not None else self.plan(text)
        root = new_id()
        budget = self.budget_factory()
        mine = [g for g in goals if g.team_supported]
        out = TeamOutcome(root, goals, [], is_big(goals, self.big_threshold),
                          remaining_text=" ".join(g.text for g in goals if not g.team_supported))
        try:
            if out.big:
                await self._lead(out, mine, budget, default_area, lang)
            else:
                await self._small(out, mine, budget, default_area, lang)
        except BudgetExceeded as e:
            out.budget_exhausted = e.reason
        done = {r.goal.id for r in out.results}
        for g in mine:
            if g.id not in done:  # never reached because the budget ran out
                out.results.append(GoalResult(g, "skipped", error="budget"))
        out.results.sort(key=lambda r: r.goal.id)
        out.budget = budget.summary()
        out.budget_exhausted = out.budget_exhausted or budget.exhausted
        return out

    async def _small(self, out: TeamOutcome, goals: list[Goal], budget: TaskBudget, area: str | None, lang: str) -> None:
        client = A2AClient(self.specialists, name="pm", depth=0, audit=self.audit)
        for g in goals:
            out.results.append(await run_goal(client, g, default_area=area, lang=lang, budget=budget, root=out.root_task_id,
                                              parent=None, outcome_children=out.children))

    async def _lead(self, out: TeamOutcome, goals: list[Goal], budget: TaskBudget, area: str | None, lang: str) -> None:
        groups = group_goals(goals, self.max_sub_pms)
        out.sub_pms = len(groups)
        sub_tr = InProcessTransport()
        for i, _grp in enumerate(groups, 1):
            sub = SubPMAgent(f"subpm-{i}", self.specialists, budget=budget, audit=self.audit, root=out.root_task_id,
                             default_area=area, lang=lang)
            sub_tr.register(sub.name, A2AServer(sub.card(), sub, max_depth=2))
        lead = A2AClient(sub_tr, name="lead-pm", depth=0, audit=self.audit)

        async def one(i: int, grp: list[Goal]) -> list[GoalResult]:
            try:
                t = await lead.delegate(f"subpm-{i}", data={"goals": [vars(g) for g in grp]}, root_task_id=out.root_task_id, budget=budget)
            except BudgetExceeded as e:
                return [GoalResult(g, "skipped", error=f"budget:{e.reason}", group=i) for g in grp]
            out.children.append({"agent": f"subpm-{i}", "task": t.id, "parent": out.root_task_id})
            data = t.result_data()
            if t.state != TaskState.COMPLETED or "results" not in data:
                # a failed sub-PM is reported up; the lead carries on with the others
                return [GoalResult(g, "failed", error="sub-project failed", group=i) for g in grp]
            out.children.extend(data.get("children", []))
            return [_unpack(r, i) for r in data["results"]]

        for rs in await asyncio.gather(*(one(i, grp) for i, grp in enumerate(groups, 1))):
            out.results.extend(rs)

    async def resume(self, pending: list[tuple[str, str]], answer: str, goal: Goal, root: str, *, lang: str = "hinglish") -> GoalResult:
        """The user answered an input-required question: continue the SAME specialist tasks with it."""
        budget = self.budget_factory()
        client = A2AClient(self.specialists, name="pm", depth=0, audit=self.audit)
        res = GoalResult(goal, "failed")
        for agent, task_id in pending:
            t = await client.delegate(agent, text=answer, task_id=task_id, root_task_id=root, budget=budget)
            if t.state == TaskState.COMPLETED:
                res.sites.append(t.result_data())
            elif t.state == TaskState.INPUT_REQUIRED:
                res.pending.append((agent, t.id))
                res.question = t.status_text()
            else:
                res.error = t.status_text() or "failed"
        res.status = "done" if res.sites else ("input_required" if res.pending else "failed")
        return res


# ---------------------------------------------------------------- merge: ONE reply, written by the lead alone
def _ist(iso: object) -> str:
    try:
        return datetime.fromisoformat(str(iso)).astimezone(_IST).strftime("%d %b %H:%M")
    except ValueError:
        return "now"


def render_goal(r: GoalResult, lang: str, *, web_render: Callable[[dict[str, Any], str], str] | None = None) -> str:
    if r.status == "input_required":
        key = {"which_area": "ask_area", "what_dish": "ask_dish"}.get(r.question or "", "ask_area")
        return wording.line(key, lang)
    if r.status != "done":
        return wording.line("part_failed", lang, what=r.goal.text[:60])
    if r.goal.domain == "web":
        return web_render(r.sites[0], lang) if web_render else str(r.sites[0].get("summary", ""))
    blocks = []
    for s in r.sites:
        site = str(s.get("site", "")).title()
        if s.get("status") != "ok" or not s.get("options"):
            blocks.append(wording.line("food_none", lang, site=site))
        else:
            stamp = _ist(s.get("as_of"))
            lines = [wording.line("food_header", lang, site=site, time=stamp)]
            for o in s["options"][:3]:
                bits = [o.get("price_text") or (f"Rs {o['price_inr']:g}" if o.get("price_inr") is not None else wording.line("price_unknown", lang))]
                if o.get("rating"):
                    bits.append(f"{o['rating']}*")
                if o.get("delivery_time"):
                    bits.append(str(o["delivery_time"]))
                if o.get("offer"):
                    bits.append(str(o["offer"]))
                lines.append(f"- {o['name']}: {', '.join(str(b) for b in bits)}\n  {o.get('deep_link') or o.get('url')}")
            if s.get("over_cap"):
                lines.append(wording.line("over_cap", lang, n=s["over_cap"], cap=s.get("max_price_inr")))
            if s.get("kb_status") != "verified":
                lines.append(wording.line("food_unverified", lang, site=site))
            blocks.append("\n".join(lines))
    if any(s.get("search_link") for s in r.sites) and not any(s.get("options") for s in r.sites):
        blocks.append(" ".join(str(s["search_link"]) for s in r.sites if s.get("search_link")))
    return "\n".join(blocks)


def merge_reply(out: TeamOutcome, lang: str, *, web_render: Callable[[dict[str, Any], str], str] | None = None) -> str:
    """One message for the user. Failed parts are named, not hidden; the money rule is stated once."""
    results = [r for r in out.results if r.goal.team_supported]
    if not results:
        return ""
    if all(r.status in ("failed", "skipped") for r in results):
        return wording.line("all_failed", lang)
    parts = []
    multi = len(results) > 1
    for r in results:
        body = render_goal(r, lang, web_render=web_render)
        parts.append((wording.line("part_title", lang, n=r.goal.id, what=r.goal.text[:50]) + "\n" if multi else "") + body)
    text = "\n\n".join(parts)
    if out.budget_exhausted:
        text += "\n\n" + wording.line("budget_stop", lang)
    if any(r.goal.domain == "food" and r.status == "done" for r in results):
        text += "\n\n" + wording.line("food_footer", lang)
    if out.remaining_text:
        text += "\n" + wording.line("rest_note", lang, what=out.remaining_text[:60])
    return text
