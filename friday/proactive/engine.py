"""Proactive engine (B-9): triggers -> dedupe -> guardrails -> brain.judge_nudge ->
autonomy level -> notifier; plus feedback capture and ignore-learning.

    pe = c.proactive
    await pe.tick()                              # one pass over all active users
    await pe.process(candidate)                  # one candidate (also used for alerts)
    await pe.handle_nudge_action(nudge, "yes")   # n:<nudge_id>:<action> buttons
    await pe.start() / stop()

Actions on buttons ``n:<nudge_id>:<action>``: yes | not_now | stop | ack | undo.
Autonomy (US-10.1): 1 inform (Got it / Stop) · 2 suggest · 3 act on "Yes" ·
4 act automatically (creates the task now, reports with Undo). Level 4 never grants
booking authority: the task engine's approval rule still applies.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any

from friday.core.clock import ist_day_bounds
from friday.core.logging import get_logger
from friday.core.models import (
    AutonomyLevel,
    AutonomySetting,
    FeedbackType,
    Nudge,
    NudgeCandidate,
    NudgeDecision,
    NudgeFeedback,
    NudgeKind,
    NudgeStatus,
    PersonConsent,
    ReplyButton,
    TaskSpec,
    TemplateRef,
    Urgency,
    nudge_button_id,
)
from friday.proactive import triggers
from friday.proactive.guardrails import CAP_EXEMPT_KINDS, Verdict, evaluate
from friday.tasks.categories import autonomy_for
from friday.tasks.context import build_context
from friday.tasks.events import WellbeingAlertRaised
from friday.tasks.outbox import Outbox
from friday.tasks.ports import call_opt, repo

log = get_logger(__name__)

IGNORE_AFTER = timedelta(hours=24)  # no interaction within 24h -> IGNORED (US-10.2)
_DONE = (NudgeStatus.ACTED, NudgeStatus.IGNORED, NudgeStatus.DISMISSED)


class ProactiveEngine:
    def __init__(self, c: Any) -> None:
        self.c = c
        self.settings = c.settings
        self.clock = c.clock
        self.bus = c.bus
        self._nudges: dict[str, Nudge] = {}  # cache for repos lacking get/list
        self._worker: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._lock = asyncio.Lock()
        self.bus.subscribe(WellbeingAlertRaised, self._on_alert)

    # ------------------------------------------------------------------ deps
    def _opt(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except Exception:  # noqa: BLE001
            return None

    @property
    def repos(self) -> Any:
        return self.c.get("repos")

    @property
    def nudges(self) -> Any:
        return self.repos.nudges

    @property
    def outbox(self) -> Outbox:
        return Outbox(notifier=self._opt("notifier"), users=repo(self.repos, "users"))

    # ------------------------------------------------------------------ loop
    async def start(self) -> None:
        if not self.settings.proactive_enabled or (self._worker and not self._worker.done()):
            return
        self._stopping.clear()

        async def loop() -> None:
            while not self._stopping.is_set():
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001
                    log.exception("proactive tick failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), self.settings.proactive_tick_s)

        self._worker = asyncio.create_task(loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._worker:
            await self._worker
            self._worker = None

    async def aclose(self) -> None:
        await self.stop()
        self.bus.unsubscribe(WellbeingAlertRaised, self._on_alert)

    # ------------------------------------------------------------------ tick
    async def tick(self) -> list[Nudge]:
        """One pass: mark ignores, send due scheduled nudges, run all triggers."""
        async with self._lock:
            now = self.clock.now()
            await self._mark_ignored(now)
            out = await self._send_scheduled(now)
            users = await call_opt(repo(self.repos, "users"), "list_active", default=[]) or []
            for user in users:
                for cand in await self.candidates(user.id):
                    nudge = await self.process(cand)
                    if nudge is not None:
                        out.append(nudge)
            return out

    async def candidates(self, user_id: str) -> list[NudgeCandidate]:
        now = self.clock.now()
        tasks = await call_opt(self.repos.tasks, "list_for_user", user_id, default=[]) or []
        facts = (
            await call_opt(repo(self.repos, "facts"), "list_for_user", user_id, default=[]) or []
        )
        profile = await call_opt(repo(self.repos, "profiles"), "get", user_id)
        s = self.settings
        out = [
            *triggers.task_reminders(user_id, tasks, now, s),
            *triggers.follow_ups(user_id, tasks, now, s),
            *triggers.date_facts(user_id, facts, now),
            *triggers.patterns(user_id, tasks, now),
            *triggers.recurring_due(user_id, tasks, now),
            *triggers.stay_reminders(user_id, tasks, now),
            *triggers.wellbeing_alerts(user_id, tasks),
        ]
        if profile is not None:
            out += triggers.morning_briefing(user_id, profile, tasks, facts, now)
        # rank: safety > urgent > normal, earliest due first (US-10.2 #6)
        order = {Urgency.SAFETY: 0, Urgency.URGENT: 1, Urgency.NORMAL: 2}
        return sorted(out, key=lambda c: (order[c.urgency], c.due_at))

    async def _on_alert(self, ev: WellbeingAlertRaised) -> None:
        cand = triggers.alert_candidate(ev.user_id, ev.task_id, ev.person_id, ev.text, ev.at)
        await self.process(cand)

    # ------------------------------------------------------------------ one candidate
    async def process(self, cand: NudgeCandidate) -> Nudge | None:
        """Dedupe -> guardrails -> judge -> autonomy -> send. Returns the stored nudge
        (SENT / SCHEDULED / SUPPRESSED) or None if it was a duplicate."""
        if await self.nudges.exists(cand.user_id, cand.dedupe_key):
            return None
        verdict = await self._guard(cand)
        nudge = Nudge(
            id=cand.nudge_id,
            user_id=cand.user_id,
            kind=cand.kind,
            category=cand.category,
            urgency=cand.urgency,
            dedupe_key=cand.dedupe_key,
            task_id=cand.task_id,
            fact_id=cand.fact_id,
            person_id=cand.person_id,
            reason=verdict.reason or cand.reason,
            created_at=self.clock.now(),
        )
        if verdict.action == "suppress":
            nudge.status = NudgeStatus.SUPPRESSED
            return await self._store(nudge)
        if verdict.action == "schedule":
            nudge.status = NudgeStatus.SCHEDULED
            nudge.scheduled_for = verdict.send_at
            nudge.text = cand.reason  # re-judged when due
            return await self._store(nudge)
        return await self._judge_and_send(nudge, cand)

    async def _guard(self, cand: NudgeCandidate) -> Verdict:
        now = self.clock.now()
        autonomy = await call_opt(
            repo(self.repos, "autonomy"), "list_for_user", cand.user_id, default=[]
        )
        history = await self._history(cand.user_id)
        start, end = ist_day_bounds(now)
        sent_today = sum(
            1
            for n in history
            if n.sent_at
            and start <= n.sent_at < end
            and n.urgency == Urgency.NORMAL
            and n.kind not in CAP_EXEMPT_KINDS
        )
        if not history:  # repo without listing: fall back to its counter
            sent_today = (
                await call_opt(
                    self.nudges, "count_sent_between", cand.user_id, start, end, default=0
                )
                or 0
            )
        same = [n for n in history if n.kind == cand.kind and n.category == cand.category]
        streak, last_ignored = 0, None
        for n in same:  # newest first
            if n.status in (NudgeStatus.IGNORED, NudgeStatus.DISMISSED):
                streak += 1
                last_ignored = last_ignored or n.responded_at or n.sent_at
            elif n.status == NudgeStatus.ACTED:
                break
        last_sent = next((n.sent_at for n in same if n.sent_at), None)
        consent_ok = True
        recipient = cand.data.get("recipient_person_id")
        if recipient:
            person = await call_opt(repo(self.repos, "people"), "get", recipient)
            consent_ok = bool(person and person.contact_consent == PersonConsent.OPTED_IN)
        return evaluate(
            cand,
            now=now,
            settings=self.settings,
            autonomy=autonomy_for(autonomy or [], cand.category),
            sent_today=sent_today,
            ignore_streak=streak,
            last_ignored_at=last_ignored,
            last_sent_same_kind=last_sent,
            recipient_consent_ok=consent_ok,
        )

    async def _history(self, user_id: str) -> list[Nudge]:
        listed = await call_opt(self.nudges, "list_for_user", user_id, limit=100)
        if listed is not None:
            return listed
        mine = [n for n in self._nudges.values() if n.user_id == user_id]
        return sorted(mine, key=lambda n: n.created_at, reverse=True)

    async def _judge_and_send(self, nudge: Nudge, cand: NudgeCandidate) -> Nudge:
        ctx = await build_context(self.repos, cand.user_id, self.clock.now())
        try:
            decision = await self.c.get("brain").judge_nudge(ctx, cand)
        except Exception as e:  # noqa: BLE001 - fall back to a plain, actionable nudge
            log.error("judge_nudge failed: %r", e)
            decision = NudgeDecision(send=True, text=cand.reason, reason="fallback")
        if not decision.send:
            nudge.status = NudgeStatus.SUPPRESSED
            nudge.reason = decision.reason or "brain said no"
            return await self._store(nudge)
        setting = autonomy_for(ctx.autonomy, cand.category)
        level = setting.level if setting else AutonomyLevel.SUGGEST
        text = decision.text or cand.reason
        nudge.proposed_task = decision.proposed_task if level > AutonomyLevel.INFORM else None
        if (
            level == AutonomyLevel.ACT_AUTOMATICALLY
            and nudge.proposed_task is not None
            and cand.urgency != Urgency.SAFETY
        ):
            task = await self._create_task(nudge, nudge.proposed_task)
            nudge.task_id = task.id if task is not None else nudge.task_id
            nudge.status = NudgeStatus.ACTED
            text = f"{text}\nI've started on it."
            buttons = [ReplyButton(id=nudge_button_id(nudge.id, "undo"), title="Undo")]
        else:
            buttons = self._buttons(nudge, decision, level)
        nudge.text = text
        nudge.buttons = buttons
        nudge.sent_at = self.clock.now()
        if nudge.status != NudgeStatus.ACTED:
            nudge.status = NudgeStatus.SENT
        await self._store(nudge)
        await self.outbox.to_user(
            nudge.user_id,
            text,
            buttons=buttons,
            nudge_id=nudge.id,
            urgency=nudge.urgency,
            template=decision.template or TemplateRef(key="nudge", params=[text[:900]]),
        )
        return nudge

    def _buttons(
        self, nudge: Nudge, decision: NudgeDecision, level: AutonomyLevel
    ) -> list[ReplyButton]:
        """Every nudge offers an action (US-10.2 #4)."""
        if level == AutonomyLevel.INFORM or nudge.kind == NudgeKind.MORNING_BRIEFING:
            return [
                ReplyButton(id=nudge_button_id(nudge.id, "ack"), title="Got it"),
                ReplyButton(id=nudge_button_id(nudge.id, "stop"), title="Stop these"),
            ]
        if decision.buttons:  # brain's copy; ids re-keyed to this nudge
            out = []
            for b in decision.buttons[:3]:
                action = b.id.rsplit(":", 1)[-1] if b.id.startswith("n:") else b.id
                out.append(ReplyButton(id=nudge_button_id(nudge.id, action), title=b.title))
            return out
        first = "Yes" if nudge.proposed_task else "Got it"
        return [
            ReplyButton(
                id=nudge_button_id(nudge.id, "yes" if nudge.proposed_task else "ack"), title=first
            ),
            ReplyButton(id=nudge_button_id(nudge.id, "not_now"), title="Not now"),
            ReplyButton(id=nudge_button_id(nudge.id, "stop"), title="Stop these"),
        ]

    async def _store(self, nudge: Nudge) -> Nudge:
        new = nudge.id not in self._nudges and not await call_opt(self.nudges, "get", nudge.id)
        self._nudges[nudge.id] = nudge
        if new:
            await self.nudges.add(nudge)
        else:
            await self.nudges.save(nudge)
        return nudge

    async def _get(self, nudge_id: str) -> Nudge | None:
        return await call_opt(self.nudges, "get", nudge_id) or self._nudges.get(nudge_id)

    async def _send_scheduled(self, now) -> list[Nudge]:
        due = await call_opt(self.nudges, "list_scheduled_due", now)
        if due is None:
            due = [
                n
                for n in self._nudges.values()
                if n.status == NudgeStatus.SCHEDULED and n.scheduled_for and n.scheduled_for <= now
            ]
        out = []
        for n in due:
            cand = NudgeCandidate(
                user_id=n.user_id,
                kind=n.kind,
                category=n.category,
                urgency=n.urgency,
                reason=n.text or n.reason,
                due_at=now,
                task_id=n.task_id,
                fact_id=n.fact_id,
                person_id=n.person_id,
                dedupe_key=n.dedupe_key,
            )
            verdict = await self._guard(cand)  # the cap may have filled up meanwhile
            if verdict.action != "send":
                n.status = NudgeStatus.SUPPRESSED
                n.reason = verdict.reason
                await self._store(n)
                continue
            out.append(await self._judge_and_send(n, cand))
        return out

    async def _mark_ignored(self, now) -> None:
        cutoff = now - IGNORE_AFTER
        stale = await call_opt(self.nudges, "list_sent_unanswered_before", cutoff)
        if stale is None:
            stale = [
                n
                for n in self._nudges.values()
                if n.status == NudgeStatus.SENT and n.responded_at is None and n.sent_at < cutoff
            ]
        for n in stale:
            await self.record_feedback(n, FeedbackType.IGNORED)

    # ------------------------------------------------------------------ feedback
    async def handle_nudge_action(self, nudge: Nudge | str, action: str) -> Nudge | None:
        """Button ``n:<id>:<action>`` or an equivalent reply (inbound pipeline)."""
        n = await self._get(nudge) if isinstance(nudge, str) else nudge
        if n is None:
            return None
        a = action.lower()
        if a in ("yes", "book", "go", "call"):
            if n.proposed_task is not None:
                task = await self._create_task(n, n.proposed_task)
                n.task_id = task.id if task else n.task_id
            return await self.record_feedback(n, FeedbackType.ACTED)
        if a in ("ack", "got_it", "ok", "done"):
            return await self.record_feedback(n, FeedbackType.ACTED)
        if a in ("stop", "off"):
            await self._stop_category(n)
            return await self.record_feedback(n, FeedbackType.STOP)
        if a == "undo":
            engine = self._opt("task_engine")
            if n.task_id and engine is not None:
                await engine.cancel(n.task_id)
            return await self.record_feedback(n, FeedbackType.DISMISSED)
        if a in ("snooze", "later"):
            return await self.record_feedback(n, FeedbackType.SNOOZED)
        return await self.record_feedback(n, FeedbackType.DISMISSED)

    async def record_feedback(self, nudge: Nudge, fb: FeedbackType) -> Nudge:
        status = {
            FeedbackType.ACTED: NudgeStatus.ACTED,
            FeedbackType.IGNORED: NudgeStatus.IGNORED,
            FeedbackType.DISMISSED: NudgeStatus.DISMISSED,
            FeedbackType.STOP: NudgeStatus.DISMISSED,
            FeedbackType.SNOOZED: NudgeStatus.DISMISSED,
        }[fb]
        nudge.status = status
        nudge.responded_at = self.clock.now()  # replied, or judged ignored
        await self._store(nudge)
        await call_opt(
            self.nudges,
            "add_feedback",
            NudgeFeedback(nudge_id=nudge.id, user_id=nudge.user_id, type=fb, at=self.clock.now()),
        )
        return nudge

    async def _stop_category(self, nudge: Nudge) -> None:
        store = repo(self.repos, "autonomy")
        current = autonomy_for(
            await call_opt(store, "list_for_user", nudge.user_id, default=[]) or [], nudge.category
        )
        setting = (
            current or AutonomySetting(user_id=nudge.user_id, category=nudge.category)
        ).model_copy(update={"enabled": False, "updated_at": self.clock.now()})
        await call_opt(store, "upsert", setting)

    async def _create_task(self, nudge: Nudge, spec: TaskSpec):
        engine = self._opt("task_engine")
        if engine is None:
            log.warning("no task engine to act on nudge %s", nudge.id)
            return None
        return await engine.create_task(
            nudge.user_id, spec, beneficiary_person_id=nudge.person_id, approved=True
        )


def build_proactive_engine(c: Any) -> ProactiveEngine:  # c: Container
    return ProactiveEngine(c)
