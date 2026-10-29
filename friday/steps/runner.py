# ruff: noqa: E501
"""The step runner: ONE step at a time, persisted, resumable.

    plan (before the browser) -> [ announce -> skip if the precondition is met -> run the step -> record proof -> next ] -> report
                                          |                                  |
                         ask ONLY at a step that needs it         stop with a plain message + the next best option

Inside a loop step the existing browser agent runs (``worker.py``); its policy layer keeps every safety rule. Code steps (area,
login, variant match, suggestions, report) are small handlers here. The OTP never touches a log, a prompt, the plan file or a
message: it lives only in the guarded one-time channel (``OtpPort``) and is read by the loop at the moment it is typed."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from friday.browser_agent import ask
from friday.browser_agent.rules import host_of, strip_query
from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger
from friday.planner import signals as sg
from friday.shopping import catalog
from friday.steps import parse, playbooks
from friday.steps import wording as w
from friday.steps.planner import StepPlanner
from friday.steps.ports import Fallback, OtpPort, Say, StepWorker, Suggester, UserPort
from friday.steps.store import MemoryPlanStore, new_plan_id
from friday.steps.types import (
    LOOP_STEPS,
    TERMINAL,
    Awaiting,
    PlanState,
    Status,
    Step,
    StepRecord,
    StepRequest,
    StepResult,
    StepType,
)
from friday.voice.text import redact_secrets

log = get_logger(__name__)
STOP_RE = re.compile(r"^\W*(stop|cancel|ruko|rok\s*do|band\s*karo)\W*$", re.I)
CODE_IN_TEXT = re.compile(r"(?<!\d)\d{4,8}(?!\d)")
SILENT = frozenset({StepType.MATCH_VARIANT, StepType.REPORT})  # instant steps: no progress line, not numbered


class Flow(StrEnum):
    NEXT = "next"  # step done: go on
    RERUN = "rerun"  # run the (possibly changed) current step again
    WAIT = "wait"  # waiting for the user / the code / the browser
    STOP = "stop"  # ended (blocked, failed ...) or a next-best option is offered


def clip(s: str, n: int) -> str:
    return " ".join((s or "").split())[:n]


class StepRunner:
    def __init__(self, *, worker: StepWorker, planner: StepPlanner, users: UserPort, say: Say, store: Any = None, clock: Clock | None = None,
                 otp: OtpPort | None = None, suggester: Suggester | None = None, fallback: Fallback | None = None, audit: Any = None,
                 otp_ttl_s: float = 300.0, ask_ttl_s: float = 6 * 3600.0, busy_retry_s: float = 60.0, poll_interval_s: float = 2.0,
                 max_replans: int = 2, max_busy: int = 5) -> None:
        self.worker, self.planner, self.users, self.say = worker, planner, users, say
        self.store = store or MemoryPlanStore()
        self.clock = clock or SystemClock()
        self.otp, self.suggester, self.fallback = otp, suggester, fallback
        self._audit = audit
        self.otp_ttl, self.ask_ttl, self.busy_retry = otp_ttl_s, ask_ttl_s, busy_retry_s
        self.poll_interval_s, self.max_replans, self.max_busy = poll_interval_s, max_replans, max_busy
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    # ================================================================== small helpers
    def _now(self) -> datetime:
        return self.clock.now()

    def _iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _age(self, iso: str) -> float:
        return (self._now() - datetime.fromisoformat(iso)).total_seconds() if iso else 0.0

    def _event(self, event: str, **kw: object) -> None:
        if self._audit is not None:
            try:
                self._audit(event, **kw)
            except Exception:  # noqa: BLE001 - an audit failure never stops a task
                log.info("steps: audit failed")

    async def _tell(self, st: PlanState, text: str) -> None:
        if text:
            await self.say(st.user_id, text)

    def _save(self, st: PlanState) -> None:
        st.updated_at = self._iso()
        self.store.save(st)

    def _site(self, st: PlanState) -> str:
        return st.plan.slots.get("store") or (st.plan.domains[0] if st.plan.domains else "the site")

    def _cat(self, st: PlanState) -> catalog.Category | None:
        return catalog.categories().get(st.plan.slots.get("category", ""))

    def _counts(self, st: PlanState) -> tuple[int, int]:
        """(n, total) over the numbered steps that will really run, given what is known now."""
        done = sum(1 for r in st.records if r.state == "done" and StepType(r.type) not in SILENT)
        left = [s for s in st.plan.steps[st.idx:] if s.type not in SILENT and self._skip(st, s) is None]
        return done + 1, done + max(1, len(left))

    def _title(self, st: PlanState, step: Step) -> str:
        t, lang = step.type, st.lang
        slots = st.plan.slots
        if t == StepType.OPEN_SITE:
            return w.line("t_open_site", lang, host=host_of(st.plan.start_url) or st.plan.domains[0])
        if t == StepType.SEARCH:
            return w.line("t_search", lang, query=slots.get("query") or slots.get("item") or "")
        if t == StepType.NEED_LOGIN:
            return w.line("t_need_login", lang, site=self._site(st), tail=st.info.get("_tail", ""))
        if t == StepType.NEED_INFO:
            return w.line("t_need_info", lang, question=step.args.get("question") or f"What should I use for {step.args.get('key', 'this')}?")
        key = f"t_{t.value}"
        return w.line(key, lang) if key in w.LINES else t.value.replace("_", " ")

    async def _announce(self, st: PlanState, step: Step) -> None:
        key = f"a{st.idx}"
        if st.tries.get(key) or step.type in SILENT:
            return
        st.tries[key] = 1
        n, total = self._counts(st)
        await self._tell(st, w.line("step", st.lang, n=n, total=total, title=self._title(st, step)))

    def _record(self, st: PlanState, step: Step, state: str, *, note: str = "", snippet: str = "", proofs: list[dict[str, str]] | None = None) -> None:
        st.records.append(StepRecord(idx=st.idx, type=step.type.value, state=state, note=clip(note, 120),
                                     snippet=clip(redact_secrets(snippet), 160), proofs=list(proofs or [])))
        self._event("steps.step", plan=st.id, idx=st.idx, type=step.type.value, state=state)

    def _skip(self, st: PlanState, step: Step) -> str | None:
        t = step.type
        if t == StepType.NEED_AREA and st.area:
            return "area known"
        if t == StepType.NEED_LOGIN and not st.login_wall:
            return "no login wall"
        if t == StepType.NEED_LOGIN and st.logged_in:
            return "already logged in"
        if t == StepType.NEED_INFO and step.args.get("key", "") in st.info:
            return "already known"
        if t == StepType.MATCH_VARIANT and not st.products:
            return "nothing to match"
        if t == StepType.COMPARE_AND_SUGGEST and (self.suggester is None or not st.plan.slots.get("category")):
            return "no suggestions available"
        return None

    # ================================================================== entry points
    async def start(self, user_id: str, text: str, lang: str) -> bool:
        """True when the step runner took the request (a plan exists and runs), False to let the old flow have it."""
        if self.store.active_for(user_id) is not None:
            return False  # the caller sends 'already' (see ``has_open``)
        plan = await self.planner.plan(text)
        if plan is None:
            return False
        st = PlanState(id=new_plan_id(), user_id=user_id, lang=lang, plan=plan, created_at=self._iso(), updated_at=self._iso())
        if plan.playbook == "price_check":
            st.area = sg.pincode_in(text) or await self.users.saved_area(user_id)  # saved place => no area question
        self._save(st)
        self._event("steps.plan", plan=st.id, playbook=plan.playbook, source=plan.source, steps=",".join(s.type.value for s in plan.steps))
        await self._advance(st)
        return True

    def has_open(self, user_id: str) -> bool:
        return self.store.active_for(user_id) is not None

    async def handle_reply(self, user_id: str, text: str) -> bool:
        """The user's chat message while a plan is open. False = not ours (a bare login code belongs to the guarded OTP flow)."""
        st = self.store.active_for(user_id)
        if st is None:
            return False
        text = (text or "").strip()
        async with self._lock(st.id):
            st = self.store.load(st.id) or st
            if st.status in TERMINAL:
                return False
            if STOP_RE.match(text):
                await self._cancel(st)
                return True
            if st.status == Status.WAITING_OTP:
                return await self._reply_otp(st, text)
            if ask.looks_secret(text) and st.status != Status.WAITING_AGENT:
                await self._tell(st, w.line("secret", st.lang))
                return True
            aw = st.awaiting
            if st.status == Status.WAITING_AGENT and aw is not None:
                return await self._reply_agent(st, text)
            if st.status == Status.WAITING_USER and aw is not None:
                return await self._reply_user(st, aw, text)
            await self._tell(st, w.line("working", st.lang))
            return True

    async def tick(self) -> int:
        """Housekeeping (runtime loop, once a minute): codes that arrived, OTP timeouts, busy retries, unanswered questions, restarts."""
        n = 0
        for st in self.store.list_open():
            async with self._lock(st.id):
                st = self.store.load(st.id) or st
                if st.status in TERMINAL:
                    continue
                n += await self._tick_one(st)
        return n

    def lock_of(self, plan_id: str) -> asyncio.Lock:
        return self._lock(plan_id)

    def _lock(self, plan_id: str) -> asyncio.Lock:
        return self._locks.setdefault(plan_id, asyncio.Lock())

    async def forget_user(self, user_id: str) -> None:
        for st in self.store.list_open():
            if st.user_id == user_id and self.otp is not None:
                self.otp.wipe(st.id)
        self.store.delete_user(user_id)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ================================================================== the loop over steps
    async def _advance(self, st: PlanState) -> None:
        async with self._lock(st.id):
            await self._advance_locked(st)

    async def _advance_locked(self, st: PlanState) -> None:
        try:
            st.status = Status.RUNNING if st.status in (Status.WAITING_USER, Status.WAITING_BUSY, Status.WAITING_AGENT) else st.status
            while st.status == Status.RUNNING and st.idx < len(st.plan.steps):
                step = st.plan.steps[st.idx]
                why = self._skip(st, step)
                if why is not None:
                    self._record(st, step, "skipped", note=why)
                    st.idx += 1
                    self._save(st)
                    continue
                flow = await self._run_step(st, step)
                if flow == Flow.NEXT:
                    st.idx += 1
                self._save(st)
                if flow in (Flow.WAIT, Flow.STOP):
                    return
            if st.status == Status.RUNNING:  # a plan always ends with report; this is only a guard
                st.status = Status.DONE
                self._save(st)
        except Exception as e:  # noqa: BLE001 - a bug stops the task safely, never loops
            log.exception("steps: runner error")
            self._event("steps.error", plan=st.id, error=type(e).__name__)
            st.status, st.stop_reason = Status.FAILED, type(e).__name__
            self._save(st)
            await self._tell(st, w.line("stop", st.lang, n=self._counts(st)[0], title=self._title(st, st.plan.steps[min(st.idx, len(st.plan.steps) - 1)]),
                                        why=w.line("why_failed", st.lang)) + "\n" + w.line("nothing_changed", st.lang))

    async def _run_step(self, st: PlanState, step: Step) -> Flow:
        t = step.type
        if t in LOOP_STEPS:
            await self._announce(st, step)
            res = await self.worker.run(self._request(st, step))
            return await self._loop_result(st, step, res)
        if t == StepType.NEED_AREA:
            await self._announce(st, step)
            st.status, st.awaiting = Status.WAITING_USER, Awaiting(kind="area", asked_at=self._iso())
            return Flow.WAIT
        if t == StepType.NEED_INFO:
            await self._announce(st, step)
            st.status, st.awaiting = Status.WAITING_USER, Awaiting(kind="info", asked_at=self._iso(), key=step.args.get("key", "info"))
            return Flow.WAIT
        if t == StepType.NEED_LOGIN:
            return await self._login_start(st, step)
        if t == StepType.MATCH_VARIANT:
            return self._match(st, step)
        if t == StepType.COMPARE_AND_SUGGEST:
            return await self._suggest(st, step)
        return await self._report(st, step)

    def _request(self, st: PlanState, step: Step, *, goal_key: str = "", otp_key: str = "") -> StepRequest:
        slots = st.plan.slots
        key = goal_key or step.type.value
        goal = playbooks.render_goal(
            key, host=host_of(st.plan.start_url) or st.plan.domains[0], start_url=st.plan.start_url, query=slots.get("query") or slots.get("item") or "",
            target=step.args.get("target", ""), retry_hint="This is a second try: the layout may differ, so scroll and look again." if step.args.get("retry") == "1" else "")
        facts = {"delivery_area": st.area} if st.area else {}
        return StepRequest(user_id=st.user_id, plan_id=st.id, step=step, goal=goal, domains=st.plan.domains, start_url=st.plan.start_url,
                           lang=st.lang, facts=facts, otp_key=otp_key, login_site=self._site(st).lower())

    # ================================================================== a loop step's result
    async def _loop_result(self, st: PlanState, step: Step, res: StepResult) -> Flow:
        if res.status == "ok":
            flow = await self._apply(st, step, res)
            if flow == Flow.NEXT:
                seen = f"{len(st.products)} products with prices" if step.type == StepType.READ_RESULTS else res.text  # the answer itself is not repeated as proof
                self._record(st, step, "done", snippet=seen, proofs=res.proofs)
            return flow
        if res.status == "waiting":  # the loop asks the user something (a form field, the confirmation before an irreversible click)
            st.status, st.sub_run_id = Status.WAITING_AGENT, res.run_id
            st.awaiting = Awaiting(kind="agent", asked_at=self._iso())
            await self._tell(st, res.message)
            return Flow.WAIT
        if res.status == "busy":
            st.tries["busy"] = st.tries.get("busy", 0) + 1
            if st.tries["busy"] > self.max_busy:
                return await self._stop(st, step, "why_failed")
            if st.tries["busy"] == 1:
                await self._tell(st, w.line("busy", st.lang))
            st.status, st.awaiting = Status.WAITING_BUSY, Awaiting(kind="busy", asked_at=self._iso())
            return Flow.WAIT
        if res.status == "payment_stop":
            return await self._stop(st, step, "why_payment", payment=True)
        if res.status == "blocked":
            return await self._stop(st, step, "why_blocked")
        return await self._failed(st, step, res.reason or "failed", "why_login" if step.type == StepType.NEED_LOGIN else "why_failed")

    async def _failed(self, st: PlanState, step: Step, reason: str, why_key: str) -> Flow:
        if st.replans < self.max_replans:
            new = await self.planner.replan(st.plan, st.idx, reason)
            if new is not None:
                st.plan, st.replans = new, st.replans + 1
                self._event("steps.replan", plan=st.id, idx=st.idx, replans=st.replans)
                return Flow.RERUN
        return await self._stop(st, step, why_key)

    def _login_step_index(self, st: PlanState) -> int:
        return next((i for i, s in enumerate(st.plan.steps[: st.idx]) if s.type == StepType.NEED_LOGIN), -1)

    async def _apply(self, st: PlanState, step: Step, res: StepResult) -> Flow:
        t, text = step.type, res.text
        f = parse.flags(text)
        if t == StepType.OPEN_SITE:
            st.login_wall = parse.yes(text, "login_wall")
            return Flow.NEXT
        if t in (StepType.SEARCH, StepType.READ_RESULTS) and parse.yes(text, "login_wall") and not st.logged_in:
            st.login_wall = True  # the wall showed up later than the first look: go back to the login step once
            j = self._login_step_index(st)
            if j >= 0 and st.tries.get("relogin", 0) < 1:
                st.tries["relogin"] = 1
                st.idx = j
                return Flow.RERUN
            return await self._stop(st, step, "why_login")
        if t == StepType.SEARCH:
            if f.get("location") == "not_accepted":
                return await self._area_rejected(st)
            return Flow.NEXT
        if t == StepType.READ_RESULTS:
            lines = parse.product_lines(text)
            if not lines:
                return await self._failed(st, step, "no_price", "why_no_price")
            st.products = lines
            return Flow.NEXT
        if t == StepType.NEED_LOGIN:  # the 'send me the code' sub-step finished
            if "no_code" in text.lower():
                return await self._stop(st, step, "why_login")
            st.status, st.awaiting = Status.WAITING_OTP, Awaiting(kind="otp", asked_at=self._iso())
            self._watch(st.id)
            return Flow.WAIT
        st.info[f"out{st.idx}"] = clip(redact_secrets(text), 300)
        return Flow.NEXT

    # ================================================================== area
    async def _area_rejected(self, st: PlanState) -> Flow:
        st.tries["area"] = st.tries.get("area", 0) + 1
        if st.tries["area"] >= 2:
            return await self._stop(st, st.plan.steps[st.idx], "why_failed")
        bad, st.area = st.area, ""
        st.status, st.awaiting = Status.WAITING_USER, Awaiting(kind="area", asked_at=self._iso())
        await self._tell(st, w.line("t_need_area_again", st.lang, site=self._site(st), area=bad or "that area"))
        return Flow.WAIT

    async def _reply_user(self, st: PlanState, aw: Awaiting, text: str) -> bool:
        step = st.plan.steps[min(st.idx, len(st.plan.steps) - 1)]
        if aw.kind == "area":
            area = await self.users.area_from_reply(st.user_id, text)
            if not area:
                aw.tries += 1
                if aw.tries >= 3:
                    await self._stop(st, step, "why_failed")
                else:
                    st.awaiting = aw
                    self._save(st)
                    await self._tell(st, w.line("t_need_area_retry", st.lang))
                return True
            st.area = area
            if step.type == StepType.NEED_AREA:
                self._record(st, step, "done", note="area given")
                st.idx += 1
            st.awaiting = None
            await self._advance_locked(st)
            return True
        if aw.kind == "info":
            st.info[aw.key] = clip(text, 200)
            self._record(st, step, "done", note="info given")
            st.idx += 1
            st.awaiting = None
            await self._advance_locked(st)
            return True
        yn = ask.yes_no(text)
        if yn is None:
            await self._tell(st, w.line("yes_no", st.lang))
            return True
        if aw.kind == "resend":
            if not yn:
                await self._stop(st, step, "why_otp_late", offer=False)
                return True
            st.resends += 1
            st.awaiting = None
            st.status = Status.RUNNING
            if self.otp is not None:
                self.otp.arm(st.user_id, self._site(st), st.id)
            res = await self.worker.run(self._request(st, step, goal_key="login_request", otp_key=st.id))
            flow = await self._loop_result(st, step, res)
            self._save(st)
            if flow == Flow.RERUN:
                await self._advance_locked(st)
            return True
        if aw.kind == "fallback":
            st.awaiting, st.status = None, Status.BLOCKED
            self._save(st)
            if yn and self.fallback is not None:
                await self.fallback(st)
            else:
                await self._tell(st, w.line("cancelled", st.lang))
            return True
        return False

    # ================================================================== login (guarded OTP)
    async def _login_start(self, st: PlanState, step: Step) -> Flow:
        site = self._site(st)
        if self.otp is None or not self.otp.arm(st.user_id, site, st.id):
            return await self._stop(st, step, "otp_unavailable", offer=False)
        st.info["_tail"] = await self.users.phone_tail(st.user_id)
        await self._announce(st, step)
        res = await self.worker.run(self._request(st, step, goal_key="login_request", otp_key=st.id))
        return await self._loop_result(st, step, res)

    async def _reply_otp(self, st: PlanState, text: str) -> bool:
        if CODE_IN_TEXT.search(text):
            return False  # a code: the guarded login-OTP flow owns it (redacts the transcript, stores it once); never read here
        if self.otp is not None and self.otp.ready(st.id):
            await self._enter_code(st)
            return True
        await self._tell(st, w.line("otp_wait", st.lang))
        return True

    def _watch(self, plan_id: str) -> None:
        """Poll for the code for the OTP lifetime so the plan continues right after the guarded flow stored it (``tick`` also does it)."""
        if self.poll_interval_s <= 0:
            return
        t = asyncio.create_task(self._poll(plan_id))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _poll(self, plan_id: str) -> None:
        waited = 0.0
        while waited < self.otp_ttl:
            await asyncio.sleep(self.poll_interval_s)
            waited += self.poll_interval_s
            st = self.store.load(plan_id)
            if st is None or st.status != Status.WAITING_OTP:
                return
            if self.otp is not None and self.otp.ready(plan_id):
                async with self._lock(plan_id):
                    st = self.store.load(plan_id)
                    if st is not None and st.status == Status.WAITING_OTP:
                        await self._enter_code(st)
                return

    async def _enter_code(self, st: PlanState) -> None:
        step = st.plan.steps[st.idx]
        st.status, st.awaiting = Status.RUNNING, None
        self._save(st)
        await self._tell(st, w.line("otp_taken", st.lang))
        res = await self.worker.run(self._request(st, step, goal_key="login_enter", otp_key=st.id))
        if self.otp is not None:
            self.otp.wipe(st.id)  # single use: nothing is left behind whatever happened
        if res.status == "ok" and parse.yes(res.text, "logged_in"):
            st.logged_in = True
            self._record(st, step, "done", snippet="logged in", proofs=res.proofs)
            st.idx += 1
            await self._advance_locked(st)
            return
        if res.status == "ok":  # the site did not accept the code
            st.code_tries += 1
            if st.code_tries < 2 and self.otp is not None and self.otp.arm(st.user_id, self._site(st), st.id):
                st.status, st.awaiting = Status.WAITING_OTP, Awaiting(kind="otp", asked_at=self._iso())
                self._save(st)
                self._watch(st.id)
                await self._tell(st, w.line("otp_wrong", st.lang, site=self._site(st)))
                return
            await self._stop(st, step, "why_login")
            return
        flow = await self._loop_result(st, step, res)
        self._save(st)
        if flow == Flow.RERUN:
            await self._advance_locked(st)

    # ================================================================== code steps
    def _match(self, st: PlanState, step: Step) -> Flow:
        slots = st.plan.slots
        st.shown, st.variant_missing = parse.pick_variants(st.products, pack=slots.get("pack", ""), brand=slots.get("brand", ""))
        self._record(st, step, "done", note=("variant not seen" if st.variant_missing else "variant matched" if (slots.get("pack") or slots.get("brand")) else "main variants"))
        return Flow.NEXT

    async def _suggest(self, st: PlanState, step: Step) -> Flow:
        await self._announce(st, step)
        out = None
        if self.suggester is not None:
            try:
                out = await self.suggester.suggest(user_id=st.user_id, category=st.plan.slots.get("category", ""), area=st.area, lang=st.lang, own=st.products)
            except Exception:  # noqa: BLE001 - suggestions are an extra; the price is already in hand
                log.info("steps: suggestions failed")
        if out is not None:
            st.suggestion = {"lines": list(out.lines), "pick": out.pick, "reason": out.reason}
        self._record(st, step, "done", note="suggestions" if out is not None else "no suggestions")
        return Flow.NEXT

    async def _report(self, st: PlanState, step: Step) -> Flow:
        lang, slots = st.lang, st.plan.slots
        lines: list[str] = []
        if st.plan.playbook == "price_check" and st.shown:
            cat = self._cat(st)
            unit = "L" if cat is not None and cat.unit == "l" else "kg"
            where = w.line("r_area", lang, area=st.area) if st.area else ""
            lines.append(w.line("r_head", lang, item=slots.get("item", ""), store=self._site(st), where=where))
            variant = " ".join(x for x in (slots.get("brand", ""), slots.get("pack", "")) if x)
            if st.variant_missing:
                lines.append(w.line("r_variant_missing", lang, variant=variant))
            else:
                lines.append(w.line("r_variant", lang, variant=variant) if variant else w.line("r_main", lang))
            lines += [f"{i}. {parse.row(p, unit)}" for i, p in enumerate(st.shown, 1)]
            sug = st.suggestion
            if sug:
                if sug.get("lines"):
                    lines.append(w.line("r_others", lang, cat=slots.get("category", "")))
                    lines += [f"- {x}" for x in sug["lines"]]  # type: ignore[attr-defined]
                lines.append(w.line("r_pick", lang, name=sug["pick"], reason=sug["reason"]) if sug.get("pick") else w.line("r_no_pick", lang))
        else:
            result = " ".join(v for k, v in st.info.items() if k.startswith("out"))[-300:] or "finished"
            lines.append(w.line("r_done", lang, store=self._site(st), result=result))
        proofs = [p for r in st.records for p in r.proofs]
        snippet = next((r.snippet for r in reversed(st.records) if r.snippet and r.state == "done"), "")
        if proofs:
            lines.append(w.line("r_proof", lang, n=len(proofs), snippet=snippet or "-"))
        elif snippet:
            lines.append(w.line("r_proof_text", lang, snippet=snippet))
        self._record(st, step, "done", note="reported")
        st.status = Status.DONE
        self._save(st)
        self._event("steps.end", plan=st.id, status="done", steps=len(st.records), proofs=len(proofs))
        await self._tell(st, "\n".join(lines))
        return Flow.STOP

    # ================================================================== stopping
    async def _stop(self, st: PlanState, step: Step, why_key: str, *, payment: bool = False, offer: bool = True) -> Flow:
        n, _ = self._counts(st)
        text = w.line("stop", st.lang, n=n, title=self._title(st, step) if step.type != StepType.NEED_LOGIN else self._site(st) + " login",
                      why=w.line(why_key, st.lang, site=self._site(st)))
        st.stop_reason = why_key
        can_web = offer and not payment and self.fallback is not None and st.plan.playbook == "price_check" and bool(st.plan.slots.get("category"))
        self._record(st, step, "failed", note=why_key)
        if can_web:
            st.fallback, st.status = "shopping_web", Status.WAITING_USER
            st.awaiting = Awaiting(kind="fallback", asked_at=self._iso())
            text += "\n" + w.line("offer_web", st.lang, item=st.plan.slots.get("item", ""))
        else:
            st.status = Status.BLOCKED
            where = strip_query(st.plan.start_url) or st.plan.domains[0]
            text += "\n" + w.line("offer_manual", st.lang, where=where) + " " + w.line("nothing_changed", st.lang)
        if self.otp is not None:
            self.otp.wipe(st.id)
        self._save(st)
        self._event("steps.end", plan=st.id, status=st.status.value, reason=why_key)
        await self._tell(st, text)
        return Flow.STOP

    async def _cancel(self, st: PlanState) -> None:
        if st.sub_run_id:
            await self.worker.cancel(st.sub_run_id)
        if self.otp is not None:
            self.otp.wipe(st.id)
        st.status, st.awaiting = Status.CANCELLED, None
        self._save(st)
        self._event("steps.end", plan=st.id, status="cancelled")
        await self._tell(st, w.line("cancelled", st.lang))

    async def _reply_agent(self, st: PlanState, text: str) -> bool:
        step = st.plan.steps[st.idx]
        res = await self.worker.reply(st.sub_run_id, text)
        st.sub_run_id, st.awaiting, st.status = "", None, Status.RUNNING
        flow = await self._loop_result(st, step, res)
        if flow == Flow.NEXT:
            st.idx += 1
        self._save(st)
        if flow in (Flow.NEXT, Flow.RERUN):
            await self._advance_locked(st)
        return True

    # ================================================================== housekeeping
    async def _tick_one(self, st: PlanState) -> int:
        aw = st.awaiting
        if st.status == Status.WAITING_OTP:
            if self.otp is not None and self.otp.ready(st.id):
                await self._enter_code(st)
                return 1
            if aw is not None and self._age(aw.asked_at) > self.otp_ttl:
                step = st.plan.steps[st.idx]
                if st.resends == 0:  # offer ONE resend
                    st.status, st.awaiting = Status.WAITING_USER, Awaiting(kind="resend", asked_at=self._iso())
                    if self.otp is not None:
                        self.otp.wipe(st.id)
                    self._save(st)
                    await self._tell(st, w.line("otp_resend", st.lang, site=self._site(st)))
                else:
                    await self._stop(st, step, "why_otp_late", offer=False)
                return 1
            return 0
        if st.status == Status.WAITING_BUSY:
            if aw is not None and self._age(aw.asked_at) >= self.busy_retry:
                st.status, st.awaiting = Status.RUNNING, None
                await self._advance_locked(st)
                return 1
            return 0
        if st.status in (Status.WAITING_USER, Status.WAITING_AGENT):
            if aw is not None and self._age(aw.asked_at) > self.ask_ttl:
                if st.sub_run_id:
                    await self.worker.cancel(st.sub_run_id)
                st.status, st.awaiting = Status.EXPIRED, None
                self._save(st)
                await self._tell(st, w.line("expired", st.lang))
                return 1
            return 0
        if st.status == Status.RUNNING and self._age(st.updated_at) > 5:  # interrupted by a restart: continue at the saved step
            await self._advance_locked(st)
            return 1
        return 0
