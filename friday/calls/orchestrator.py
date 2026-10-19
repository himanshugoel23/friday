"""Scheduler glue and the AFTER of a call: gate -> task -> dial (W2 engine) -> outcome -> report ->
retry / group collection / opt-out handling.

Safety properties enforced here (and tested):
* No dial without a gate ``allow`` on the current brief; the gate runs again right before every
  dial, so a do-not-call mark made in between, a changed brief or a switched-off kill switch
  all stop the call.
* At most one dial per attempt: the attempt counter is saved BEFORE the engine runs, task keys
  are ``callreq:<request>:<attempt>`` (idempotent), a crash mid-call is never redialled
  automatically (``recover_stale`` closes it and tells the user).
* Retries use the existing task policy (``tasks.scheduling.retry_at`` with ``TaskPolicy``: +1 h,
  +3 h, max 3) aligned to the calling window of the callee kind. Opt-out, wrong-person and a
  do-not-call mark stop every retry, for every user.
* The model never decides: the engine returns an outcome, this code applies the rules.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from friday.calls import copy
from friday.calls.approval import (
    ApprovalService,
    StaleApproval,
    parse_button,
)
from friday.calls.brief import build_brief
from friday.calls.dnc import DncRegistry
from friday.calls.gate import CallGate, GateDecision, Verdict, next_window_start
from friday.calls.interfaces import Callee, LiveCallEngine, TaskPort, UserNotifier
from friday.calls.models import (
    CallBrief,
    CalleeKind,
    CallOutcome,
    CallRequest,
    CallStatus,
    NextAction,
    OutcomeStatus,
)
from friday.calls.numbers import NumberHasher, canonical, mask
from friday.calls.recordings import RecordingNotFound, RecordingService
from friday.calls.report import ReportBuilder, parse_action
from friday.calls.settings import CallsSettings
from friday.calls.stores import AttemptRecord, CallStore
from friday.calls.understand import Draft
from friday.core.clock import Clock, SystemClock, format_ist
from friday.core.logging import get_logger
from friday.core.models import CallOutcome as CoreOutcome
from friday.core.models import User, new_id
from friday.tasks.policy import TaskPolicy
from friday.tasks.scheduling import retry_at

log = get_logger(__name__)

_RETRY_MAP = {
    OutcomeStatus.NO_ANSWER: CoreOutcome.NO_ANSWER,
    OutcomeStatus.BUSY: CoreOutcome.BUSY,
    OutcomeStatus.VOICEMAIL: CoreOutcome.VOICEMAIL,
    OutcomeStatus.FAILED: CoreOutcome.FAILED,
    OutcomeStatus.CALLBACK_LATER: CoreOutcome.CALLBACK_LATER,
}
_STOPS = (OutcomeStatus.OPTED_OUT, OutcomeStatus.WRONG_PERSON, OutcomeStatus.SAFETY_STOP)
ENGINE_GRACE_S = 30


class UserDirectory(Protocol):
    async def get(self, user_id: str) -> User | None: ...


@dataclass
class Member:
    """One resolved member of a group call (the intake resolved name -> number)."""

    name: str
    number: str = field(repr=False)
    confirmed: bool = False
    kind: CalleeKind = CalleeKind.FAMILY_FRIEND


@dataclass
class SubmitResult:
    status: CallStatus
    decision: GateDecision | None = None
    task_id: str | None = None
    created: bool = True


@dataclass
class ButtonResult:
    handled: bool
    action: str | None = None
    request_id: str | None = None
    next_action: NextAction | None = None
    status: CallStatus | None = None


def _lang(brief: CallBrief | None, request: CallRequest) -> str:
    lang = brief.language if brief else request.language
    return lang if lang in ("hinglish", "en") else copy.DEFAULT_LANGUAGE


class CallOrchestrator:
    def __init__(
        self,
        *,
        store: CallStore,
        gate: CallGate,
        approval: ApprovalService,
        dnc: DncRegistry,
        hasher: NumberHasher,
        engine: LiveCallEngine,
        notifier: UserNotifier,
        tasks: TaskPort,
        users: UserDirectory,
        clock: Clock | None = None,
        settings: CallsSettings | None = None,
        policy: TaskPolicy | None = None,
        recordings: RecordingService | None = None,
        reports: ReportBuilder | None = None,
    ) -> None:
        self.store, self.gate, self.approval = store, gate, approval
        self.dnc, self.hasher, self.engine = dnc, hasher, engine
        self.notifier, self.tasks, self.users = notifier, tasks, users
        self.clock: Clock = clock or SystemClock()
        self.settings = settings or gate.settings
        self.policy = policy or TaskPolicy()
        self.recordings = recordings
        self.reports = reports or ReportBuilder()
        self.max_attempts = min(self.policy.max_attempts, self.settings.retry_max_attempts)
        self._group_locks: dict[str, asyncio.Lock] = {}

    # ================================================================== approval -> schedule
    async def submit(self, request_id: str) -> SubmitResult:
        """The user approved: gate it and schedule it. Safe to call twice (idempotent)."""
        request = await self.store.get_request(request_id)
        brief = await self.store.get_brief(request_id)
        if request is None or brief is None:
            raise LookupError("unknown request")
        if request.status in (CallStatus.SCHEDULED, CallStatus.CALLING, CallStatus.GROUP_WAITING):
            return SubmitResult(request.status, task_id=request.task_id, created=False)
        if request.status.is_terminal:
            return SubmitResult(request.status, created=False)
        user = await self.users.get(request.user_id)
        if user is None:
            raise LookupError("unknown user")
        now = self.clock.now()
        decision = await self.gate.decide(request, brief, user, now)
        if decision.verdict == Verdict.DENY:
            return await self._deny(request, brief, decision)
        if decision.verdict == Verdict.ASK:
            return await self._ask(request, brief, decision, now)
        if request.callee_kind == CalleeKind.GROUP:
            return await self._start_group(request, brief)
        run_at = max(now, request.scheduled_for or now)
        return await self._schedule(request, brief, run_at, decision)

    async def _schedule(
        self,
        request: CallRequest,
        brief: CallBrief,
        run_at: datetime,
        decision: GateDecision | None,
        *,
        parent_task_id: str | None = None,
    ) -> SubmitResult:
        attempt = request.attempts + 1
        task_id = await self.tasks.create(
            key=f"callreq:{request.id}:{attempt}",
            request=request,
            run_at=run_at,
            parent_task_id=parent_task_id,
        )
        request.status = CallStatus.SCHEDULED
        request.next_attempt_at = run_at
        request.task_id = task_id
        request.updated_at = self.clock.now()
        await self.store.save_request(request)
        log.info(
            "call %s scheduled kind=%s to=%s",
            request.id,
            request.callee_kind,
            mask(request.callee_number),
        )
        return SubmitResult(CallStatus.SCHEDULED, decision, task_id)

    async def _deny(
        self, request: CallRequest, brief: CallBrief, decision: GateDecision
    ) -> SubmitResult:
        request.status = CallStatus.DENIED
        request.updated_at = self.clock.now()
        await self.store.save_request(request)
        if decision.strike:
            await self.store.add_strike(
                request.user_id, decision.category or "abuse", self.clock.now()
            )
        lang = _lang(brief, request)
        await self.notifier.send(
            request.user_id, copy.line(decision.refusal_key or "deny_generic", lang)
        )
        log.info("call %s denied reasons=%s", request.id, decision.reasons)
        return SubmitResult(CallStatus.DENIED, decision, created=False)

    async def _ask(
        self, request: CallRequest, brief: CallBrief, decision: GateDecision, now: datetime
    ) -> SubmitResult:
        reasons = set(decision.reasons)
        lang = _lang(brief, request)
        if reasons & {"approval_missing", "approval_stale", "approval_expired"}:
            stale = bool(reasons & {"approval_stale", "approval_expired"})
            fresh, prompt = await self.approval.prepare(request, brief, stale=stale)
            await self.store.save_brief(fresh)
            request.status = CallStatus.AWAITING_APPROVAL
            await self.store.save_request(request)
            await self.notifier.send(request.user_id, prompt.text, prompt.buttons)
            return SubmitResult(CallStatus.AWAITING_APPROVAL, decision, created=False)
        if "number_unconfirmed" in reasons:
            request.status = CallStatus.NEEDS_INFO
            await self.store.save_request(request)
            await self.notifier.send(
                request.user_id,
                copy.line(
                    "confirm_number_back", lang, name=request.callee_name or "-",
                    masked=(request.callee_number or "")[-4:],
                ),
            )  # fmt: skip
            return SubmitResult(CallStatus.NEEDS_INFO, decision, created=False)
        if decision.defer_until is not None:  # only the calling window is in the way
            run_at = max(decision.defer_until, request.scheduled_for or decision.defer_until)
            result = await self._schedule(request, brief, run_at, decision)
            await self.notifier.send(
                request.user_id,
                copy.line("sched_later", lang, name=request.callee_name or "-",
                          when=format_ist(run_at, "%a %I:%M %p")),
            )  # fmt: skip
            return result
        return await self._deny(request, brief, decision)

    # ================================================================== group
    async def create_group(
        self,
        draft: Draft,
        *,
        user: User,
        message_id: str | None,
        members: list[Member],
        user_display_name: str | None = None,
    ) -> tuple[CallRequest, CallBrief, list[CallRequest]]:
        """Parent request + one DRAFT child request per member (idempotent on the message id)."""
        draft = draft.model_copy(update={"callee_kind": CalleeKind.GROUP})
        parent, brief, created = await self.create_from_draft(
            draft, user=user, message_id=message_id, callee_name=None, callee_number=None,
            number_confirmed=True, kind=CalleeKind.GROUP, user_display_name=user_display_name,
        )  # fmt: skip
        if len(members) > self.settings.group_max_members:
            parent.group_members = [m.name for m in members]  # so the gate can refuse the size
            await self.store.save_request(parent)
            return parent, brief, []
        parent.group_members = [m.name for m in members]
        await self.store.save_request(parent)
        kids: list[CallRequest] = []
        for i, m in enumerate(members):
            e164 = canonical(m.number)
            child = CallRequest(
                user_id=parent.user_id, callee_kind=m.kind, purpose=parent.purpose,
                purpose_kind=parent.purpose_kind, callee_ref=m.name, callee_name=m.name,
                callee_number=e164, number_confirmed=m.confirmed, language=parent.language,
                scheduled_for=parent.scheduled_for, parent_id=parent.id, raw_text=parent.raw_text,
                source_message_id=f"{parent.id}:{i}",
            )  # fmt: skip
            child, _ = await self.store.create_request(child)
            kids.append(child)
        return parent, brief, kids

    async def submit_group(self, parent_id: str) -> SubmitResult:
        """The user approved the group plan: gate the parent, then fan out to the children."""
        parent = await self.store.get_request(parent_id)
        brief = await self.store.get_brief(parent_id)
        if parent is None or brief is None:
            raise LookupError("unknown request")
        result = await self.submit(parent_id)
        if result.status != CallStatus.GROUP_WAITING or not result.created:
            return result
        kids = [k for k in await self.store.children(parent_id) if k.status == CallStatus.DRAFT]
        pairs: list[tuple[CallRequest, CallBrief]] = []
        for child in kids:
            e164 = canonical(child.callee_number or "")
            pairs.append((child, brief.model_copy(update={
                "request_id": child.id, "callee_kind": child.callee_kind,
                "callee_name": child.callee_name,
                "callee_number_hash": self.hasher.hash(e164) if e164 else None,
            })))  # fmt: skip
        for (child, _), cb in zip(pairs, self.approval.derive_children(brief, pairs), strict=True):
            await self.store.save_brief(cb)
            await self.submit(child.id)
        await self.notifier.send(
            parent.user_id,
            copy.line("sched_group_started", _lang(brief, parent), n=len(kids)),
        )
        await self._maybe_finish_group(parent_id)  # every child may already be denied
        return SubmitResult(CallStatus.GROUP_WAITING, result.decision, parent.task_id)

    async def _start_group(self, parent: CallRequest, brief: CallBrief) -> SubmitResult:
        task_id = await self.tasks.create(
            key=f"callreq:{parent.id}:0", request=parent, run_at=self.clock.now()
        )
        parent.status, parent.task_id = CallStatus.GROUP_WAITING, task_id
        parent.updated_at = self.clock.now()
        await self.store.save_request(parent)
        return SubmitResult(CallStatus.GROUP_WAITING, None, task_id)

    async def _maybe_finish_group(self, parent_id: str) -> None:
        # two children can finish at the same moment on a concurrent worker: one report only
        async with self._group_locks.setdefault(parent_id, asyncio.Lock()):
            await self._finish_group_locked(parent_id)

    async def _finish_group_locked(self, parent_id: str) -> None:
        parent = await self.store.get_request(parent_id)
        if parent is None or parent.status != CallStatus.GROUP_WAITING:
            return
        kids = await self.store.children(parent_id)
        if not kids or any(not k.status.is_terminal for k in kids):
            return
        rows = []
        for k in kids:
            outs = await self.store.outcomes(k.id)
            rows.append((k, outs[-1] if outs else None))
        brief = await self.store.get_brief(parent_id)
        rep = self.reports.group(parent, brief, rows)
        parent.status = CallStatus.COMPLETED
        parent.updated_at = self.clock.now()
        await self.store.save_request(parent)
        await self.notifier.send(parent.user_id, rep.text, rep.buttons)

    # ================================================================== dialling
    async def run_due(self, now: datetime | None = None) -> int:
        """Execute every request whose time has come. The task engine's job calls ``execute``."""
        now = now or self.clock.now()
        n = 0
        for r in await self.store.due(now):
            await self.execute(r.id)
            n += 1
        return n

    async def execute(self, request_id: str) -> CallOutcome | None:
        now = self.clock.now()
        request = await self.store.get_request(request_id)
        if request is None or request.status != CallStatus.SCHEDULED:
            return None
        if request.next_attempt_at and request.next_attempt_at > now:
            return None
        brief = await self.store.get_brief(request_id)
        user = await self.users.get(request.user_id)
        if brief is None or user is None:
            return None
        decision = await self.gate.decide(request, brief, user, now)  # again, right before dialling
        if decision.verdict != Verdict.ALLOW:
            if (
                decision.verdict == Verdict.ASK
                and decision.defer_until
                and set(decision.reasons) == {"outside_window"}
            ):
                request.next_attempt_at = decision.defer_until
                await self.store.save_request(request)
                return None
            if decision.verdict == Verdict.ASK:
                await self._ask(request, brief, decision, now)
            else:
                await self._deny(request, brief, decision)
            await self._after_terminal(request)
            return None
        number = canonical(request.callee_number or "")
        if number is None:  # defensive: the gate already checked
            return None
        # at-most-once: persist the attempt BEFORE the engine runs
        request.attempts += 1
        request.status = CallStatus.CALLING
        request.updated_at = now
        await self.store.save_request(request)
        callee = Callee(
            name=request.callee_name or request.callee_ref or "", number=number,
            kind=request.callee_kind, language=request.language,
            max_duration_s=decision.max_duration_s or self.settings.max_call_seconds,
        )  # fmt: skip
        number_hash = self.hasher.hash(number)
        try:
            outcome = await asyncio.wait_for(
                self.engine.run(brief, callee), callee.max_duration_s + ENGINE_GRACE_S
            )
        except Exception as e:  # noqa: BLE001 - the engine must not take the flow down
            log.error("live engine failed for call %s: %s", request.id, type(e).__name__)
            outcome = CallOutcome(
                request_id=request.id, attempt=request.attempts, status=OutcomeStatus.FAILED,
                summary="", started_at=now,
            )  # fmt: skip
        outcome = outcome.model_copy(update={"request_id": request.id, "attempt": request.attempts})
        await self.store.add_outcome(request.user_id, outcome, number_hash)
        await self.store.record_attempt(
            AttemptRecord(request.user_id, request.id, number_hash, now, outcome.duration_s)
        )
        await self._apply_outcome(request, brief, outcome, number)
        return outcome

    async def _apply_outcome(
        self, request: CallRequest, brief: CallBrief, outcome: CallOutcome, number: str
    ) -> None:
        now = self.clock.now()
        st = outcome.status
        # opt-out and mistakes are recorded for ALL users, first
        if st == OutcomeStatus.OPTED_OUT or outcome.do_not_call_again:
            await self.dnc.add(number, "opt_out_call", source=f"req:{request.id}")
        if st == OutcomeStatus.WRONG_PERSON:
            await self.dnc.add(number, "wrong_person", source=f"req:{request.id}")
        stop = st in _STOPS or outcome.do_not_call_again
        retry = st.is_retryable and not stop and request.attempts < self.max_attempts
        if retry:
            when = self._next_try(request, outcome, now)
            task_id = await self.tasks.create(
                key=f"callreq:{request.id}:{request.attempts + 1}", request=request, run_at=when
            )
            request.status, request.next_attempt_at, request.task_id = (
                CallStatus.SCHEDULED, when, task_id,
            )  # fmt: skip
            request.updated_at = now
            await self.store.save_request(request)
            first = request.attempts == 1 or st == OutcomeStatus.CALLBACK_LATER
            if first and request.parent_id is None:  # tell the user once, not on every attempt
                await self.notifier.send(
                    request.user_id, self.reports.retry_notice(request, brief, st, when)
                )
            return
        if st in _STOPS:
            request.status = CallStatus.CANCELLED
        elif st.is_retryable:
            request.status = CallStatus.FAILED
        else:
            request.status = CallStatus.COMPLETED
        request.updated_at = now
        await self.store.save_request(request)
        if request.parent_id is None:
            rep = self.reports.single(request, brief, outcome, attempts_used=request.attempts)
            await self.notifier.send(request.user_id, rep.text, rep.buttons, urgent=rep.urgent)
        await self._after_terminal(request)

    def _next_try(self, request: CallRequest, outcome: CallOutcome, now: datetime) -> datetime:
        when = retry_at(
            _RETRY_MAP[outcome.status], request.attempts, now, self.policy,
            callback_at=outcome.callback_at,
        )  # fmt: skip
        return next_window_start(request.callee_kind.value, when, self.settings)

    async def _after_terminal(self, request: CallRequest) -> None:
        if request.parent_id:
            await self._maybe_finish_group(request.parent_id)

    async def recover_stale(self, now: datetime | None = None) -> int:
        """A call stuck in CALLING (worker died) is closed, never redialled blindly."""
        now = now or self.clock.now()
        limit = timedelta(seconds=self.settings.max_call_seconds * 2 + ENGINE_GRACE_S)
        n = 0
        for r in await self.store.stale_calling(now - limit):
            r.status = CallStatus.FAILED
            r.updated_at = now
            await self.store.save_request(r)
            await self.notifier.send(
                r.user_id,
                copy.line("report_failed_final", _lang(None, r), name=r.callee_name or "-"),
            )
            await self._after_terminal(r)
            n += 1
        return n

    # ================================================================== cancel / repeat / buttons
    async def cancel(self, request_id: str) -> None:
        request = await self.store.get_request(request_id)
        if request is None or request.status.is_terminal:
            return
        for kid in await self.store.children(request_id):
            await self.cancel(kid.id)
        if request.task_id:
            await self.tasks.cancel(request.task_id)
        request.status = CallStatus.CANCELLED
        request.updated_at = self.clock.now()
        await self.store.save_request(request)

    async def repeat(self, origin_id: str, *, at: datetime | None = None) -> SubmitResult:
        """ "Call again" / "Call later": the user's explicit tap re-uses the plan they approved.
        A new request is created (own idempotency key); every gate rule still applies."""
        origin = await self.store.get_request(origin_id)
        old = await self.store.get_brief(origin_id)
        if origin is None or old is None or not old.is_approved_as_is():
            raise LookupError("nothing approved to repeat")
        now = self.clock.now()
        fresh = origin.model_copy(
            update={
                "id": new_id(),
                "status": CallStatus.DRAFT, "attempts": 0, "next_attempt_at": None,
                "task_id": None, "callback_of": origin.id, "scheduled_for": at,
                "source_message_id": f"repeat:{origin.id}:{now.isoformat()}",
                "created_at": now, "updated_at": now,
            }
        )  # fmt: skip
        fresh, _ = await self.store.create_request(fresh)
        brief = old.model_copy(
            update={
                "request_id": fresh.id,
                "approved": True,
                "approved_at": now,
                "approval_hash": None,
            }
        )
        brief = brief.model_copy(update={"approval_hash": brief.content_hash()})
        await self.store.save_brief(brief)
        return await self.submit(fresh.id)

    async def handle_button(self, user_id: str, button_id: str) -> ButtonResult:
        press = parse_button(button_id)
        if press is not None:
            return await self._approval_button(user_id, press.request_id, press.action, press.hash8)
        act = parse_action(button_id)
        if act is None:
            return ButtonResult(False)
        request_id, action = act
        request = await self.store.get_request(request_id)
        if request is None or request.user_id != user_id:  # per-user access only
            return ButtonResult(False)
        if action == NextAction.CALL_AGAIN:
            await self.repeat(request_id)
        elif action == NextAction.CALL_LATER:
            await self.repeat(
                request_id, at=self.clock.now() + timedelta(minutes=self.policy.vague_callback_min)
            )
        elif action == NextAction.STOP_CALLING:
            if request.callee_number:
                await self.dnc.add(
                    request.callee_number, "user_request", source=f"req:{request.id}"
                )
            await self.notifier.send(
                user_id,
                copy.line(
                    "stop_calling_ack", _lang(None, request), name=request.callee_name or "-"
                ),
            )
        elif action == NextAction.DELETE_RECORDING and self.recordings is not None:
            for rec in await self.store.recordings(user_id):
                if rec.request_id == request_id:
                    try:
                        await self.recordings.delete_now(user_id, rec.ref)
                    except RecordingNotFound:
                        continue
            await self.notifier.send(user_id, copy.line("recording_deleted", _lang(None, request)))
        return ButtonResult(True, "action", request_id, action)

    async def _approval_button(
        self, user_id: str, request_id: str, action: str, hash8: str
    ) -> ButtonResult:
        request = await self.store.get_request(request_id)
        brief = await self.store.get_brief(request_id)
        if request is None or brief is None or request.user_id != user_id:
            return ButtonResult(False)
        lang = _lang(brief, request)
        if action == "cancel":
            await self.cancel(request_id)
            await self.notifier.send(user_id, copy.line("approval_cancelled", lang))
            return ButtonResult(True, "cancel", request_id)
        if action == "edit":
            request.status = CallStatus.NEEDS_INFO
            await self.store.save_request(request)
            await self.store.save_brief(self.approval.edit(brief))
            await self.notifier.send(user_id, copy.line("approval_edit_prompt", lang))
            return ButtonResult(True, "edit", request_id)
        try:
            approved = self.approval.approve(brief, hash8, self.clock.now())
        except StaleApproval:
            fresh, prompt = await self.approval.prepare(request, brief, stale=True)
            await self.store.save_brief(fresh)
            await self.notifier.send(user_id, prompt.text, prompt.buttons)
            return ButtonResult(True, "stale", request_id)
        await self.store.save_brief(approved)
        if request.callee_kind == CalleeKind.GROUP:
            res = await self.submit_group(request_id)
        else:
            res = await self.submit(request_id)
        return ButtonResult(True, "approve", request_id, status=res.status)

    async def apply_edit(self, request_id: str, **changes: object) -> None:
        """The user's edit: a new brief version, approval dropped, a new approval message sent."""
        request = await self.store.get_request(request_id)
        brief = await self.store.get_brief(request_id)
        if request is None or brief is None:
            raise LookupError("unknown request")
        edited = self.approval.edit(brief, **changes)
        fresh, prompt = await self.approval.prepare(request, edited)
        await self.store.save_brief(fresh)
        request.status = CallStatus.AWAITING_APPROVAL
        await self.store.save_request(request)
        await self.notifier.send(request.user_id, prompt.text, prompt.buttons)

    # ================================================================== new request from a draft
    async def create_from_draft(
        self,
        draft: Draft,
        *,
        user: User,
        message_id: str | None,
        callee_name: str | None,
        callee_number: str | None,
        number_confirmed: bool,
        kind: CalleeKind | None = None,
        relationship: str | None = None,
        user_display_name: str | None = None,
    ) -> tuple[CallRequest, CallBrief, bool]:
        """Persist the request (idempotent on the message id) and its first, unapproved brief."""
        from friday.calls.brief import request_from_draft

        req = request_from_draft(
            draft, user_id=user.id, message_id=message_id, callee_name=callee_name,
            callee_number=canonical(callee_number) if callee_number else None,
            number_confirmed=number_confirmed, kind=kind,
        )  # fmt: skip
        req, created = await self.store.create_request(req)
        if not created:
            brief = await self.store.get_brief(req.id)
            if brief is not None:
                return req, brief, False
        h = self.hasher.hash(req.callee_number) if req.callee_number else None
        brief = build_brief(
            req,
            draft,
            number_hash=h,
            relationship=relationship,
            user_display_name=user_display_name,
        )
        await self.store.save_brief(brief)
        return req, brief, created
