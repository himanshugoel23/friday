# ruff: noqa: E501
"""The browser agent in the live message path.

* ``handle`` (early in ``InboundPipeline._active``): the user's reply to an open question / confirmation, 'stop', the job-apply
  commands. A bare login code is left to the guarded OTP flow.
* ``start_task`` (called by the approach planner for 'do this on a website' requests with no connector): picks the allowed domains
  from what the USER wrote (a link, or a brand word from data/domains.v1.json), never from the model or a page.
* ``tick`` (runtime loop): closes timed-out questions politely, resumes runs that were busy or interrupted by a restart, purges old
  proofs, sends the evening job summary.

A run takes minutes, so it runs in a background task; the user gets one 'on it' line and then the result or the next question.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import timedelta
from typing import Any

from friday.browser_agent import ask, rules, wording
from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.jobapply import URL_RE, ApplyDecision, JobApplyService, ist_day
from friday.browser_agent.types import RunOutcome, RunSpec, Status
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User

log = get_logger(__name__)
STOP_RE = re.compile(r"^\W*(stop|cancel|ruko|rok\s*do|band\s*karo)\W*$", re.I)
JOB_RE = re.compile(r"\bapply\s+(for|to|on)\b.*\b(job|position|role|vacancy)\b|\b(job|position|role)\b.*\bapply\b|\bapply\s+(for|to)\s+this\b", re.I)
DOMAIN_RE = re.compile(r"(?<![@\w])((?:[a-z0-9-]+\.)+(?:com|in|co\.in|org|net|io|app|ai|co|shop|store|online))(?![\w@])", re.I)
PAYLINK_RE = re.compile(r"\b(payment\s+link|pay\s+link|upi\s+(link|qr)|qr\s+code|qr)\b", re.I)
SITE_WAIT = timedelta(minutes=10)
SUMMARY_HOUR_IST = 20


def domains_from_text(text: str) -> tuple[list[str], str]:
    """-> (allowed domains, start url). Only what the user wrote: links, bare domains, or brand words from the data file."""
    urls = [u.rstrip(".,)") for u in URL_RE.findall(text or "")]
    hosts = [rules.host_of(u) for u in urls]
    start = urls[0] if urls else ""
    for m in DOMAIN_RE.findall(text or ""):
        h = m.lower()
        if h not in hosts:
            hosts.append(h)
        if not start:
            start = "https://" + h + "/"
    low = (text or "").lower()
    for brand, doms in rules.brand_domains().items():
        if re.search(rf"\b{re.escape(brand)}\b", low):
            hosts += [d for d in doms if d not in hosts]
            if not start:
                start = "https://" + doms[0] + "/"
    return [h for h in dict.fromkeys(hosts) if h], start


class BrowserAgentGateway:
    def __init__(self, pipeline: Any, agent: BrowserAgent, *, jobs: JobApplyService | None, settings: Any, proofs: Any = None) -> None:
        self.p, self.agent, self.jobs, self.s, self.proofs = pipeline, agent, jobs, settings, proofs
        self._tasks: set[asyncio.Task[Any]] = set()
        self._need_site: dict[str, tuple[str, Any]] = {}
        self.sync = False  # tests: run inline instead of in the background

    # ------------------------------------------------------------------ plumbing
    def _now(self) -> Any:
        return self.p.clock.now()

    async def _say(self, user_id: str, text: str) -> None:
        if text:
            await self.p.notifier.notify_user(user_id, text, buttons=[], task_id=None)

    async def _lang(self, user: User) -> str:
        try:
            return str(await self.p._reply_lang(user))
        except Exception:  # noqa: BLE001
            return "hinglish"

    def _spawn(self, coro: Any) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _bg(self, user_id: str, coro: Any) -> None:
        """Run a long agent call without blocking the inbound handler (inline when ``sync``, for tests)."""
        if self.sync:
            await self._drive(user_id, coro)
        else:
            self._spawn(self._drive(user_id, coro))

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _deliver(self, user_id: str, out: RunOutcome) -> None:
        await self._say(user_id, out.message)
        st = self.agent.store.load(out.run_id)
        if st is not None and st.status in (Status.DONE, Status.CANCELLED, Status.BLOCKED, Status.PAYMENT_STOP, Status.GAVE_UP, Status.BUDGET, Status.EXPIRED, Status.ERROR):
            with contextlib.suppress(Exception):
                await self.p.audit("browser_agent.end", None, run=out.run_id, status=st.status.value, steps=st.step, proofs=len(st.proofs), cost_inr=round(st.spent_inr, 2))
            if st.spec.playbook == "job_apply" and self.jobs is not None:
                self.jobs.record_outcome(st.user_id, out, st.result)

    async def _drive(self, user_id: str, coro: Any) -> None:
        try:
            out = await coro
        except Exception:  # noqa: BLE001 - never lose the user silently
            log.exception("browser agent run failed")
            await self._say(user_id, wording.line("error", "en", manual=""))
            return
        if isinstance(out, ApplyDecision):
            await self._say(user_id, out.message)
        elif out is not None:
            await self._deliver(user_id, out)

    # ------------------------------------------------------------------ inbound
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        lang = await self._lang(user)
        if self.jobs is not None and (reply := await self.jobs.handle_command(user.id, text, lang)) is not None:
            await self._say(user.id, reply)
            return True
        run = self.agent.store.active_for(user.id)
        if run is None:
            return await self._maybe_site_answer(user, text, lang)
        if STOP_RE.match(text):
            out = await self.agent.cancel(run.id)
            if out is not None:
                await self._deliver(user.id, out)
                return True
            return False
        if run.pending is not None:
            if run.pending.ask_kind == "otp" and ask.looks_like_code(text):
                return False  # a login code typed in chat belongs to the guarded OTP flow, never to this module
            await self._bg(user.id, self.agent.reply(run.id, text))
            return True
        if run.status in (Status.BUSY, Status.RUNNING):
            await self._say(user.id, wording.line("busy", run.spec.lang))
            await self._bg(user.id, self.agent.resume(run.id))
            return True
        return False

    async def _maybe_site_answer(self, user: User, text: str, lang: str) -> bool:
        waiting = self._need_site.get(user.id)
        if waiting is None or self._now() - waiting[1] > SITE_WAIT:
            return False
        doms, start = domains_from_text(text)
        if not doms:
            return False
        goal = self._need_site.pop(user.id)[0]
        await self._launch(user, goal + " " + text, lang, doms, start)
        return True

    # ------------------------------------------------------------------ start (called by the planner)
    async def start_task(self, user: User, text: str, lang: str) -> bool:
        if self.jobs is not None and JOB_RE.search(text) and URL_RE.search(text):
            await self._say(user.id, wording.line("ack", lang, host=(domains_from_text(text)[0] or ["the job site"])[0]))
            assert self.jobs is not None
            await self._bg(user.id, self.jobs.apply(user.id, text, lang))
            return True
        doms, start = domains_from_text(text)
        if not doms:
            self._need_site[user.id] = (text, self._now())
            await self._say(user.id, wording.line("no_site", lang))
            return True
        await self._launch(user, text, lang, doms, start)
        return True

    async def _launch(self, user: User, text: str, lang: str, doms: list[str], start: str) -> None:
        s = self.s
        spec = RunSpec(goal=text[:500], allowed_domains=doms, start_url=start or None, lang=lang, handover_payment_link=bool(PAYLINK_RE.search(text)),
                       max_steps=int(s.browser_agent_max_steps), max_seconds=float(s.browser_agent_max_seconds), max_cost_inr=float(s.browser_agent_max_cost_inr))
        await self._say(user.id, wording.line("ack", lang, host=doms[0]))

        await self._bg(user.id, self.agent.start(user.id, spec))

    # ------------------------------------------------------------------ housekeeping (runtime loop)
    async def tick(self) -> int:
        n = 0
        for out in self.agent.sweep():
            st = self.agent.store.load(out.run_id)
            if st is not None:
                await self._deliver(st.user_id, out)
                n += 1
        for st in self.agent.store.list_open():
            if st.pending is None and st.status in (Status.BUSY, Status.RUNNING) and st.id not in self._running():
                await self._bg(st.user_id, self.agent.resume(st.id))
                n += 1
        if self.proofs is not None:
            with contextlib.suppress(Exception):
                self.proofs.purge()
        if self.jobs is not None:
            n += await self._evening_summaries()
        return n

    def _running(self) -> set[str]:
        return {rid for rid, lock in self.agent._locks.items() if lock.locked()}

    async def _evening_summaries(self) -> int:
        assert self.jobs is not None
        now = self._now()
        if (now + timedelta(hours=5, minutes=30)).hour < SUMMARY_HOUR_IST:
            return 0
        day, n = ist_day(now), 0
        for uid in self.jobs.ledger.users_for_day(day):
            rows = self.jobs.ledger.rows(uid, day)
            if any(r["status"] == "summary_sent" for r in rows) or not any(r["status"] == "applied" for r in rows):
                continue
            user = await self.p.repos.users.get(uid)
            lang = await self._lang(user) if user is not None else "hinglish"
            await self._say(uid, self.jobs.evening_summary(uid, lang, day))
            self.jobs.ledger.record(uid, now=now, host="", where="", what="", proof_id="", status="summary_sent")
            n += 1
        return n

    async def forget_user(self, user_id: str) -> None:
        """'Delete everything': runs, proofs, files, the ledger."""
        self.agent.forget_user(user_id)
        if self.proofs is not None:
            self.proofs.delete_user(user_id)
        files = getattr(self.agent, "files", None)
        if hasattr(files, "delete_user"):
            files.delete_user(user_id)
        if self.jobs is not None:
            self.jobs.ledger.delete_user(user_id)
        self._need_site.pop(user_id, None)
