# ruff: noqa: E501
"""Build the step runner for the live pipeline. Returns None unless FRIDAY_BROWSER_STEPS_ENABLED and the browser agent exists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.browser_agent.stores import JsonRunStore
from friday.core.logging import get_logger
from friday.shopping import catalog, places
from friday.steps.gateway import StepGateway
from friday.steps.planner import OpenAIPlanLLM, StepPlanner
from friday.steps.runner import StepRunner
from friday.steps.store import JsonPlanStore
from friday.steps.suggest import ShoppingSuggester
from friday.steps.worker import AgentStepWorker, OverlayFacts, StepLogin, build_step_agent

log = get_logger(__name__)


class RepoUserPort:
    """UserPort over the saved places (the same store 'what do you remember' lists and 'delete everything' erases)."""

    def __init__(self, repos: Any) -> None:
        self.repos = repos

    async def saved_area(self, user_id: str) -> str:
        saved = await places.saved_places(self.repos, user_id, include_office=False)
        return next((d.where for d in saved if d.where), "")

    async def area_from_reply(self, user_id: str, text: str) -> str:
        ans = places.parse_answer(text)
        if ans is None:
            kind = places.kind_of(text)  # a bare 'Home' / 'PG': the saved place of that kind
            saved = await places.saved_places(self.repos, user_id, include_office=True)
            return next((d.where for d in saved if d.kind == kind and d.where), "")
        saved_place = await places.save_place(self.repos, user_id, ans)
        return saved_place.where

    async def phone_tail(self, user_id: str) -> str:
        user = await self.repos.users.get(user_id)
        digits = "".join(c for c in (getattr(user, "phone", "") or "") if c.isdigit())
        return digits[-2:]


class StackOtp:
    """OtpPort over the private-browser stack: arms the guarded 'login code typed in chat' path (this user, this site, single use)
    and answers 'is a code waiting' without consuming it."""

    def __init__(self, stack: Any) -> None:
        self.stack = stack

    def arm(self, user_id: str, site: str, key: str) -> bool:
        pending = getattr(self.stack, "pending_logins", None)
        if pending is None or getattr(self.stack, "otp", None) is None:
            return False
        pending.expect(user_id, site, key)
        return True

    def ready(self, key: str) -> bool:
        otp = getattr(self.stack, "otp", None)
        return bool(otp is not None and otp.has_pending(key))

    def wipe(self, key: str) -> None:
        otp = getattr(self.stack, "otp", None)
        if otp is not None:
            otp.wipe(key)
        pending = getattr(self.stack, "pending_logins", None)
        if pending is not None:
            pending.clear_task(key)


def build_steps(pipeline: Any) -> StepGateway | None:
    s = pipeline.c.settings
    if not getattr(s, "browser_steps_enabled", False):
        return None
    gw = getattr(pipeline, "browser_agent", None)
    if gw is None:
        log.info("step runner: needs the browser agent (FRIDAY_BROWSER_AGENT_ENABLED); staying off")
        return None
    from friday.browser_agent.wiring import StackLogin

    root = Path(s.browser_steps_dir)
    base = gw.agent
    stack = getattr(pipeline, "browser", None)
    overlay = OverlayFacts(base.facts)
    run_store = JsonRunStore(root)
    login = StepLogin(StackLogin(stack) if stack is not None else None, run_store)
    worker = AgentStepWorker(build_step_agent(base, store=run_store, overlay=overlay, login=login), overlay, login)
    shopping = getattr(getattr(pipeline, "planner", None), "shopping", None)
    llm = None
    if s.resolve_llm() == "openai":
        try:
            llm = OpenAIPlanLLM(pipeline.c.get("llm"), model=s.browser_agent_model or s.openai_default_purpose_model)
        except Exception:  # noqa: BLE001 - data playbooks alone are a valid planner
            llm = None

    async def say(user_id: str, text: str) -> None:
        await pipeline.notifier.notify_user(user_id, text, buttons=[], task_id=None)

    async def web_fallback(st: Any) -> None:
        user = await pipeline.repos.users.get(st.user_id)
        cat = catalog.categories().get(st.plan.slots.get("category", ""))
        if user is not None and cat is not None and shopping is not None:
            await shopping.start(user, cat, st.plan.goal, st.lang)

    runner = StepRunner(
        worker=worker, planner=StepPlanner(llm), users=RepoUserPort(pipeline.repos), say=say, store=JsonPlanStore(root), clock=pipeline.clock,
        otp=StackOtp(stack) if stack is not None else None,
        suggester=ShoppingSuggester(shopping.agent) if shopping is not None else None,
        fallback=web_fallback if shopping is not None else None,
        audit=lambda event, **kw: log.info("%s %s", event, kw), otp_ttl_s=float(s.browser_steps_otp_ttl_s),
    )
    return StepGateway(pipeline, runner)
