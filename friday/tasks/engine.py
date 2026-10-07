"""Task engine (B-6): the state machine that turns requests into calls and results.

Public API (Backend A's inbound pipeline + CallbackService call these by name):

    await engine.submit(task)                        # task may already be persisted (CREATED)
    await engine.handle_answer(UserAnswer(...))      # q:<qid>:<i> buttons / free text
    await engine.approve(task_id, True|False)        # a:<task>:yes|no
    await engine.choose(task_id, index)              # comparison pick
    await engine.cancel(task_id)
    await engine.update_spec(task_id, spec)          # NEEDS_INFO filled / task edited
    await engine.start() / stop()                    # queue worker
    # BRIEF E.30-37 (match = repos.calls.match(...) -> CallbackMatch)
    await engine.handle_business_callback(match, contact)
    await engine.handle_missed_call(match, contact)
    await engine.handle_business_message(msg, match)
    await engine.handle_unknown_caller(match, contact)
    # also: create_task(), handle_button(), pending_question(), tick(), drain(),
    #       on_inbound_call(caller, dialled, leg=...), on_missed_call(caller, dialled)

Founder approval rule (final): the engine is the authority for ``CallBrief.delegation``
and ``CallBrief.approved_terms`` - it overwrites whatever the brain put there, so
Friday can only commit on a confirmation call-back with user-approved terms, or under
the user's explicit Delegation (task or recurring rule).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from friday.core.clock import at_ist, format_ist, ist_day_bounds, to_ist
from friday.core.events import (
    MidCallQuestionAsked,
    TaskStatusChanged,
    UserAnswerReceived,
)
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    AuditEntry,
    Beneficiary,
    Business,
    BusinessCandidate,
    BusinessHours,
    CallBrief,
    CallOutcome,
    CallResult,
    Channel,
    ContactTarget,
    Delegation,
    DialStatus,
    FanOutPolicy,
    FanOutStrategy,
    HotelBooking,
    HotelBookingMode,
    HotelBookingStatus,
    HotelOffer,
    HotelProperty,
    InteractionKind,
    MidCallQuestion,
    NumberCheck,
    NumberVerdict,
    PersonConsent,
    QuestionPurpose,
    Quote,
    ReplyButton,
    ShortlistItem,
    TargetKind,
    Task,
    TaskResult,
    TaskSpec,
    TaskType,
    TemplateRef,
    UserAnswer,
    VendorInteraction,
    approval_button_id,
    parse_button_id,
    question_button_id,
)
from friday.core.models import TaskStatus as S
from friday.discovery.geo import is_toll_free, phone_key
from friday.tasks import states
from friday.tasks.categories import category_for, level_for
from friday.tasks.context import build_context
from friday.tasks.events import BusinessContactLogged, WellbeingAlertRaised
from friday.tasks.outbox import Outbox
from friday.tasks.policy import TaskPolicy
from friday.tasks.ports import call_opt, repo
from friday.tasks.recurrence import next_run
from friday.tasks.scheduling import next_call_time, retry_at

log = get_logger(__name__)

# ------------------------------------------------------------------ child roles
# Persisted as a tag in ``spec.notes`` until core gets ``Task.role`` (CORE_CHANGES).
ROLE_FANOUT = "fanout"  # one candidate of a discovery/compare/stock-hunt parent
ROLE_BOOKING = "booking"  # booking call for the option the user chose
ROLE_INSTANCE = "instance"  # one occurrence of a recurring series
ROLE_RECONFIRM = "reconfirm"  # hotel day-before reconfirm
ROLE_CARE_FOLLOWUP = "care_followup"  # C25 follow-up at promised date
ROLE_CALLBACK = "callback"  # business called back about a resolved booking (E.32/37)
ROLE_CLOSE_LOOP = "close_loop"  # polite "need already met" call-back (E.37)
ROLE_RETRY = "retry"  # user asked to try again later / tomorrow
_ROLE_RE = re.compile(r"\[friday:role=(\w+)\]")

# children created as part of satisfying the parent's need (cancelled when it resolves)
_NEED_ROLES = {ROLE_FANOUT}
# children that are reported to the user individually
_SILENT_ROLES = {ROLE_FANOUT, ROLE_CLOSE_LOOP}

CHILD_TYPE = {TaskType.DISCOVERY: TaskType.QUOTE}
BOOKING_TYPES = {
    TaskType.BOOKING,
    TaskType.ORDER,
    TaskType.HEALTHCARE,
    TaskType.HOTEL_BOOKING,
    TaskType.RESCHEDULE,
}
# a pure decline ("None", "neither", "nahi"); "neither, ask for Sunday" is a new choice
DECLINE_WORDS = re.compile(
    r"^\s*(none( of (these|them))?|neither|no( thanks)?|nahi+n?|cancel|don'?t book( it)?)[\s.!]*$",
    re.I,
)


def role_of(task: Task) -> str | None:
    m = _ROLE_RE.search(task.spec.notes or "")
    return m.group(1) if m else None


def with_role(spec: TaskSpec, role: str, **updates: Any) -> TaskSpec:
    notes = _ROLE_RE.sub("", spec.notes or "").strip()
    tag = f"[friday:role={role}]"
    return spec.model_copy(update={**updates, "notes": f"{tag} {notes}".strip()})


class TaskAborted(Exception):  # noqa: N818 - control flow
    """The task was cancelled/resolved concurrently; stop working on it."""


class InboundPlan:
    """What to do with an inbound business contact (call, missed call, message)."""

    def __init__(
        self,
        action: str,
        *,
        task_ids: list[str] | None = None,
        brief: CallBrief | None = None,
        verified: bool = False,
        result: CallResult | None = None,
        note: str = "",
    ) -> None:
        # action: resume | about_booking | close_loop | choose_task | take_message |
        #         callback_scheduled | relayed | logged
        self.action = action
        self.task_ids = task_ids or []
        self.brief = brief
        self.verified = verified
        self.result = result
        self.note = note

    def __repr__(self) -> str:  # pragma: no cover
        return f"InboundPlan({self.action}, tasks={self.task_ids}, verified={self.verified})"


class TaskEngine:
    def __init__(self, c: Any, *, policy: TaskPolicy | None = None) -> None:
        self.c = c
        self.settings = c.settings
        self.clock = c.clock
        self.bus = c.bus
        self.policy = policy or TaskPolicy()
        self._global_calls = asyncio.Semaphore(max(1, self.settings.max_concurrent_calls))
        self._jobs: dict[str, set[asyncio.Task]] = {}
        self._calls: dict[str, asyncio.Task] = {}  # task_id -> running call coroutine task
        self._pending: dict[str, tuple[asyncio.Future, str, str, MidCallQuestion]] = {}
        self._offer_questions: dict[str, str] = {}  # question id -> task id
        self._retry_questions: dict[str, str] = {}  # final-failure options -> task id
        self._parent_locks: dict[str, asyncio.Lock] = {}
        self._verified: dict[str, NumberCheck] = {}
        self._calls_today: dict[tuple[str, str], int] = {}
        self._worker: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # Friday caller-ID pool (E.30). Settings.friday_numbers is proposed for core.
        self.caller_ids: list[str] = list(
            getattr(self.settings, "friday_numbers", None)
            or self.policy.caller_ids
            or [
                n
                for n in (
                    self.settings.twilio_from_number,
                    self.settings.exotel_caller_id,
                    self.settings.plivo_from_number,
                )
                if n
            ]
        )

    # ================================================================== deps
    def _opt(self, name: str) -> Any:
        try:
            return self.c.get(name)
        except Exception as e:  # noqa: BLE001 - component not built yet / no key
            log.debug("component %s unavailable: %r", name, e)
            return None

    @property
    def repos(self) -> Any:
        return self.c.get("repos")

    @property
    def tasks(self) -> Any:
        return self.repos.tasks

    @property
    def brain(self) -> Any:
        return self.c.get("brain")

    @property
    def runner(self) -> Any:
        return self.c.get("call_runner")

    @property
    def outbox(self) -> Outbox:
        return Outbox(
            notifier=self._opt("notifier"), users=repo(self.repos, "users"), sms=self._opt("sms")
        )

    @property
    def calls(self) -> Any:
        """Call memory (Backend A: ``repos.calls`` - record_outbound / choose_number /
        match / inbound_for_task)."""
        return repo(self.repos, "calls")

    # ================================================================== lifecycle
    def _spawn(self, task_id: str, coro: Awaitable[Any]) -> asyncio.Task:
        job = asyncio.ensure_future(coro)
        self._jobs.setdefault(task_id, set()).add(job)

        def done(j: asyncio.Task) -> None:
            self._jobs.get(task_id, set()).discard(j)
            if not j.cancelled() and j.exception() is not None:
                log.error("task %s job failed: %r", task_id, j.exception())

        job.add_done_callback(done)
        return job

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait until no engine work is in flight (tests / graceful shutdown)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            jobs = [j for js in self._jobs.values() for j in js if not j.done()]
            if not jobs:
                return
            if loop.time() > deadline:
                raise TimeoutError(f"{len(jobs)} engine jobs still running")
            await asyncio.wait(jobs, timeout=max(0.01, deadline - loop.time()))

    async def start(self, poll_s: float = 5.0) -> None:
        """Queue worker: dials due SCHEDULED tasks. Cadence uses real time; every
        scheduling decision uses ``Clock.now()``."""
        if self._worker and not self._worker.done():
            return
        self._stopping.clear()

        async def loop() -> None:
            while not self._stopping.is_set():
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001
                    log.exception("task engine tick failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), poll_s)

        self._worker = asyncio.create_task(loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._worker:
            await self._worker
            self._worker = None

    async def aclose(self) -> None:
        await self.stop()
        for js in self._jobs.values():
            for j in js:
                j.cancel()

    async def tick(self) -> int:
        """Start every due task (SCHEDULED retries/queued calls/recurring runs)."""
        now = self.clock.now()
        due = await self.tasks.list_due(now)
        started = 0
        for task in due:
            if any(not j.done() for j in self._jobs.get(task.id, set())):
                continue
            self._spawn(task.id, self._run(task.id))
            started += 1
        return started

    # ================================================================== public API
    async def create_task(
        self,
        user_id: str,
        spec: TaskSpec,
        *,
        beneficiary_person_id: str | None = None,
        place_id: str | None = None,
        source_message_id: str | None = None,
        approved: bool = True,
    ) -> Task:
        task = Task(
            requester_user_id=user_id,
            beneficiary=Beneficiary(person_id=beneficiary_person_id),
            place_id=place_id,
            type=spec.type,
            spec=spec,
            delegation=spec.delegation,
            recurrence=spec.recurrence,
            max_attempts=self.policy.max_attempts,
            source_message_id=source_message_id,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        return await self.submit(task, approved=approved)

    async def submit(self, task: Task, *, approved: bool = True) -> Task:
        """Persist a new task and start working on it in the background.

        ``approved=False`` asks the user before dialling (proactive suggestions at
        autonomy < 4). A user's own request is already their approval (US-3.4).
        Customer-care calls always get a pre-call summary + Go (US-30.2)."""
        if not task.delegation.granted and task.spec.delegation.granted:
            task.delegation = task.spec.delegation
        if task.recurrence is None and task.spec.recurrence is not None:
            task.recurrence = task.spec.recurrence
        existing = await self.tasks.get(task.id)
        if existing is None:
            task = await self.tasks.add(task)
            await self._audit(task, "task.created", type=task.type.value, approved=approved)
        else:  # persisted by the inbound pipeline; keep our normalisation
            task = await self.tasks.save(task)
        self._spawn(task.id, self._run(task.id, needs_approval=not approved))
        return task

    async def cancel(self, task_id: str, *, by_user: bool = True) -> Task | None:
        task = await self.tasks.get(task_id)
        if task is None or task.status.is_terminal:
            return task
        for child in await self.tasks.list_children(task_id):
            if not child.status.is_terminal and role_of(child) in _NEED_ROLES | {ROLE_BOOKING}:
                await self.cancel(child.id, by_user=False)
        job = self._calls.pop(task_id, None)
        task = await self._transition(task, S.CANCELLED, force=True)
        if job and not job.done():
            polite = getattr(self.runner, "cancel", None)
            if callable(polite):  # runner wraps up politely -> outcome CANCELLED
                self._calls[task_id] = job
                polite(task_id)
            else:
                job.cancel()
        for qid, (fut, tid, _, _) in list(self._pending.items()):
            if tid == task_id and not fut.done():
                fut.set_result(None)
        if task.recurrence is not None:
            await self._audit(task, "series.stopped")
        if by_user:
            await self.outbox.to_user(task.requester_user_id, "Cancelled.", task_id=task.id)
        return task

    async def update_spec(self, task_id: str, spec: TaskSpec) -> Task | None:
        """User edited / completed the spec. NEEDS_INFO resumes planning; a task that
        hasn't dialled yet is re-planned; a live call keeps going with the old spec."""
        task = await self.tasks.get(task_id)
        if task is None or task.status.is_terminal:
            return task
        if task.status == S.NEEDS_INFO:
            return await self.provide_info(task_id, spec)
        task.spec = spec
        if spec.delegation.granted:
            task.delegation = spec.delegation
        task = await self._save(task)
        await self._audit(task, "task.updated")
        return task

    async def handle_answer(self, answer: UserAnswer) -> bool:
        return await self.answer_question(answer)

    async def provide_info(self, task_id: str, spec: TaskSpec | None = None) -> Task | None:
        """NEEDS_INFO -> PLANNING once the user filled the gap (or consent arrived)."""
        task = await self.tasks.get(task_id)
        if task is None or task.status != S.NEEDS_INFO:
            return task
        if spec is not None:
            task.spec = spec
            if spec.delegation.granted:
                task.delegation = spec.delegation
        task = await self._transition(task, S.PLANNING)
        self._spawn(task.id, self._run(task.id))
        return task

    def pending_question(self, user_id: str) -> MidCallQuestion | None:
        """Outstanding question for ``ConversationContext.pending_question``: a live
        mid-call question first, else the latest approval/choice question."""
        live = [q for (_, _, uid, q) in self._pending.values() if uid == user_id]
        if live:
            return live[-1]
        return None

    async def handle_button(self, user_id: str, button_id: str) -> bool:
        parsed = parse_button_id(button_id)
        if parsed is None:
            return False
        kind, ref, value = parsed
        if kind == "q":
            try:
                idx = int(value)
            except ValueError:
                return False
            q = await self._find_question(ref)
            text = q.options[idx] if q and 0 <= idx < len(q.options) else value
            answer = UserAnswer(
                question_id=ref,
                text=text,
                option_index=idx,
                approves=bool(q)
                and q.purpose == QuestionPurpose.APPROVE_BOOKING
                and not DECLINE_WORDS.match(text),
                answered_at=self.clock.now(),
            )
            return await self.answer_question(answer)
        if kind == "a":
            task = await self.tasks.get(ref)
            if task is None or task.requester_user_id != user_id:
                return False
            await self.approve(ref, value == "yes", source=button_id)
            return True
        return False

    async def answer_question(self, answer: UserAnswer) -> bool:
        """Route an answer: live mid-call question, offer approval, choice, or the
        final-failure options."""
        pending = self._pending.get(answer.question_id)
        if pending is not None:
            fut = pending[0]
            if not fut.done():
                fut.set_result(answer)
            return True
        q = await self._find_question(answer.question_id)
        task_id = (
            self._offer_questions.get(answer.question_id)
            or self._retry_questions.get(answer.question_id)
            or (q.task_id if q else None)
        )
        if task_id is None:
            return False
        task = await self.tasks.get(task_id)
        if task is None:
            return False
        if answer.question_id in self._retry_questions:
            await self._handle_retry_choice(task, answer)
            return True
        decline = bool(DECLINE_WORDS.match(answer.text or "")) and not answer.approves
        if task.status == S.AWAITING_CHOICE:
            if decline or answer.option_index is None:
                if decline:
                    await self.reject(task.id, source=f"answer:{answer.question_id}")
                    return True
                return False
            await self.choose(task.id, answer.option_index)
            return True
        if task.status == S.AWAITING_APPROVAL:
            if decline:
                await self.reject(task.id, source=f"answer:{answer.question_id}")
            elif answer.option_index is not None or answer.approves:
                await self.approve(
                    task.id, option_index=answer.option_index, source=f"q:{answer.question_id}"
                )
            else:  # free text: "neither, ask for Sunday" -> relay a different choice
                await self.approve(
                    task.id,
                    terms=f"User asked instead: {answer.text}",
                    source=f"q:{answer.question_id}",
                )
            return True
        return False

    async def approve(
        self,
        task_id: str,
        approve: bool = True,
        *,
        option_index: int | None = None,
        terms: str | None = None,
        source: str | None = None,
    ) -> Task | None:
        if not approve:
            return await self.reject(task_id, source=source)
        task = await self.tasks.get(task_id)
        if task is None:
            return None
        if task.status == S.AWAITING_CHOICE:
            return await self.choose(task_id, option_index or 0)
        if task.status != S.AWAITING_APPROVAL:
            return task
        await self._audit(task, "task.approved", source=source, option=option_index)
        if task.last_outcome in (CallOutcome.PENDING_APPROVAL, CallOutcome.USER_TIMEOUT):
            # offer approval -> confirmation call-back with the approved terms
            q = task.result.needs_approval if task.result else None
            if terms is None:
                options = [o for o in (q.options if q else []) if not DECLINE_WORDS.match(o)]
                pick = (
                    q.options[option_index]
                    if q and option_index is not None and option_index < len(q.options)
                    else (options[0] if options else None)
                )
                terms = _terms_text(pick, task.result)
            task.approved_terms = terms
            task.attempts = 0
            await self._queue_dial(task)
            return task
        if task.shortlist and not await self.tasks.list_children(task.id):
            await self._start_children(task)  # shortlist approved
            return task
        await self._queue_dial(task)  # pre-call approval ("Go")
        return task

    async def reject(self, task_id: str, *, source: str | None = None) -> Task | None:
        task = await self.tasks.get(task_id)
        if task is None or task.status not in (S.AWAITING_APPROVAL, S.AWAITING_CHOICE):
            return task
        await self._audit(task, "task.declined", source=source)
        offer = task.last_outcome == CallOutcome.PENDING_APPROVAL
        task = await self._transition(task, S.CANCELLED)
        if offer and task.target and task.target.kind == TargetKind.BUSINESS:
            # politely let the business release the slot (no call needed)
            await self.outbox.to_business(
                task.target.phone,
                TemplateRef(key="business_booking_declined", params=[task.target.name]),
                business_id=task.target.business_id,
                task_id=task.id,
            )
        await self.outbox.to_user(task.requester_user_id, "Okay, I won't book it.", task_id=task.id)
        await self._on_terminal(task)
        return task

    async def choose(self, task_id: str, index: int) -> Task | None:
        """AWAITING_CHOICE -> booking child for the chosen offer (the tap IS approval)."""
        parent = await self.tasks.get(task_id)
        if parent is None or parent.status != S.AWAITING_CHOICE or parent.result is None:
            return parent
        ranked = parent.result.comparison.ranked_quotes if parent.result.comparison else []
        ranked = ranked or parent.result.quotes
        if not 0 <= index < len(ranked):
            return parent
        quote = ranked[index]
        children = await self.tasks.list_children(parent.id)
        source = next(
            (ch for ch in children if quote.task_id and ch.id == quote.task_id),
            None,
        ) or next(
            (ch for ch in children if ch.target and ch.target.name == quote.business_name), None
        )
        if source is None or source.target is None:
            log.warning("chosen quote has no callable source task")
            return parent
        btype = (
            TaskType.HOTEL_BOOKING if parent.type == TaskType.HOTEL_BOOKING else TaskType.BOOKING
        )
        child = Task(
            requester_user_id=parent.requester_user_id,
            beneficiary=parent.beneficiary,
            place_id=parent.place_id,
            type=btype,
            spec=with_role(
                parent.spec,
                ROLE_BOOKING,
                type=btype,
                business_name=source.target.name,
                business_phone=source.target.phone,
                business_id=source.target.business_id,
                fan_out=None,
                recurrence=None,
            ),
            target=source.target,
            candidate=source.candidate,
            parent_task_id=parent.id,
            approved_terms=_terms_text(None, None, quote=quote),
            delegation=parent.delegation,
            max_attempts=self.policy.max_attempts,
            created_at=self.clock.now(),
        )
        child = await self.tasks.add(child)
        parent.result.details["booking_child_id"] = child.id
        await self._audit(parent, "task.chosen", index=index, business=quote.business_name)
        await self._transition(parent, S.WAITING_CHILDREN)
        self._spawn(child.id, self._run(child.id))
        return parent

    # ================================================================== dispatcher
    async def _run(self, task_id: str, *, needs_approval: bool = False) -> None:
        task = await self.tasks.get(task_id)
        if task is None or task.status.is_terminal:
            return
        try:
            if task.status == S.CREATED:
                task = await self._transition(task, S.PLANNING)
            if task.status == S.PLANNING:
                await self._plan(task, needs_approval=needs_approval)
            elif task.status == S.SCHEDULED:
                if task.recurrence is not None and task.parent_task_id is None:
                    if task.recurrence.next_run_at is None:  # queued before planning
                        task = await self._transition(task, S.PLANNING)
                        await self._plan(task, needs_approval=needs_approval)
                    else:
                        await self._run_recurring(task)
                elif task.target is None and not task.approved_terms:
                    task = await self._transition(task, S.PLANNING)  # queued before planning
                    await self._plan(task, needs_approval=needs_approval)
                else:
                    await self._queue_dial(task)
            elif task.status in (S.CALLING, S.CONFIRMATION_CALLBACK):
                await self._call(task)
            elif task.status == S.DISCOVERING:
                await self._discover(task)
            elif task.status == S.WAITING_CHILDREN:
                await self._pump_children(task)
        except TaskAborted:
            log.info("task %s aborted (resolved concurrently)", task_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - never leave a task hanging
            log.exception("task %s failed", task_id)
            fresh = await self.tasks.get(task_id)
            if fresh and not fresh.status.is_terminal:
                fresh.result = TaskResult(
                    success=False, summary="Sorry, something went wrong on my side."
                )
                await self._transition(fresh, S.FAILED, force=True)
                await self._report(fresh, fresh.result)
                await self._on_terminal(fresh)
            _ = e

    async def _transition(self, task: Task, new: S, *, force: bool = False, **updates: Any) -> Task:
        current = await self.tasks.get(task.id)
        old = current.status if current else task.status
        if old.is_terminal and old != new:
            raise TaskAborted(task.id)
        if not force:
            states.check(old, new)
        for k, v in updates.items():
            setattr(task, k, v)
        task.status = new
        task.updated_at = self.clock.now()
        task = await self.tasks.save(task)
        if old != new:
            await self.bus.publish(
                TaskStatusChanged(
                    task_id=task.id,
                    user_id=task.requester_user_id,
                    old=old,
                    new=new,
                    at=self.clock.now(),
                )
            )
            await self._audit(task, "task.status", old=old.value, new=new.value)
        return task

    async def _save(self, task: Task) -> Task:
        task.updated_at = self.clock.now()
        return await self.tasks.save(task)

    async def _audit(self, task: Task, action: str, **detail: Any) -> None:
        entry = AuditEntry(
            user_id=task.requester_user_id,
            actor="friday",
            action=action,
            subject_id=task.id,
            detail={k: v for k, v in detail.items() if v is not None},
            at=self.clock.now(),
        )
        await call_opt(repo(self.repos, "audit"), "add", entry)

    async def _context(self, user_id: str):
        return await build_context(self.repos, user_id, self.clock.now())

    # ================================================================== planning
    async def _plan(self, task: Task, *, needs_approval: bool = False) -> None:
        spec = task.spec
        if task.parent_task_id is None and task.recurrence is not None:
            if task.type in (TaskType.RECURRING_BOOKING, TaskType.WELLBEING_CHECKIN):
                await self._plan_recurring(task)
                return
        if spec.missing:
            await self._needs_info(task, spec.missing)
            return
        if task.type == TaskType.WELLBEING_CHECKIN and not await self._checkin_target(task):
            return
        if task.type == TaskType.CUSTOMER_CARE and task.target is None:
            if not await self._care_target(task):
                return
            needs_approval = needs_approval or task.parent_task_id is None
        if task.parent_task_id is None and task.target is None:
            if task.type == TaskType.HOTEL_BOOKING and spec.stay:
                await self._transition(task, S.DISCOVERING)
                await self._discover(task)
                return
            if spec.needs_discovery:
                await self._transition(task, S.DISCOVERING)
                await self._discover(task)
                return
        if task.target is None and not await self._business_target(task):
            return
        if task.target.kind == TargetKind.BUSINESS and not await self._vet_number(task):
            return
        if needs_approval and not task.approved_terms:
            await self._ask_call_approval(task)
            return
        await self._queue_dial(task)

    async def _needs_info(self, task: Task, missing: list[str], text: str | None = None) -> None:
        task.spec.missing = list(missing)
        await self._transition(task, S.NEEDS_INFO)
        await self.outbox.to_user(
            task.requester_user_id,
            text or "Before I call, I need: " + ", ".join(m.replace("_", " ") for m in missing),
            task_id=task.id,
        )

    async def _checkin_target(self, task: Task) -> bool:
        people = repo(self.repos, "people")
        person = await call_opt(people, "get", task.beneficiary.person_id or "")
        if person is None or not person.phone:
            await self._needs_info(task, ["beneficiary"], "Whom should I call for the check-in?")
            return False
        if person.checkin_consent != PersonConsent.OPTED_IN:
            await self._needs_info(
                task,
                ["checkin_consent"],
                f"{person.name} hasn't agreed to check-in calls yet. I'll start once they opt in.",
            )
            return False
        task.target = ContactTarget(
            kind=TargetKind.PERSON,
            name=person.name,
            phone=person.phone,
            person_id=person.id,
            language_hint=person.language,
        )
        return True

    async def _care_target(self, task: Task) -> bool:
        """Official numbers only (C26 / US-35)."""
        spec = task.spec
        company = spec.company or spec.business_name or ""
        official = self._opt("official_numbers")
        nums = (
            await call_opt(
                official,
                "lookup",
                company,
                purpose=spec.category or (spec.care_request or None),
                default=[],
            )
            or []
        )
        phone = None
        if spec.business_phone:
            match = await call_opt(official, "find_by_phone", spec.business_phone)
            if match is not None:
                phone = spec.business_phone
            else:
                check = await self._verify(spec.business_phone, company=company, name=company)
                if nums:
                    phone = nums[0].phone
                    await self.outbox.to_user(
                        task.requester_user_id,
                        f"The number you gave isn't on {company}'s official list "
                        f"({'; '.join(check.signals[:2]) or 'unverified'}). "
                        f"I'll use their official number instead.",
                        task_id=task.id,
                    )
                elif check.verdict in (NumberVerdict.SCAM, NumberVerdict.SUSPICIOUS):
                    await self._fail(
                        task, f"I can't verify that number for {company}, so I won't call it."
                    )
                    return False
                else:
                    phone = spec.business_phone
        elif nums:
            phone = nums[0].phone
        if not phone:
            await self._fail(
                task,
                f"I can't verify an official {company} customer-care number yet. If you have one "
                "from their app or a bill, send it and I'll check it.",
            )
            return False
        task.target = ContactTarget(
            kind=TargetKind.BUSINESS, name=company or "customer care", phone=phone
        )
        await self._attach_business(task, is_customer_care=True)
        return True

    async def _business_target(self, task: Task) -> bool:
        spec = task.spec
        phone = spec.business_phone
        name = spec.business_name
        if not phone and name:  # US-3.2: memory, then a directory lookup by name
            businesses = repo(self.repos, "businesses")
            known = await call_opt(businesses, "known_for_user", task.requester_user_id, default=[])
            hit = next((b for b in known or [] if b.name.lower() == name.lower()), None)
            if hit:
                phone = hit.phone
            else:
                directory = self._opt("directory")
                found = await call_opt(directory, "search", name, spec.location_text or "", limit=3)
                for cand in found or []:
                    if cand.phone is None:
                        cand = await call_opt(directory, "details", cand.place_id) or cand
                    if cand.phone:
                        phone, name = cand.phone, cand.name
                        task.candidate = cand
                        break
        if not phone:
            await self._needs_info(
                task, ["business_phone"], "What's their number? You can share the contact too."
            )
            return False
        task.target = ContactTarget(
            kind=TargetKind.BUSINESS,
            name=name or "the business",
            phone=phone,
            business_id=spec.business_id,
        )
        await self._attach_business(task)
        return True

    async def _attach_business(
        self, task: Task, *, is_customer_care: bool = False
    ) -> Business | None:
        """Vendor memory: make sure the business exists and the target points at it."""
        businesses = repo(self.repos, "businesses")
        target = task.target
        if businesses is None or target is None or target.kind != TargetKind.BUSINESS:
            return None
        biz = await call_opt(businesses, "get_by_phone", target.phone)
        if biz is None:
            cand = task.candidate
            biz = Business(
                name=target.name,
                phone=target.phone,
                category=task.spec.category or (cand.category if cand else None),
                address=cand.address if cand else None,
                location=cand.location if cand else None,
                rating=cand.rating if cand else None,
                review_count=cand.review_count if cand else None,
                directory_provider=cand.provider if cand else None,
                directory_place_id=cand.place_id if cand else None,
                is_customer_care=is_customer_care,
                created_by_user_id=task.requester_user_id,
                created_at=self.clock.now(),
            )
            if cand is not None:
                hours = await call_opt(self._opt("directory"), "business_hours", cand.place_id)
                if hours:
                    biz.hours = hours
            biz = await call_opt(businesses, "upsert", biz) or biz
        task.target = target.model_copy(update={"business_id": biz.id})
        task.spec.business_id = biz.id
        return biz

    async def _verify(
        self, phone: str, *, name: str | None = None, company: str | None = None
    ) -> NumberCheck:
        key = phone_key(phone)
        if key in self._verified:
            return self._verified[key]
        verifier = self._opt("number_verifier")
        check = await call_opt(verifier, "verify", phone, claimed_name=name, company=company)
        if check is None:
            check = NumberCheck(
                phone=phone, verdict=NumberVerdict.UNKNOWN, checked_at=self.clock.now()
            )
        self._verified[key] = check
        return check

    async def _vet_number(self, task: Task) -> bool:
        """B16: never call a scam number; warn + ask before calling a suspicious one."""
        if not self.settings.verify_numbers or task.target is None:
            return True
        businesses = repo(self.repos, "businesses")
        biz = await call_opt(businesses, "get_by_phone", task.target.phone)
        if biz is not None and biz.verification == NumberVerdict.TRUSTED:
            return True
        check = await self._verify(
            task.target.phone, name=task.target.name, company=task.spec.company
        )
        if biz is not None and biz.verification != check.verdict:
            biz.verification = check.verdict
            await call_opt(businesses, "upsert", biz)
        if check.verdict == NumberVerdict.SCAM:
            await self._fail(
                task,
                f"⚠ The number for {task.target.name} is on a known-scam list, so I won't call it "
                "or share anything with it.",
            )
            return False
        if check.verdict == NumberVerdict.SUSPICIOUS and task.approved_terms is None:
            await self._ask_call_approval(
                task,
                f"⚠ I couldn't verify the number for {task.target.name}: "
                f"{'; '.join(check.signals[:3])}. Still call?",
            )
            return False
        return True

    async def _ask_call_approval(self, task: Task, text: str | None = None) -> None:
        if text is None:
            target = task.target.name if task.target else "them"
            text = f"Shall I call {target} now? ({task.spec.goal})"
            if task.type == TaskType.CUSTOMER_CARE and task.target:
                text = await self._care_summary(task)
        await self._transition(task, S.AWAITING_APPROVAL)
        await self.outbox.to_user(
            task.requester_user_id,
            text,
            buttons=[
                ReplyButton(id=approval_button_id(task.id, True), title="Go"),
                ReplyButton(id=approval_button_id(task.id, False), title="Cancel"),
            ],
            task_id=task.id,
        )

    async def _care_summary(self, task: Task) -> str:
        """US-30.2 pre-call summary: company, official number, ask, identifiers (masked)."""
        ids = (
            await call_opt(
                repo(self.repos, "identifiers"), "list_for_user", task.requester_user_id, default=[]
            )
            or []
        )
        shared = [i for i in ids if i.id in task.spec.approved_identifier_ids]
        lines = [
            f"I'll call {task.target.name} on their official number {task.target.phone}.",
            f"Ask: {task.spec.goal}",
            "I'll share: " + (", ".join(f"{i.label} {i.masked}" for i in shared) or "nothing"),
            "Never shared: OTPs, PINs, CVV, passwords.",
        ]
        return "\n".join(lines)

    async def _fail(self, task: Task, summary: str) -> None:
        task.result = TaskResult(success=False, summary=summary)
        await self._transition(task, S.FAILED)
        await self._report(task, task.result)
        await self._on_terminal(task)

    # ================================================================== queue / dialling
    async def _hours_for(self, task: Task) -> BusinessHours | None:
        if task.target is None or task.target.kind != TargetKind.BUSINESS:
            return None
        biz = await call_opt(repo(self.repos, "businesses"), "get_by_phone", task.target.phone)
        return biz.hours if biz else None

    async def _queue_dial(self, task: Task) -> None:
        """Dial now if the business can take the call, else SCHEDULED for the next
        good window (business hours, call window, lunch). Confirmation call-backs
        keep their ``approved_terms`` while queued."""
        now = self.clock.now()
        is_person = task.target is not None and task.target.kind == TargetKind.PERSON
        not_before = (
            task.next_attempt_at if task.status == S.SCHEDULED and task.next_attempt_at else now
        )
        when = next_call_time(
            max(now, not_before),
            self.settings,
            hours=await self._hours_for(task),
            is_person=is_person,
        )
        if self._abuse_limited(task, now):
            when = max(
                when, next_call_time(ist_day_bounds(now)[1], self.settings, is_person=is_person)
            )
            log.warning("ops: abuse rate-limit hit for user %s", task.requester_user_id)
        if when > now + timedelta(seconds=60):
            first_queue = task.status != S.SCHEDULED
            await self._transition(task, S.SCHEDULED, next_attempt_at=when)
            if first_queue and task.attempts == 0 and role_of(task) not in _SILENT_ROLES:
                who = task.target.name if task.target else "them"
                await self.outbox.to_user(
                    task.requester_user_id,
                    f"{who} can't take calls right now. I'll call at {format_ist(when, '%a %I:%M %p')}.",
                    task_id=task.id,
                )
            return
        target = S.CONFIRMATION_CALLBACK if task.approved_terms else S.CALLING
        task = await self._transition(task, target, next_attempt_at=None)
        await self._call(task)

    def _abuse_limited(self, task: Task, now: datetime) -> bool:
        """Ops-only abuse limit (off by default); never shown to users as a cap."""
        if not self.settings.abuse_rate_limit_enabled:
            return False
        key = (task.requester_user_id, to_ist(now).date().isoformat())
        return self._calls_today.get(key, 0) >= self.settings.abuse_max_calls_per_day

    async def _call(self, task: Task, *, inbound_leg: Any = None) -> None:
        is_confirm = task.status == S.CONFIRMATION_CALLBACK
        ctx = await self._context(task.requester_user_id)
        brief = await self.brain.build_call_brief(ctx, task)
        task.attempts += 1
        brief = await self._finalize_brief(task, brief)
        task = await self._save(task)
        key = (task.requester_user_id, to_ist(self.clock.now()).date().isoformat())
        self._calls_today[key] = self._calls_today.get(key, 0) + 1
        caller_id = None
        if task.target and task.target.kind == TargetKind.BUSINESS:  # sticky caller-ID (E.30)
            caller_id = await call_opt(
                self.calls, "choose_number", task.target.phone, self.caller_ids
            )
        result = await self._run_call(task, brief, inbound_leg=inbound_leg, from_number=caller_id)
        await self._process_result(task, result, is_confirm=is_confirm, caller_id=caller_id)

    async def _run_call(
        self,
        task: Task,
        brief: CallBrief,
        *,
        inbound_leg: Any = None,
        from_number: str | None = None,
        context: str | None = None,
    ) -> CallResult:
        ask = self._ask_user_cb(task)
        notify = self._notify_cb(task)
        async with self._global_calls:
            try:
                if inbound_leg is not None:
                    kw = {"context": context} if _accepts(self.runner.run_inbound, "context") else {}
                    coro = self.runner.run_inbound(brief, inbound_leg, ask, notify, **kw)
                elif from_number and _accepts(self.runner.run, "from_number"):
                    coro = self.runner.run(brief, ask, notify, from_number=from_number)
                else:
                    coro = self.runner.run(brief, ask, notify)
                job = asyncio.ensure_future(coro)
                self._calls[task.id] = job
                return await job
            except asyncio.CancelledError:
                if self._calls.get(task.id) is None:  # cancelled by engine.cancel()
                    raise TaskAborted(task.id) from None
                raise
            except Exception as e:  # noqa: BLE001 - runner must not raise, but be safe
                log.error("call runner raised for %s: %r", task.id, e)
                return CallResult(
                    task_id=task.id,
                    provider="unknown",
                    to_phone=brief.target.phone,
                    dial_status=DialStatus.FAILED,
                    outcome=CallOutcome.FAILED,
                    error=type(e).__name__,
                    started_at=self.clock.now(),
                    ended_at=self.clock.now(),
                )
            finally:
                self._calls.pop(task.id, None)

    async def _finalize_brief(self, task: Task, brief: CallBrief) -> CallBrief:
        """The engine is the authority for commitment and targeting."""
        updates: dict[str, Any] = {
            "delegation": task.delegation,  # explicit user delegation only (never inferred)
            "approved_terms": task.approved_terms,  # set only after the user approved
            "attempt": task.attempts,
        }
        if task.target is not None:
            updates["target"] = task.target  # the verified number, nothing else
        if role_of(task) == ROLE_CLOSE_LOOP:  # need already met: never commit anything
            updates["delegation"] = Delegation()
            updates["approved_terms"] = None
        if task.type == TaskType.WELLBEING_CHECKIN:
            updates["max_duration_s"] = min(
                brief.max_duration_s, self.settings.checkin_max_duration_s
            )
        if not brief.user_phone:
            user = await call_opt(repo(self.repos, "users"), "get", task.requester_user_id)
            if user:
                updates["user_phone"] = user.phone
        if task.parent_task_id and role_of(task) == ROLE_FANOUT:
            siblings = await self.tasks.list_children(task.parent_task_id)
            if not brief.competing_quotes:
                updates["competing_quotes"] = [
                    q for s in siblings if s.id != task.id and s.result for q in s.result.quotes
                ]
            parent = await self.tasks.get(task.parent_task_id)
            if parent and parent.result and parent.result.hotel_offers and brief.api_offer is None:
                updates["api_offer"] = _offer_for(parent.result.hotel_offers, task.target)
        return brief.model_copy(update=updates)

    def _ask_user_cb(self, task: Task) -> Callable[[MidCallQuestion], Awaitable[UserAnswer | None]]:
        async def ask_user(question: MidCallQuestion) -> UserAnswer | None:
            fresh = await self.tasks.get(task.id) or task
            prev = fresh.status
            if prev in (S.CALLING, S.CONFIRMATION_CALLBACK):
                fresh = await self._transition(fresh, S.AWAITING_USER)
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[question.id] = (fut, task.id, task.requester_user_id, question)
            await call_opt(self.tasks, "add_question", question)
            who = task.target.name if task.target else "the call"
            buttons = [
                ReplyButton(id=question_button_id(question.id, i), title=opt[:20])
                for i, opt in enumerate(question.options[:3])
            ]
            await self.outbox.to_user(
                task.requester_user_id,
                f"{who}: {question.text}",
                buttons=buttons,
                task_id=task.id,
                question_id=question.id,
                template_key="question",
            )
            await self.bus.publish(
                MidCallQuestionAsked(question=question, user_id=task.requester_user_id)
            )
            answer: UserAnswer | None = None
            try:
                answer = await asyncio.wait_for(fut, timeout=question.timeout_s)
            except TimeoutError:
                answer = None
            finally:
                self._pending.pop(question.id, None)
                current = await self.tasks.get(task.id)
                if current and current.status == S.AWAITING_USER:
                    await self._transition(current, prev)
            if answer is not None:
                await call_opt(self.tasks, "answer_question", answer)
                await self.bus.publish(UserAnswerReceived(answer=answer))
            return answer

        return ask_user

    def _notify_cb(self, task: Task) -> Callable[[str], Awaitable[None]]:
        sent = 0

        async def notify_user(text: str) -> None:
            nonlocal sent
            if sent >= self.policy.max_progress_updates_per_call or role_of(task) in _SILENT_ROLES:
                return
            sent += 1
            who = task.target.name if task.target else ""
            await self.outbox.to_user(
                task.requester_user_id, f"{who}: {text}".strip(": "), task_id=task.id
            )

        return notify_user

    # ================================================================== results
    async def _process_result(
        self, task: Task, result: CallResult, *, is_confirm: bool, caller_id: str | None = None
    ) -> None:
        # save_call persists the call, quotes, questions, cost ledger and call memory
        await self.tasks.save_call(result)
        task.cost_inr_est += result.cost_inr_est
        task.last_outcome = result.outcome
        if task.target and task.target.kind == TargetKind.BUSINESS:
            # call memory (E.30): make sure the caller-ID we chose is on record
            await call_opt(
                self.calls,
                "record_outbound",
                task_id=task.id,
                user_id=task.requester_user_id,
                business_phone=result.to_phone or task.target.phone,
                friday_number=getattr(result, "from_number", None) or caller_id,
                call_id=result.call_id,
                business_id=task.target.business_id,
                outcome=result.outcome,
                at=result.started_at,
            )
        await self._handle_outcome(task, result, is_confirm=is_confirm)

    async def _handle_outcome(self, task: Task, result: CallResult, *, is_confirm: bool) -> None:
        o = result.outcome
        role = role_of(task)
        if o == CallOutcome.CANCELLED:
            raise TaskAborted(task.id)
        if o == CallOutcome.PENDING_APPROVAL or (o == CallOutcome.USER_TIMEOUT and result.quotes):
            summary = await self._summarize(task, result)
            await self._vendor_memory(task, result, summary, committed=False)
            if role in (ROLE_FANOUT, ROLE_CLOSE_LOOP):
                task.result = summary
                await self._transition(task, S.COMPLETED)
                if role == ROLE_CLOSE_LOOP:
                    await self._maybe_better_offer(task, summary)
                await self._on_terminal(task)
                return
            await self._ask_offer_approval(task, summary, result)
            return
        if o in (CallOutcome.SUCCESS, CallOutcome.PARTIAL, CallOutcome.TRANSFERRED):
            summary = await self._summarize(task, result)
            committed = (
                o == CallOutcome.SUCCESS
                and (is_confirm or task.delegation.granted)
                and task.type in BOOKING_TYPES | {TaskType.RECURRING_BOOKING}
            )
            await self._vendor_memory(task, result, summary, committed=committed)
            task.result = summary
            await self._transition(task, S.COMPLETED)
            await self._after_success(task, result, summary)
            await self._on_terminal(task)
            return
        if o.is_retryable and task.attempts < task.max_attempts and role != ROLE_CLOSE_LOOP:
            await self._vendor_memory(task, result, None, committed=False)
            await self._schedule_retry(task, result)
            return
        summary = await self._summarize(task, result)
        await self._vendor_memory(task, result, summary, committed=False)
        task.result = summary
        await self._transition(task, S.FAILED)
        if task.type == TaskType.WELLBEING_CHECKIN and o.is_retryable:
            await self._raise_alert(
                task, f"I couldn't reach {task.target.name} after {task.attempts} tries."
            )
        if role not in _SILENT_ROLES:
            await self._report(task, summary, final_options=o.is_retryable)
        await self._on_terminal(task)

    async def _summarize(self, task: Task, result: CallResult) -> TaskResult:
        try:
            return await self.brain.summarize_call(
                await self._context(task.requester_user_id), task, result
            )
        except Exception as e:  # noqa: BLE001
            log.error("summarize_call failed for %s: %r", task.id, e)
            return TaskResult(
                success=result.outcome == CallOutcome.SUCCESS,
                summary=f"Call to {task.target.name if task.target else 'them'} ended: "
                f"{result.outcome.value.replace('_', ' ')}.",
                quotes=result.quotes,
                care=result.care,
            )

    async def _schedule_retry(self, task: Task, result: CallResult) -> None:
        """BRIEF E.36: retry with the policy delays, alternate numbers / WhatsApp
        request in between, tell the user once."""
        now = self.clock.now()
        callback_at = _parse_dt(result.collected.get("callback_at"))
        when = retry_at(result.outcome, task.attempts, now, self.policy, callback_at=callback_at)
        is_person = task.target is not None and task.target.kind == TargetKind.PERSON
        when = next_call_time(
            when, self.settings, hours=await self._hours_for(task), is_person=is_person
        )
        await self._try_alternates(task, result)
        first_retry = task.attempts == 1
        await self._transition(task, S.SCHEDULED, next_attempt_at=when)
        role = role_of(task)
        if role in _SILENT_ROLES:
            return
        who = task.target.name if task.target else "They"
        at = format_ist(when, "%I:%M %p").lstrip("0")
        if result.outcome == CallOutcome.CALLBACK_LATER:
            await self.outbox.to_user(
                task.requester_user_id,
                f"{who} asked me to call later. I'll call at {at}.",
                task_id=task.id,
            )
        elif result.outcome == CallOutcome.HOLD_TIMEOUT:
            await self.outbox.to_user(
                task.requester_user_id,
                f"Gave up after a long hold with {who}. I'll try again at {format_ist(when)}.",
                task_id=task.id,
            )
        elif first_retry:  # once, not on every attempt
            await self.outbox.to_user(
                task.requester_user_id,
                f"{who} isn't picking up. I'll keep trying, next attempt {at}.",
                task_id=task.id,
            )

    async def _try_alternates(self, task: Task, result: CallResult) -> None:
        if task.target is None or task.target.kind != TargetKind.BUSINESS:
            return
        if result.outcome not in (CallOutcome.NO_ANSWER, CallOutcome.BUSY, CallOutcome.VOICEMAIL):
            return
        biz = await call_opt(repo(self.repos, "businesses"), "get_by_phone", task.target.phone)
        if biz is None:
            biz = await call_opt(
                repo(self.repos, "businesses"), "get", task.target.business_id or ""
            )
        if biz is None:
            return
        alternates = [p for p in _alt_numbers(biz) if phone_key(p) != phone_key(task.target.phone)]
        if self.policy.try_alt_numbers and alternates:
            alt = alternates[0]
            check = await self._verify(alt, name=biz.name)
            # listed on the business's own record: only a known scam disqualifies it
            # (a "different number" listing signal is expected for an alternate)
            if check.verdict != NumberVerdict.SCAM:
                task.target = task.target.model_copy(update={"phone": alt})
                await self._audit(task, "call.alternate_number", phone=mask_phone(alt))
        if self.policy.whatsapp_request_on_no_answer and biz.whatsapp_phone and task.attempts == 1:
            user = await call_opt(repo(self.repos, "users"), "get", task.requester_user_id)
            await self.outbox.to_business(
                biz.whatsapp_phone,
                TemplateRef(
                    key=self.policy.business_request_template,
                    params=[task.spec.on_behalf_of or "my user", task.spec.goal],
                ),
                business_id=biz.id,
                task_id=task.id,
                channel=Channel.WHATSAPP,
            )
            _ = user

    async def _ask_offer_approval(
        self, task: Task, summary: TaskResult, result: CallResult
    ) -> None:
        """Founder rule: offer -> AWAITING_APPROVAL -> user picks -> confirmation call-back."""
        q = summary.needs_approval
        if q is None:
            options: list[str] = []
            for quote in summary.quotes or result.quotes:
                for slot in quote.available_slots:
                    options.append(f"{slot} {quote.price_text}".strip()[:20])
            options = options[:2]
            q = MidCallQuestion(
                task_id=task.id,
                text="Book which?" if options else "Shall I confirm it?",
                purpose=QuestionPurpose.APPROVE_BOOKING,
                options=[*options, "None"] if options else ["Yes, book it", "No"],
                timeout_s=self.policy.offer_question_timeout_s,
                asked_at=self.clock.now(),
            )
        else:
            q = q.model_copy(update={"task_id": task.id, "options": _cap_options(q.options)})
        summary.needs_approval = q
        task.result = summary
        await self._transition(task, S.AWAITING_APPROVAL)
        self._offer_questions[q.id] = task.id
        await call_opt(self.tasks, "add_question", q)
        await self.outbox.to_user(
            task.requester_user_id,
            f"{summary.summary}\n{q.text}".strip(),
            buttons=[
                ReplyButton(id=question_button_id(q.id, i), title=o[:20])
                for i, o in enumerate(q.options)
            ],
            task_id=task.id,
            question_id=q.id,
            template_key="question",
        )

    async def _vendor_memory(
        self, task: Task, result: CallResult, summary: TaskResult | None, *, committed: bool
    ) -> None:
        """B20: every call, quote and booking goes to vendor memory."""
        businesses = repo(self.repos, "businesses")
        target = task.target
        if businesses is None or target is None or target.kind != TargetKind.BUSINESS:
            return
        biz = await call_opt(businesses, "get_by_phone", target.phone)
        if biz is None and target.business_id:
            biz = await call_opt(businesses, "get", target.business_id)
        if biz is None:
            return
        now = self.clock.now()
        if result.dial_status == DialStatus.ANSWERED:
            biz.last_called_at = now
            await call_opt(businesses, "upsert", biz)

        def interaction(kind: InteractionKind, **kw: Any) -> VendorInteraction:
            return VendorInteraction(
                user_id=task.requester_user_id,
                business_id=biz.id,
                kind=kind,
                task_id=task.id,
                call_id=result.call_id,
                at=now,
                **kw,
            )

        items = [interaction(InteractionKind.CALLED, outcome=result.outcome.value)]
        for q in result.quotes:
            items.append(
                interaction(
                    InteractionKind.QUOTED, amount_inr=q.amount_inr, note=q.price_text[:200]
                )
            )
        if committed:
            amount = next((q.amount_inr for q in result.quotes if q.amount_inr), None)
            items.append(
                interaction(InteractionKind.BOOKED, amount_inr=amount, note=task.approved_terms)
            )
        if summary is not None:
            items.extend(summary.interactions)
        for it in items:
            await call_opt(businesses, "add_interaction", it)
        if summary is not None:
            for fact in summary.facts:
                await call_opt(repo(self.repos, "facts"), "upsert", fact)

    async def _after_success(self, task: Task, result: CallResult, summary: TaskResult) -> None:
        role = role_of(task)
        if role not in _SILENT_ROLES:
            await self._report(task, summary, recording_url=result.recording_url)
        # end-of-call business touch (BRIEF #8)
        if (
            summary.business_touch
            and result.outcome == CallOutcome.SUCCESS
            and task.target
            and task.target.kind == TargetKind.BUSINESS
            and role != ROLE_CLOSE_LOOP
        ):
            await self.outbox.to_business(
                task.target.phone,
                summary.business_touch,
                business_id=task.target.business_id,
                task_id=task.id,
            )
        # beneficiary confirmation (US-22.3) - only with their opt-in, minimal content
        if (
            task.beneficiary.person_id
            and result.outcome == CallOutcome.SUCCESS
            and role not in _SILENT_ROLES
        ):
            person = await call_opt(repo(self.repos, "people"), "get", task.beneficiary.person_id)
            if person and person.can_be_contacted and task.type in BOOKING_TYPES:
                when = summary.details.get("time") or (
                    format_ist(summary.appointment_at) if summary.appointment_at else ""
                )
                await self.outbox.to_person(
                    person,
                    f"Booking confirmed: {task.target.name if task.target else ''} {when}".strip(),
                    task_id=task.id,
                )
        if summary.alert:
            await self._raise_alert(task, summary.alert)
        # C25: auto follow-up at the promised date
        care = summary.care or result.care
        if (
            care
            and care.promised_date
            and not care.resolved
            and task.type == TaskType.CUSTOMER_CARE
        ):
            when = at_ist(care.promised_date, 10) + timedelta(
                hours=self.settings.care_followup_grace_h
            )
            await self._timed_child(
                task,
                ROLE_CARE_FOLLOWUP,
                TaskType.CUSTOMER_CARE,
                when,
                goal=f"Follow up on {care.company or task.target.name} ticket {care.ticket_number or ''}".strip(),
                reference=care.ticket_number,
                care_request=task.spec.care_request,
            )
        # D28: day-before reconfirm for stays
        booking = summary.hotel_booking or (
            _direct_booking(task, summary)
            if task.type == TaskType.HOTEL_BOOKING and task.approved_terms
            else None
        )
        if booking is not None:
            summary.hotel_booking = booking
            await self._save(task)
            await call_opt(
                self.tasks, "save_hotel_booking", booking, user_id=task.requester_user_id
            )
            when = at_ist(
                booking.check_in - timedelta(days=1), self.settings.hotel_reconfirm_hour_ist
            )
            await self._timed_child(
                task,
                ROLE_RECONFIRM,
                TaskType.RECONFIRM,
                when,
                goal=f"Reconfirm stay at {booking.property.name} {booking.check_in}–{booking.check_out}",
                reference=booking.confirmation_ref,
                stay=task.spec.stay,
            )
        # E.37: a late call-back offering something materially better
        if role in (ROLE_CLOSE_LOOP, ROLE_CALLBACK):
            await self._maybe_better_offer(task, summary)

    async def _timed_child(
        self,
        task: Task,
        role: str,
        ttype: TaskType,
        when: datetime,
        *,
        goal: str,
        **spec_updates: Any,
    ) -> Task:
        child = Task(
            requester_user_id=task.requester_user_id,
            beneficiary=task.beneficiary,
            place_id=task.place_id,
            type=ttype,
            spec=with_role(
                task.spec,
                role,
                type=ttype,
                goal=goal,
                fan_out=None,
                recurrence=None,
                delegation=Delegation(),
                **spec_updates,
            ),
            target=task.target,
            parent_task_id=task.id,
            max_attempts=self.policy.max_attempts,
            created_at=self.clock.now(),
        )
        child = await self.tasks.add(child)
        now = self.clock.now()
        await self._transition(child, S.SCHEDULED, next_attempt_at=max(when, now))
        return child

    async def _raise_alert(self, task: Task, text: str) -> None:
        await self.bus.publish(
            WellbeingAlertRaised(
                task_id=task.id,
                user_id=task.requester_user_id,
                person_id=task.beneficiary.person_id,
                text=text,
                at=self.clock.now(),
            )
        )

    async def _report(
        self,
        task: Task,
        summary: TaskResult,
        *,
        recording_url: str | None = None,
        final_options: bool = False,
    ) -> None:
        lines = [summary.summary]
        lines += [f"{k}: {v}" for k, v in summary.details.items() if k != "booking_child_id"]
        lines += summary.next_steps
        buttons: list[ReplyButton] = []
        qid = None
        if final_options and task.target is not None:
            q = MidCallQuestion(
                task_id=task.id,
                text="Try again?",
                purpose=QuestionPurpose.CHOOSE_OPTION,
                options=["Later today", "Tomorrow", "Another business"],
                asked_at=self.clock.now(),
            )
            self._retry_questions[q.id] = task.id
            await call_opt(self.tasks, "add_question", q)
            buttons = [
                ReplyButton(id=question_button_id(q.id, i), title=o)
                for i, o in enumerate(q.options)
            ]
            qid = q.id
        await self.outbox.to_user(
            task.requester_user_id,
            "\n".join(x for x in lines if x),
            buttons=buttons,
            task_id=task.id,
            question_id=qid,
            media_url=recording_url,
        )

    async def _handle_retry_choice(self, task: Task, answer: UserAnswer) -> None:
        """After the final failed attempt: later today / tomorrow / another business."""
        self._retry_questions.pop(answer.question_id, None)
        idx = answer.option_index if answer.option_index is not None else 0
        now = self.clock.now()
        if idx == 2:  # another business -> discovery for the same need
            spec = task.spec.model_copy(
                update={
                    "type": TaskType.DISCOVERY if task.type in BOOKING_TYPES else task.type,
                    "business_name": None,
                    "business_phone": None,
                    "business_id": None,
                    "discovery_query": task.spec.discovery_query
                    or task.spec.category
                    or task.spec.goal,
                }
            )
            await self.create_task(
                task.requester_user_id,
                spec,
                beneficiary_person_id=task.beneficiary.person_id,
                place_id=task.place_id,
            )
            return
        when = (
            now + timedelta(hours=2)
            if idx == 0
            else at_ist(to_ist(now).date() + timedelta(days=1), 10)
        )
        retry = Task(
            requester_user_id=task.requester_user_id,
            beneficiary=task.beneficiary,
            place_id=task.place_id,
            type=task.type,
            spec=with_role(task.spec, ROLE_RETRY),
            target=task.target,
            delegation=task.delegation,
            max_attempts=self.policy.max_attempts,
            created_at=now,
        )
        retry = await self.tasks.add(retry)
        is_person = task.target is not None and task.target.kind == TargetKind.PERSON
        when = next_call_time(
            when, self.settings, hours=await self._hours_for(task), is_person=is_person
        )
        await self._transition(retry, S.SCHEDULED, next_attempt_at=when)
        await self.outbox.to_user(
            task.requester_user_id, f"Okay, I'll try again at {format_ist(when)}.", task_id=retry.id
        )

    # ================================================================== terminal hooks
    async def _on_terminal(self, task: Task) -> None:
        """E.37: cancel all pending retries / call-backs for the resolved need, and
        let a fan-out / booking parent react."""
        for child in await self.tasks.list_children(task.id):
            if not child.status.is_terminal and role_of(child) in _NEED_ROLES | {ROLE_CALLBACK}:
                await self.cancel(child.id, by_user=False)
        if task.parent_task_id:
            await self._on_child_settled(task)

    async def _on_child_settled(self, child: Task) -> None:
        parent = await self.tasks.get(child.parent_task_id or "")
        if parent is None or parent.status.is_terminal:
            return
        role = role_of(child)
        if role == ROLE_BOOKING or (
            parent.result and parent.result.details.get("booking_child_id") == child.id
        ):
            parent.result = parent.result or TaskResult(success=False, summary="")
            parent.result.success = child.status == S.COMPLETED and bool(
                child.result and child.result.success
            )
            if child.result:
                parent.result.summary = child.result.summary
            new = {S.COMPLETED: S.COMPLETED, S.CANCELLED: S.CANCELLED}.get(child.status, S.FAILED)
            await self._transition(parent, new, force=new == S.CANCELLED)
            await self._on_terminal(parent)
            return
        if role == ROLE_FANOUT:
            await self._pump_children(parent)

    # ================================================================== discovery / fan-out
    async def _discover(self, task: Task) -> None:
        spec = task.spec
        near = None
        location_text = spec.location_text or ""
        if task.place_id:
            place = await call_opt(repo(self.repos, "places"), "get", task.place_id)
            if place:
                near = place.location
                location_text = (
                    location_text
                    or place.formatted_address
                    or place.address_text
                    or place.city
                    or ""
                )
        geocoder = self._opt("geocoder")
        if near is None and location_text:
            geo = await call_opt(geocoder, "geocode", location_text)
            near = geo.location if geo else None
        candidates: list[BusinessCandidate] = []
        if task.type == TaskType.HOTEL_BOOKING and spec.stay:
            candidates = await self._hotel_candidates(task, near)
        else:
            query = (
                spec.discovery_query
                or spec.category
                or spec.item
                or spec.business_name
                or spec.goal
            )
            directory = self._opt("directory")
            found = (
                await call_opt(
                    directory,
                    "search",
                    query,
                    location_text,
                    near=near,
                    limit=self.settings.discovery_max_candidates,
                    default=[],
                )
                or []
            )
            for cand in found:
                if cand.phone is None or not cand.review_snippets:
                    cand = await call_opt(directory, "details", cand.place_id) or cand
                candidates.append(cand)
        candidates = await self._filter_candidates(task, candidates)
        if not candidates:
            await self._fail(task, "I couldn't find anyone suitable nearby to call.")
            return
        policy = await self._fan_out_policy(task)
        n = min(spec.shortlist_size or self.settings.discovery_shortlist_size, policy.max_targets)
        if task.type == TaskType.HOTEL_BOOKING:
            n = min(n, self.settings.hotel_shortlist_size)
        ctx = await self._context(task.requester_user_id)
        try:
            shortlist = await self.brain.shortlist(ctx, spec, candidates, n)
        except Exception as e:  # noqa: BLE001 - fall back to rating order
            log.error("shortlist failed: %r", e)
            ranked = sorted(candidates, key=lambda c: (-(c.rating or 0), -c.review_count))[:n]
            shortlist = [
                ShortlistItem(
                    candidate=c, rank=i + 1, reason=f"{c.rating or '?'}★ ({c.review_count})"
                )
                for i, c in enumerate(ranked)
            ]
        shortlist = [s for s in shortlist if s.candidate.phone][:n]
        if not shortlist:
            await self._fail(task, "I couldn't find anyone with a working number to call.")
            return
        task.shortlist = shortlist
        task = await self._save(task)
        autonomy = ctx.autonomy
        skip_approval = (
            task.type == TaskType.STOCK_HUNT or level_for(autonomy, category_for(task.type)) >= 3
        )
        if skip_approval:
            names = ", ".join(s.candidate.name for s in shortlist)
            await self.outbox.to_user(task.requester_user_id, f"Calling {names}.", task_id=task.id)
            await self._start_children(task)
            return
        lines = [f"{s.rank}. {s.candidate.name}: {s.reason}" for s in shortlist]
        await self._transition(task, S.AWAITING_APPROVAL)
        await self.outbox.to_user(
            task.requester_user_id,
            "Here's my shortlist:\n" + "\n".join(lines),
            buttons=[
                ReplyButton(
                    id=approval_button_id(task.id, True), title=f"Call all {len(shortlist)}"
                ),
                ReplyButton(id=approval_button_id(task.id, False), title="Cancel"),
            ],
            task_id=task.id,
        )

    async def _hotel_candidates(self, task: Task, near: Any) -> list[BusinessCandidate]:
        stay = task.spec.stay
        if stay.near is None and near is not None:
            stay = stay.model_copy(update={"near": near})
            task.spec.stay = stay
        hotels = self._opt("hotels")
        offers: list[HotelOffer] = await call_opt(hotels, "search", stay, default=[]) or []
        task.result = TaskResult(success=False, summary="", hotel_offers=offers)
        await self._save(task)
        out: dict[str, BusinessCandidate] = {}
        for o in offers:
            p = o.property
            if p.phone and phone_key(p.phone) not in out:
                out[phone_key(p.phone)] = _hotel_candidate(p, getattr(hotels, "name", "hotels"))
        directory = self._opt("directory")
        query = " ".join(stay.property_types) or "homestay hotel"
        found = (
            await call_opt(directory, "search", query, stay.destination, near=stay.near, default=[])
            or []
        )
        for cand in found:  # offline homestays/guesthouses with a phone
            if cand.phone is None:
                cand = await call_opt(directory, "details", cand.place_id) or cand
            if cand.phone and phone_key(cand.phone) not in out:
                out[phone_key(cand.phone)] = cand
        return list(out.values())

    async def _filter_candidates(
        self, task: Task, cands: list[BusinessCandidate]
    ) -> list[BusinessCandidate]:
        never = set()
        history = (
            await call_opt(
                repo(self.repos, "businesses"), "interactions", task.requester_user_id, default=[]
            )
            or []
        )
        for it in history:
            if (it.rating is not None and it.rating <= 1) or (
                it.note and "never" in it.note.lower()
            ):
                never.add(it.business_id)
        known = {}
        for b in (
            await call_opt(
                repo(self.repos, "businesses"), "known_for_user", task.requester_user_id, default=[]
            )
            or []
        ):
            known[phone_key(b.phone)] = b.id
        out = []
        min_rating = self.settings.discovery_min_rating
        for c in cands:
            if not c.phone or is_toll_free(c.phone):
                continue
            if c.rating is not None and c.review_count >= 5 and c.rating < min_rating:
                continue
            if known.get(phone_key(c.phone)) in never:
                continue
            check = await self._verify(c.phone, name=c.name)
            if check.verdict == NumberVerdict.SCAM:
                continue
            out.append(c)
        return out

    async def _fan_out_policy(self, task: Task) -> FanOutPolicy:
        policy = task.spec.fan_out
        if policy is None:
            try:
                policy = self.brain.template_for(task.type).fan_out
            except Exception:  # noqa: BLE001
                policy = None
        policy = policy or FanOutPolicy()
        if task.type == TaskType.STOCK_HUNT and policy.strategy == FanOutStrategy.SINGLE:
            policy = policy.model_copy(update={"strategy": FanOutStrategy.FIRST_MATCH})
        if policy.strategy == FanOutStrategy.SINGLE:
            policy = policy.model_copy(update={"strategy": FanOutStrategy.SEQUENTIAL})
        return policy

    async def _start_children(self, parent: Task) -> None:
        policy = await self._fan_out_policy(parent)
        first_match = policy.strategy == FanOutStrategy.FIRST_MATCH
        ctype = CHILD_TYPE.get(parent.type, parent.type)
        for item in parent.shortlist[: policy.max_targets]:
            cand = item.candidate
            child = Task(
                requester_user_id=parent.requester_user_id,
                beneficiary=parent.beneficiary,
                place_id=parent.place_id,
                type=ctype,
                spec=with_role(
                    parent.spec,
                    ROLE_FANOUT,
                    type=ctype,
                    business_name=cand.name,
                    business_phone=cand.phone,
                    business_id=None,
                    fan_out=None,
                    recurrence=None,
                    # compare calls never commit; a stock hunt may (e.g. "order if < ₹300")
                    delegation=parent.delegation if first_match else Delegation(),
                ),
                target=ContactTarget(kind=TargetKind.BUSINESS, name=cand.name, phone=cand.phone),
                candidate=cand,
                parent_task_id=parent.id,
                delegation=parent.delegation if first_match else Delegation(),
                max_attempts=1 if first_match else self.policy.max_attempts,
                created_at=self.clock.now(),
            )
            await self.tasks.add(child)
        await self._transition(parent, S.WAITING_CHILDREN)
        await self._pump_children(parent)

    def _lock(self, parent_id: str) -> asyncio.Lock:
        return self._parent_locks.setdefault(parent_id, asyncio.Lock())

    async def _pump_children(self, parent: Task) -> None:
        async with self._lock(parent.id):
            parent = await self.tasks.get(parent.id)
            if parent is None or parent.status != S.WAITING_CHILDREN:
                return
            if parent.result and parent.result.details.get("booking_child_id"):
                return
            policy = await self._fan_out_policy(parent)
            children = [
                c for c in await self.tasks.list_children(parent.id) if role_of(c) == ROLE_FANOUT
            ]
            if policy.strategy == FanOutStrategy.FIRST_MATCH:
                if any(_is_match(c) for c in children):
                    for c in children:
                        if not c.status.is_terminal:
                            await self.cancel(c.id, by_user=False)
                    await self._aggregate(parent)
                    return
            # SCHEDULED (retrying) children don't hold a slot: move on (E.36)
            active = [
                c
                for c in children
                if not c.status.is_terminal and c.status not in (S.CREATED, S.SCHEDULED)
            ]
            created = [c for c in children if c.status == S.CREATED]
            limit = (
                1
                if policy.strategy == FanOutStrategy.SEQUENTIAL
                else max(
                    1,
                    min(
                        policy.concurrency,
                        self.settings.fanout_default_concurrency or policy.concurrency,
                    ),
                )
            )
            for c in created[: max(0, limit - len(active))]:
                c = await self._transition(c, S.PLANNING)
                self._spawn(c.id, self._run(c.id))
                active.append(c)
            if active or created:
                return
            retrying = [c for c in children if c.status == S.SCHEDULED]
            have_offer = any(_has_offer(c) for c in children)
            if retrying and not have_offer:
                return  # nothing yet: wait for the retries
            for c in retrying:  # resolved enough: cancel pending retries (E.37)
                await self.cancel(c.id, by_user=False)
            await self._aggregate(parent)

    async def _aggregate(self, parent: Task) -> None:
        children = [
            c for c in await self.tasks.list_children(parent.id) if role_of(c) == ROLE_FANOUT
        ]
        policy = await self._fan_out_policy(parent)
        n = len([c for c in children if c.attempts > 0])
        if policy.strategy == FanOutStrategy.FIRST_MATCH:
            match = next((c for c in children if _is_match(c)), None)
            if match:
                res = match.result.model_copy(deep=True)
                res.summary = f"{res.summary} (Checked {n} place{'s' if n != 1 else ''}.)"
                parent.result = res
                await self._transition(parent, S.COMPLETED)
                await self._report(parent, res)
            else:
                parent.result = TaskResult(
                    success=False, summary=f"None of the {n} places I called had it."
                )
                await self._transition(parent, S.FAILED)
                await self._report(parent, parent.result)
            await self._on_terminal(parent)
            return
        quotes: list[Quote] = []
        for c in children:
            for q in c.result.quotes if c.result else []:
                quotes.append(q.model_copy(update={"task_id": q.task_id or c.id}))
        if not quotes:
            outcomes = ", ".join(
                f"{c.target.name}: {(c.last_outcome or CallOutcome.CANCELLED).value.replace('_', ' ')}"
                for c in children
                if c.target
            )
            parent.result = TaskResult(
                success=False, summary=f"I couldn't get any offers. {outcomes}"
            )
            await self._transition(parent, S.FAILED)
            await self._report(parent, parent.result)
            await self._on_terminal(parent)
            return
        ctx = await self._context(parent.requester_user_id)
        comparison = await self.brain.compare_quotes(ctx, parent, quotes)
        ranked = comparison.ranked_quotes or quotes
        options = [f"Book {q.business_name}"[:20] for q in ranked[:3]]
        if len(options) < 3:
            options.append("None")
        q = MidCallQuestion(
            task_id=parent.id,
            text=comparison.summary,
            purpose=QuestionPurpose.CHOOSE_OPTION,
            options=options,
            timeout_s=self.policy.offer_question_timeout_s,
            asked_at=self.clock.now(),
        )
        comparison = comparison.model_copy(update={"ranked_quotes": ranked})
        parent.result = TaskResult(
            success=False,
            summary=comparison.summary,
            quotes=ranked,
            comparison=comparison,
            needs_approval=q,
            hotel_offers=parent.result.hotel_offers if parent.result else [],
        )
        await self._transition(parent, S.AWAITING_CHOICE)
        self._offer_questions[q.id] = parent.id
        await call_opt(self.tasks, "add_question", q)
        if parent.delegation.granted and comparison.recommended_index is not None:
            await self.outbox.to_user(
                parent.requester_user_id,
                f"{comparison.summary}\nAs you asked, I'm booking the best option within your limits.",
                task_id=parent.id,
            )
            await self.choose(parent.id, comparison.recommended_index)
            return
        await self.outbox.to_user(
            parent.requester_user_id,
            comparison.summary,
            buttons=[
                ReplyButton(id=question_button_id(q.id, i), title=o) for i, o in enumerate(options)
            ],
            task_id=parent.id,
            question_id=q.id,
            template_key="question",
        )

    # ================================================================== recurring
    async def _plan_recurring(self, task: Task) -> None:
        rule = task.recurrence
        if rule.delegation.granted:
            task.delegation = rule.delegation  # authority for every instance (founder rule)
        if task.type == TaskType.WELLBEING_CHECKIN and not await self._checkin_target(task):
            return
        nxt = next_run(rule, self.clock.now(), anchor=to_ist(task.created_at).date())
        if nxt is None:
            task.result = TaskResult(success=True, summary="The series has ended.")
            await self._transition(task, S.COMPLETED)
            return
        run_at, occurrence = nxt
        task.recurrence = rule.model_copy(update={"next_run_at": run_at})
        await self._transition(task, S.SCHEDULED, next_attempt_at=run_at)
        await self.outbox.to_user(
            task.requester_user_id,
            f"Series set up. Next: {format_ist(occurrence)} (I'll call on {format_ist(run_at)}).",
            task_id=task.id,
        )

    async def _run_recurring(self, parent: Task) -> None:
        rule = parent.recurrence
        now = self.clock.now()
        due = rule.next_run_at or parent.next_attempt_at or now
        if due > now:
            return
        occurrence = due + timedelta(days=rule.lead_days)
        itype = (
            TaskType.WELLBEING_CHECKIN
            if parent.type == TaskType.WELLBEING_CHECKIN
            else TaskType.BOOKING
        )
        instance = Task(
            requester_user_id=parent.requester_user_id,
            beneficiary=parent.beneficiary,
            place_id=parent.place_id,
            type=itype,
            spec=with_role(
                parent.spec,
                ROLE_INSTANCE,
                type=itype,
                recurrence=None,
                fan_out=None,
                window_start=occurrence,
                window_end=occurrence + timedelta(hours=2),
                when_text=format_ist(occurrence),
                delegation=rule.delegation,
            ),
            target=parent.target if itype == TaskType.WELLBEING_CHECKIN else None,
            parent_task_id=parent.id,
            delegation=rule.delegation,
            max_attempts=self.policy.max_attempts,
            created_at=now,
        )
        instance = await self.tasks.add(instance)
        nxt = next_run(rule, due, anchor=to_ist(parent.created_at).date())
        if nxt is None:
            parent.recurrence = rule.model_copy(update={"next_run_at": None})
            parent.result = TaskResult(success=True, summary="The series has ended.")
            await self._transition(parent, S.COMPLETED, next_attempt_at=None)
        else:
            parent.recurrence = rule.model_copy(update={"next_run_at": nxt[0]})
            parent.next_attempt_at = nxt[0]
            await self._save(parent)
        self._spawn(instance.id, self._run(instance.id))

    # ================================================================== E.30-37 inbound
    # Matching lives in call memory (Backend A: ``repos.calls.match`` -> CallbackMatch with
    # status matched|ambiguous|unmatched, task_id, candidates[CallMemory], from_phone,
    # friday_number). The API's CallbackService records the contact and calls the
    # ``handle_*`` methods below; ``on_inbound_call`` etc. are thin convenience wrappers.

    async def _match_tasks(self, match: Any) -> tuple[list[Task], bool]:
        """Matched tasks (newest first) and whether the caller is verified: caller ID ==
        the business number we called for those tasks and not flagged (E.34)."""
        status = str(getattr(match, "status", "unmatched"))
        if status.endswith("unmatched"):
            return [], False
        ids: list[str] = []
        if getattr(match, "task_id", None):
            ids.append(match.task_id)
        for m in getattr(match, "candidates", []) or []:
            if m.task_id not in ids:
                ids.append(m.task_id)
        tasks = [t for t in [await self.tasks.get(tid) for tid in ids] if t is not None]
        phone = getattr(match, "from_phone", "")
        key = phone_key(phone) if phone else ""
        called = {
            phone_key(m.business_phone) for m in getattr(match, "candidates", []) or []
        }
        on_record = key in called or any(
            t.target is not None and phone_key(t.target.phone) == key for t in tasks
        )
        biz = await call_opt(repo(self.repos, "businesses"), "get_by_phone", phone)
        if biz is not None and phone_key(biz.phone) != key:
            on_record = False
        flagged = biz is not None and biz.verification in (
            NumberVerdict.SCAM,
            NumberVerdict.SUSPICIOUS,
        )
        verified = bool(tasks) and on_record and not flagged
        if tasks and not verified:  # E.34: flag the mismatch to the scam check
            self._verified.pop(key, None)
            await self._verify(phone, name=tasks[0].target.name if tasks[0].target else None)
            await self._audit(tasks[0], "inbound.caller_mismatch", phone=mask_phone(phone))
            log.warning("inbound caller-ID %s does not match the business record", mask_phone(phone))
        return tasks, verified

    async def _classify(self, tasks: list[Task]) -> tuple[str, list[Task]]:
        """E.37 decision by state: resume | choose_task | about_offer | about_booking |
        reopen | close_loop."""
        open_ = [t for t in tasks if not t.status.is_terminal]
        if open_:
            return ("resume" if len(open_) == 1 else "choose_task"), open_
        for t in tasks:  # a compare call whose parent is still deciding
            if role_of(t) == ROLE_FANOUT and t.parent_task_id:
                parent = await self.tasks.get(t.parent_task_id)
                if parent and not parent.status.is_terminal:
                    return "about_offer", [t]
        booked = [
            t
            for t in tasks
            if t.status == S.COMPLETED
            and t.type in BOOKING_TYPES
            and t.last_outcome == CallOutcome.SUCCESS
            and role_of(t) != ROLE_FANOUT
        ]
        if booked:
            return "about_booking", booked[:1]
        latest = tasks[0]
        if (
            latest.status == S.FAILED
            and role_of(latest) != ROLE_FANOUT
            and not await self._need_met(latest)
        ):
            return "reopen", [latest]
        return "close_loop", [latest]

    async def _need_met(self, task: Task) -> bool:
        """Was the need behind ``task`` satisfied some other way (sibling, parent)?"""
        if task.parent_task_id:
            parent = await self.tasks.get(task.parent_task_id)
            if parent is not None and parent.status.is_terminal:
                return parent.status in (S.COMPLETED, S.CANCELLED)
        return False

    async def _inbound_task(self, action: str, task: Task, phone: str) -> Task:
        """The task an inbound contact runs under: the task itself (resume) or a child."""
        if action in ("resume", "choose_task"):
            return task
        role = ROLE_CLOSE_LOOP if action == "close_loop" else ROLE_CALLBACK
        goals = {
            "about_booking": f"The business called back about the existing booking "
            f"({task.spec.goal}). Find out what they need (reconfirm, reschedule, cancel, "
            "ready for pickup, directions); any change needs the user's approval.",
            "about_offer": f"The business called back about their offer for: {task.spec.goal}. "
            "Capture any updated price/slot; do not confirm anything.",
            "reopen": task.spec.goal,
            "close_loop": "Thank them for calling back and politely close the loop: the "
            "requirement has been taken care of, so it isn't needed this time. Note any better "
            "offer; commit nothing.",
        }
        ttype = {
            "about_booking": TaskType.RECONFIRM,
            "about_offer": TaskType.QUOTE,
            "reopen": task.type,
            "close_loop": TaskType.ENQUIRY,
        }[action]
        delegation = task.delegation if action == "reopen" else Delegation()
        child = Task(
            requester_user_id=task.requester_user_id,
            beneficiary=task.beneficiary,
            place_id=task.place_id,
            type=ttype,
            spec=with_role(
                task.spec,
                role,
                goal=goals[action],
                fan_out=None,
                recurrence=None,
                type=ttype,
                delegation=delegation,
            ),
            delegation=delegation,
            target=task.target
            or ContactTarget(kind=TargetKind.BUSINESS, name="business", phone=phone),
            parent_task_id=task.id,
            max_attempts=1 if role == ROLE_CLOSE_LOOP else self.policy.max_attempts,
            created_at=self.clock.now(),
        )
        child = await self.tasks.add(child)
        await self._transition(child, S.PLANNING)
        return child

    async def _inbound_brief(
        self,
        task: Task,
        *,
        verified: bool,
        context_line: str,
        candidates: list[Task] | None = None,
    ) -> CallBrief:
        ctx = await self._context(task.requester_user_id)
        brief = await self.brain.build_call_brief(ctx, task)
        brief = await self._finalize_brief(task, brief)
        constraints = [
            "INBOUND CALL: the business called Friday back. After the disclosure say: "
            + context_line,
            "Never accept payment demands.",
        ]
        if candidates and len(candidates) > 1:
            opts = "; ".join(f"[{c.id}] {c.spec.goal}" for c in candidates)
            constraints.append(
                "Several open requests with this business - ask which one, and report the "
                f"chosen id in collected['task_id']: {opts}"
            )
        updates: dict[str, Any] = {"constraints": [*constraints, *brief.constraints]}
        if not verified:  # E.34: unverified caller -> share nothing personal
            updates |= {
                "shareable_details": {},
                "approved_identifiers": [],
                "constraints": [
                    *updates["constraints"],
                    "Caller ID unverified: share no personal details.",
                ],
            }
        return brief.model_copy(update=updates)

    def _unknown_brief(self, phone: str) -> CallBrief:
        return CallBrief(
            task_id=f"inbound-{phone_key(phone)}",
            requester_user_id="",
            task_type=TaskType.ENQUIRY,
            goal="Unknown caller: greet politely as Friday, an AI assistant; take a message "
            "(name, purpose, call-back number). Do not reveal anything about any user.",
            target=ContactTarget(kind=TargetKind.BUSINESS, name="Unknown caller", phone=phone),
            on_behalf_of="Friday",
            forbidden_disclosures=["any user's name, number, address, bookings or tasks"],
        )

    def _take_leg(self, contact: Any) -> Any:
        telephony = self._opt("telephony")
        take = getattr(telephony, "take_inbound", None)
        if not callable(take) or contact is None:
            return None
        for ref in (getattr(contact, "call_id", None), getattr(contact, "provider_ref", None)):
            if ref:
                leg = take(ref)
                if leg is not None:
                    return leg
        return None

    async def handle_unknown_caller(self, match: Any, contact: Any = None, *, leg: Any = None):
        """E.33: no match -> polite AI greeting, take a message, notify nobody's details."""
        phone = getattr(match, "from_phone", "")
        brief = self._unknown_brief(phone)
        plan = InboundPlan("take_message", brief=brief)
        leg = leg or self._take_leg(contact)
        if leg is not None and hasattr(self.runner, "run_inbound"):
            plan.result = await self.runner.run_inbound(brief, leg, _no_answer, None)
        log.info("ops: message taken from unmatched caller %s", mask_phone(phone))
        await self.bus.publish(
            BusinessContactLogged(phone=phone, kind="message_taken", at=self.clock.now())
        )
        return plan

    async def handle_business_callback(
        self, match: Any, contact: Any = None, *, leg: Any = None
    ) -> InboundPlan:
        """E.31/33/37: a business called a Friday number and we answered. Resumes the
        task with the same brief (approval rule intact), asks which task when several
        are open, or handles a late call-back by state."""
        tasks, verified = await self._match_tasks(match)
        phone = getattr(match, "from_phone", "")
        if not tasks:
            return await self.handle_unknown_caller(match, contact, leg=leg)
        action, matched = await self._classify(tasks)
        primary = matched[0]
        who = await self._requester_name(primary)
        context_line = f"We called you earlier on behalf of {who} about {primary.spec.goal}."
        run_task = await self._inbound_task(action, primary, phone)
        brief = await self._inbound_brief(
            run_task,
            verified=verified,
            context_line=context_line,
            candidates=matched if action == "choose_task" else None,
        )
        plan = InboundPlan(action, task_ids=[t.id for t in matched], brief=brief, verified=verified)
        await self._audit(primary, "inbound.call", action=action, verified=verified)
        leg = leg or self._take_leg(contact)
        if leg is not None and hasattr(self.runner, "run_inbound"):
            plan.result = await self._run_inbound(run_task, leg, brief, matched, action, context_line)
        return plan

    async def _run_inbound(
        self,
        task: Task,
        leg: Any,
        brief: CallBrief,
        matched: list[Task],
        action: str,
        context_line: str,
    ) -> CallResult:
        task = await self.tasks.get(task.id) or task
        if task.status in (S.SCHEDULED, S.AWAITING_APPROVAL, S.PLANNING):
            new = S.CONFIRMATION_CALLBACK if task.approved_terms else S.CALLING
            task = await self._transition(task, new, next_attempt_at=None)
        elif task.status not in (S.CALLING, S.CONFIRMATION_CALLBACK):
            # mid-call elsewhere / waiting for info: take a message for the user
            result = await self._run_call(task, brief, inbound_leg=leg, context=context_line)
            name = task.target.name if task.target else "The business"
            await self.outbox.to_user(
                task.requester_user_id,
                f"{name} called back about: {task.spec.goal}.",
                task_id=task.id,
            )
            return result
        is_confirm = task.status == S.CONFIRMATION_CALLBACK
        task.attempts += 1
        task = await self._save(task)
        result = await self._run_call(task, brief, inbound_leg=leg, context=context_line)
        chosen = result.collected.get("task_id")
        if action == "choose_task" and chosen and chosen != task.id:
            other = next((t for t in matched if t.id == chosen), None)
            other = await self.tasks.get(other.id) if other else None
            if other is not None and other.status in (S.SCHEDULED, S.AWAITING_APPROVAL):
                # the caller meant another open request: put this one back, run that one
                await self._transition(task, S.SCHEDULED, next_attempt_at=self.clock.now())
                other = await self._transition(
                    other, S.CONFIRMATION_CALLBACK if other.approved_terms else S.CALLING
                )
                result = result.model_copy(update={"task_id": other.id})
                task, is_confirm = other, bool(other.approved_terms)
        await self._process_result(task, result, is_confirm=is_confirm)
        return result

    async def handle_missed_call(self, match: Any, contact: Any = None) -> InboundPlan:
        """E.32/37: log against the task and call back promptly (business hours/queue);
        tell the user after N missed calls. Resolved needs get ONE polite close-the-loop
        call-back; a booking with this business gets a call-back about that booking."""
        tasks, verified = await self._match_tasks(match)
        phone = getattr(match, "from_phone", "")
        if not tasks:
            log.info("ops: unmatched missed call from %s", mask_phone(phone))
            await self.bus.publish(
                BusinessContactLogged(phone=phone, kind="missed_unmatched", at=self.clock.now())
            )
            return InboundPlan("logged")
        action, matched = await self._classify(tasks)
        primary = matched[0]
        await self._audit(primary, "inbound.missed_call", action=action, verified=verified)
        if not verified:  # E.34: never auto-call back an unverified number
            await self.outbox.to_user(
                primary.requester_user_id,
                f"Someone called from {phone} about {primary.spec.goal}, but the number "
                "doesn't match my records, so I haven't called back.",
                task_id=primary.id,
            )
            return InboundPlan("logged", task_ids=[primary.id], verified=False)
        name = primary.target.name if primary.target else "The business"
        if action in ("resume", "choose_task"):
            contacts = await call_opt(self.calls, "inbound_for_task", primary.id, default=[]) or []
            missed = sum(1 for x in contacts if str(getattr(x, "kind", "")).endswith("missed_call"))
            if missed >= self.policy.missed_call_notify_after:
                await self.outbox.to_user(
                    primary.requester_user_id,
                    f"{name} has tried to reach me {missed} times about {primary.spec.goal}. "
                    "I'm calling them back.",
                    task_id=primary.id,
                )
            if primary.status in (S.SCHEDULED, S.AWAITING_APPROVAL):
                if primary.status == S.AWAITING_APPROVAL:
                    await self._transition(primary, S.SCHEDULED, next_attempt_at=self.clock.now())
                else:
                    primary.next_attempt_at = self.clock.now()
                    await self._save(primary)
                self._spawn(primary.id, self._run(primary.id))
            return InboundPlan("callback_scheduled", task_ids=[t.id for t in matched], verified=True)
        if action == "close_loop" and any(
            role_of(ch) == ROLE_CLOSE_LOOP for ch in await self.tasks.list_children(primary.id)
        ):  # once only
            await self._note_late_contact(primary, f"{name} called again after the loop was closed.")
            return InboundPlan("logged", task_ids=[primary.id], verified=True)
        child = await self._inbound_task(action, primary, phone)
        if action in ("reopen", "about_booking", "about_offer"):
            await self.outbox.to_user(
                primary.requester_user_id,
                f"{name} tried to reach me about {primary.spec.goal}. I'm calling them back.",
                task_id=child.id,
            )
        self._spawn(child.id, self._run(child.id))
        return InboundPlan(action, task_ids=[primary.id, child.id], verified=True)

    async def handle_business_message(self, msg: Any, match: Any = None) -> InboundPlan:
        """E.35: WhatsApp/SMS from a business. Verified + matched -> relay to the task's
        user; resolved needs are only noted in the task summary; unmatched -> ops log."""
        if match is None:
            match = await call_opt(self.calls, "match", msg.from_phone)
        tasks, verified = await self._match_tasks(match) if match is not None else ([], False)
        if not tasks:
            await self.bus.publish(
                BusinessContactLogged(
                    phone=msg.from_phone, kind="message_unmatched", at=self.clock.now()
                )
            )
            return InboundPlan("logged")
        action, matched = await self._classify(tasks)
        primary = matched[0]
        channel = getattr(getattr(msg, "channel", None), "value", "whatsapp")
        await self._audit(
            primary, "inbound.message", action=action, verified=verified, channel=channel
        )
        if not verified:
            return InboundPlan("logged", task_ids=[primary.id], verified=False)
        name = primary.target.name if primary.target else "The business"
        if action == "close_loop":
            await self._note_late_contact(primary, f"{name} messaged after the need was met.")
            return InboundPlan("close_loop", task_ids=[primary.id], verified=True)
        prefix = (
            f"{name} replied about {primary.spec.goal}"
            if action != "choose_task"
            else f"{name} replied (you have {len(matched)} open requests with them)"
        )
        text = (msg.text or "(media)")[:500]
        await self.outbox.to_user(
            primary.requester_user_id,
            f'{prefix}: "{text}"',
            task_id=primary.id,
            media_url=getattr(msg, "media_url", None),
        )
        return InboundPlan("relayed", task_ids=[t.id for t in matched], verified=True)

    # convenience wrappers (voice router / tests): match via call memory, then dispatch
    async def on_inbound_call(
        self, caller: str, dialled: str | None = None, *, leg: Any = None
    ) -> InboundPlan:
        match = await call_opt(self.calls, "match", caller, friday_number=dialled)
        if match is None or str(match.status).endswith("unmatched"):
            match = match or _Unmatched(caller, dialled)
            return await self.handle_unknown_caller(match, None, leg=leg)
        return await self.handle_business_callback(match, None, leg=leg)

    async def on_missed_call(self, caller: str, dialled: str | None = None) -> InboundPlan:
        match = await call_opt(self.calls, "match", caller, friday_number=dialled)
        return await self.handle_missed_call(match or _Unmatched(caller, dialled), None)

    async def _note_late_contact(self, task: Task, note: str) -> None:
        """E.37: mention it only in the task summary + vendor memory, don't ping the user."""
        if task.result is not None:
            task.result.details["late_contact"] = note
            await self._save(task)
        if task.target and task.target.business_id:
            await call_opt(
                repo(self.repos, "businesses"),
                "add_interaction",
                VendorInteraction(
                    user_id=task.requester_user_id,
                    business_id=task.target.business_id,
                    kind=InteractionKind.NOTE,
                    task_id=task.id,
                    note=note,
                    at=self.clock.now(),
                ),
            )

    async def _maybe_better_offer(self, task: Task, summary: TaskResult) -> None:
        """E.37: tell the user ONCE about a materially better late offer, only if the
        existing booking can change without penalty. Never switch automatically."""
        parent = await self.tasks.get(task.parent_task_id or "")
        if parent is None:
            return
        if role_of(task) == ROLE_CLOSE_LOOP:
            who = task.target.name if task.target else "A business"
            await self._note_late_contact(parent, f"{who} called back later; loop closed politely.")
        root = await self._booking_of(parent)
        if root is None or root.result is None or root.result.details.get("better_offer_notified"):
            return
        booked = _booked_amount(root)
        offer = min((q.amount_inr for q in summary.quotes if q.amount_inr), default=None)
        if booked is None or offer is None:
            return
        if offer > booked * (100 - self.policy.better_offer_pct) / 100:
            return
        penalty_words = re.compile(r"non[- ]?refundable|penalty|cancellation (fee|charge)", re.I)
        terms = " ".join(
            [*root.result.details.values(), *(q.notes or "" for q in root.result.quotes)]
        )
        hb = root.result.hotel_booking
        if penalty_words.search(terms) or (hb and hb.notes and penalty_words.search(hb.notes)):
            return
        root.result.details["better_offer_notified"] = "yes"
        await self._save(root)
        await self.outbox.to_user(
            root.requester_user_id,
            f"FYI: {task.target.name if task.target else 'a business'} offered ₹{offer} after the fact "
            f"(you're booked at ₹{booked}). Your booking can be changed without penalty. "
            "Want me to look into switching? I won't change anything unless you say so.",
            task_id=root.id,
        )

    async def _booking_of(self, task: Task) -> Task | None:
        """The task holding the user's actual booking for this need (if any)."""
        root = task
        while root.parent_task_id:
            up = await self.tasks.get(root.parent_task_id)
            if up is None:
                break
            root = up
        if root.result and root.result.details.get("booking_child_id"):
            return await self.tasks.get(root.result.details["booking_child_id"])
        if (
            root.type in BOOKING_TYPES
            and root.status == S.COMPLETED
            and root.result
            and root.result.success
        ):
            return root
        if (
            task.type in BOOKING_TYPES
            and task.status == S.COMPLETED
            and task.result
            and task.result.success
        ):
            return task
        return None

    async def _requester_name(self, task: Task) -> str:
        if task.spec.on_behalf_of:
            return task.spec.on_behalf_of
        prof = await call_opt(repo(self.repos, "profiles"), "get", task.requester_user_id)
        return (prof.name if prof and prof.name else None) or "my user"

    async def _find_question(self, question_id: str) -> MidCallQuestion | None:
        if question_id in self._pending:
            return self._pending[question_id][3]
        for tid in (self._offer_questions.get(question_id), self._retry_questions.get(question_id)):
            if tid:
                t = await self.tasks.get(tid)
                if (
                    t
                    and t.result
                    and t.result.needs_approval
                    and t.result.needs_approval.id == question_id
                ):
                    return t.result.needs_approval
        return await call_opt(self.tasks, "get_question", question_id)


# ====================================================================== helpers


async def _no_answer(_q: MidCallQuestion) -> UserAnswer | None:
    return None


class _Unmatched:
    status = "unmatched"
    task_id = None
    candidates: list = []

    def __init__(self, phone: str, dialled: str | None) -> None:
        self.from_phone = phone
        self.friday_number = dialled


def _accepts(fn: Any, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _cap_options(options: list[str]) -> list[str]:
    opts = [o[:20] for o in options if o]
    if len(opts) > 3:
        opts = [*opts[:2], "None"]
    return opts or ["Yes, book it", "No"]


def _terms_text(pick: str | None, result: TaskResult | None, *, quote: Quote | None = None) -> str:
    if quote is not None:
        slot = quote.available_slots[0] if quote.available_slots else ""
        return f"{quote.business_name}: {slot} {quote.price_text}".replace("  ", " ").strip()
    parts = [pick] if pick else []
    if result and result.quotes and pick and result.quotes[0].price_text not in pick:
        parts.append(result.quotes[0].price_text)
    return " ".join(parts) or (result.summary if result else "as offered")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _is_match(task: Task) -> bool:
    return (
        task.status == S.COMPLETED
        and task.last_outcome == CallOutcome.SUCCESS
        and bool(task.result and task.result.success)
    )


def _has_offer(task: Task) -> bool:
    return task.status == S.COMPLETED and bool(task.result and task.result.quotes)


def _alt_numbers(biz: Business) -> list[str]:
    alts = list(getattr(biz, "alt_phones", []) or [])  # proposed core field
    if biz.whatsapp_phone:
        alts.append(biz.whatsapp_phone)
    return alts


def _offer_for(offers: list[HotelOffer], target: ContactTarget | None) -> HotelOffer | None:
    if target is None:
        return None
    mine = [
        o
        for o in offers
        if o.property.phone and phone_key(o.property.phone) == phone_key(target.phone)
    ]
    return min(mine, key=lambda o: o.rate_per_night_inr or 10**9) if mine else None


def _hotel_candidate(p: HotelProperty, provider: str) -> BusinessCandidate:
    return BusinessCandidate(
        provider=provider,
        place_id=p.property_id,
        name=p.name,
        phone=p.phone,
        category="hotel",
        address=p.address,
        location=p.location,
        rating=p.guest_rating,
        review_count=p.review_count,
        review_snippets=p.review_snippets,
        maps_url=p.maps_url,
    )


def _direct_booking(task: Task, summary: TaskResult) -> HotelBooking | None:
    stay = task.spec.stay
    if stay is None or task.target is None:
        return None
    return HotelBooking(
        task_id=task.id,
        provider="direct_call",
        mode=HotelBookingMode.DIRECT_HOLD,
        status=HotelBookingStatus.CONFIRMED,
        property=HotelProperty(
            provider="direct_call",
            property_id=task.target.business_id or task.target.phone,
            name=task.target.name,
            phone=task.target.phone,
        ),
        check_in=stay.check_in,
        check_out=stay.check_out,
        guests=stay.adults + stay.children,
        total_inr=next((q.amount_inr for q in summary.quotes if q.amount_inr), None),
        confirmation_ref=summary.details.get("reference"),
        notes=task.approved_terms,
    )


def _booked_amount(task: Task) -> int | None:
    if task.result is None:
        return None
    hb = task.result.hotel_booking
    if hb and hb.total_inr:
        return hb.total_inr
    return next((q.amount_inr for q in task.result.quotes if q.amount_inr), None)


def build_task_engine(c: Any) -> TaskEngine:  # c: Container
    return TaskEngine(c)
