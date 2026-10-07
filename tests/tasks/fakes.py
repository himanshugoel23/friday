"""In-memory fakes for engine tests: repositories, brain, call runner, notifier.
No DB, no network, no other engineer's package."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from friday.core.clock import FakeClock
from friday.core.models import (
    AuditEntry,
    AutonomySetting,
    BriefTemplate,
    Business,
    CallBrief,
    CallOutcome,
    CallResult,
    DialStatus,
    Fact,
    FanOutPolicy,
    MidCallQuestion,
    Nudge,
    NudgeDecision,
    NudgeFeedback,
    NudgeStatus,
    OutboundMessage,
    Person,
    Place,
    Profile,
    Quote,
    QuoteComparison,
    SendReceipt,
    ShortlistItem,
    Task,
    TaskResult,
    TaskStatus,
    TemplateRef,
    Urgency,
    User,
    UserAnswer,
    VendorInteraction,
)


def _copy(m):
    return m.model_copy(deep=True)


class TaskRepo:
    def __init__(self) -> None:
        self.items: dict[str, Task] = {}
        self.calls: list[CallResult] = []
        self.questions: dict[str, MidCallQuestion] = {}
        self.answers: dict[str, UserAnswer] = {}
        self.hotel_bookings: list = []

    async def get(self, task_id):
        t = self.items.get(task_id)
        return _copy(t) if t else None

    async def add(self, task):
        self.items[task.id] = _copy(task)
        return _copy(task)

    async def save(self, task):
        self.items[task.id] = _copy(task)
        return _copy(task)

    async def set_status(self, task_id, status):
        self.items[task_id].status = status
        return _copy(self.items[task_id])

    async def list_for_user(self, user_id, *, open_only=False):
        return [
            _copy(t)
            for t in self.items.values()
            if t.requester_user_id == user_id and not (open_only and t.status.is_terminal)
        ]

    async def list_children(self, parent_task_id):
        return sorted(
            (_copy(t) for t in self.items.values() if t.parent_task_id == parent_task_id),
            key=lambda t: t.created_at,
        )

    async def list_due(self, now):
        return [
            _copy(t)
            for t in self.items.values()
            if t.status == TaskStatus.SCHEDULED and t.next_attempt_at and t.next_attempt_at <= now
        ]

    async def save_call(self, result):
        self.calls.append(_copy(result))

    async def add_question(self, q):
        self.questions[q.id] = _copy(q)
        return q

    async def get_question(self, qid):
        return self.questions.get(qid)

    async def answer_question(self, answer):
        self.answers[answer.question_id] = answer
        return True

    async def save_hotel_booking(self, booking, *, user_id):
        self.hotel_bookings.append(booking)
        return booking

    # helpers
    def by_type(self, t):
        return [x for x in self.items.values() if x.type == t]


class KeyRepo:
    def __init__(self, key: str = "id") -> None:
        self.items: dict[str, Any] = {}
        self.key = key

    async def get(self, k):
        v = self.items.get(k)
        return _copy(v) if v else None

    async def add(self, v):
        self.items[getattr(v, self.key)] = _copy(v)
        return v

    async def save(self, v):
        return await self.add(v)

    async def upsert(self, v):
        return await self.add(v)


class UserRepo(KeyRepo):
    async def get_by_phone(self, phone):
        return next((_copy(u) for u in self.items.values() if u.phone == phone), None)

    async def list_active(self):
        return [_copy(u) for u in self.items.values()]


class ProfileRepo(KeyRepo):
    def __init__(self):
        super().__init__("user_id")


class OwnerRepo(KeyRepo):
    async def list_for_owner(self, owner_user_id):
        return [_copy(v) for v in self.items.values() if v.owner_user_id == owner_user_id]


class BusinessRepo(KeyRepo):
    def __init__(self):
        super().__init__()
        self.interactions_: list[VendorInteraction] = []

    async def get_by_phone(self, phone):
        return next((_copy(b) for b in self.items.values() if b.phone == phone), None)

    async def upsert(self, b: Business):
        existing = await self.get_by_phone(b.phone)
        if existing and existing.id != b.id:
            b = b.model_copy(update={"id": existing.id})
        self.items[b.id] = _copy(b)
        return _copy(b)

    async def add_interaction(self, i):
        self.interactions_.append(i)
        return i

    async def interactions(self, user_id, *, business_id=None, limit=50):
        out = [
            i
            for i in self.interactions_
            if i.user_id == user_id and (business_id is None or i.business_id == business_id)
        ]
        return out[-limit:][::-1]

    async def known_for_user(self, user_id, *, limit=30):
        ids = {i.business_id for i in self.interactions_ if i.user_id == user_id}
        return [_copy(self.items[i]) for i in ids if i in self.items]

    def kinds(self):
        return [i.kind for i in self.interactions_]


class UserListRepo:
    def __init__(self):
        self.items: list = []

    async def list_for_user(self, user_id):
        return [_copy(x) for x in self.items if x.user_id == user_id]

    async def upsert(self, x):
        self.items = [i for i in self.items if getattr(i, "id", None) != getattr(x, "id", 0)]
        self.items.append(_copy(x))
        return x


class AutonomyRepo:
    def __init__(self):
        self.items: dict[tuple[str, str], AutonomySetting] = {}

    async def list_for_user(self, user_id):
        return [_copy(s) for (u, _), s in self.items.items() if u == user_id]

    async def upsert(self, s):
        self.items[(s.user_id, s.category)] = _copy(s)
        return s


class NudgeRepo:
    def __init__(self):
        self.items: dict[str, Nudge] = {}
        self.feedback: list[NudgeFeedback] = []

    async def add(self, n):
        self.items[n.id] = _copy(n)
        return n

    async def save(self, n):
        self.items[n.id] = _copy(n)
        return n

    async def get(self, nid):
        n = self.items.get(nid)
        return _copy(n) if n else None

    async def exists(self, user_id, dedupe_key):
        return any(n.user_id == user_id and n.dedupe_key == dedupe_key for n in self.items.values())

    async def count_sent_between(self, user_id, start, end):
        return sum(
            1
            for n in self.items.values()
            if n.user_id == user_id and n.sent_at and start <= n.sent_at < end
        )

    async def list_for_user(self, user_id, *, kind=None, status=None, limit=50):
        out = [
            _copy(n)
            for n in self.items.values()
            if n.user_id == user_id
            and (kind is None or n.kind == kind)
            and (status is None or n.status == status)
        ]
        return sorted(out, key=lambda n: n.created_at, reverse=True)[:limit]

    async def list_scheduled_due(self, now):
        return [
            _copy(n)
            for n in self.items.values()
            if n.status == NudgeStatus.SCHEDULED and n.scheduled_for and n.scheduled_for <= now
        ]

    async def list_sent_unanswered_before(self, cutoff):
        return [
            _copy(n)
            for n in self.items.values()
            if n.status == NudgeStatus.SENT and n.responded_at is None and n.sent_at < cutoff
        ]

    async def add_feedback(self, f):
        self.feedback.append(f)
        return f

    def by_status(self, status):
        return [n for n in self.items.values() if n.status == status]


class AuditRepo:
    def __init__(self):
        self.entries: list[AuditEntry] = []

    async def add(self, e):
        self.entries.append(e)
        return e

    def actions(self):
        return [e.action for e in self.entries]


class CostRepo:
    def __init__(self):
        self.records: list = []

    async def record(self, user_id, amount, **kw):
        self.records.append((user_id, amount, kw))


class Repos:
    def __init__(self):
        self.tasks = TaskRepo()
        self.users = UserRepo()
        self.profiles = ProfileRepo()
        self.people = OwnerRepo()
        self.places = OwnerRepo()
        self.businesses = BusinessRepo()
        self.identifiers = UserListRepo()
        self.facts = UserListRepo()
        self.nudges = NudgeRepo()
        self.autonomy = AutonomyRepo()
        self.audit = AuditRepo()
        self.costs = CostRepo()


# ====================================================================== brain


class FakeBrain:
    """Deterministic brain: briefs straight from the task, summaries from the result."""

    def __init__(self) -> None:
        self.briefs: list[CallBrief] = []
        self.inject_delegation = False  # simulate a brain that tries to grant authority
        self.fan_out: FanOutPolicy | None = None
        self.decisions: dict[str, NudgeDecision] = {}  # nudge kind -> decision
        self.judged: list = []

    def template_for(self, task_type):
        return BriefTemplate(task_type=task_type, goal_template="{goal}", fan_out=self.fan_out or FanOutPolicy())

    async def build_call_brief(self, ctx, task: Task) -> CallBrief:
        from friday.core.models import ContactTarget, Delegation, TargetKind

        brief = CallBrief(
            task_id=task.id,
            requester_user_id=task.requester_user_id,
            task_type=task.type,
            goal=task.spec.goal,
            target=task.target
            or ContactTarget(kind=TargetKind.BUSINESS, name="?", phone="+910000000000"),
            on_behalf_of=ctx.profile.name or "Rahul",
            delegation=Delegation(granted=True) if self.inject_delegation else Delegation(),
            approved_terms="brain-made-up" if self.inject_delegation else None,
        )
        self.briefs.append(brief)
        return brief

    async def summarize_call(self, ctx, task, result: CallResult) -> TaskResult:
        c = result.collected
        return TaskResult(
            success=result.outcome == CallOutcome.SUCCESS,
            summary=c.get("summary", f"{task.target.name if task.target else ''}: {result.outcome.value}"),
            details={k: v for k, v in c.items() if k in ("time", "price", "reference")},
            quotes=result.quotes,
            care=result.care,
            alert=c.get("alert"),
            business_touch=TemplateRef(key="business_booking_confirmed", params=["x"])
            if result.outcome == CallOutcome.SUCCESS
            else None,
        )

    async def shortlist(self, ctx, spec, candidates, n):
        ranked = sorted(candidates, key=lambda c: (-(c.rating or 0), c.name))[:n]
        return [ShortlistItem(candidate=c, rank=i + 1, reason=f"{c.rating}★") for i, c in enumerate(ranked)]

    async def compare_quotes(self, ctx, parent, quotes):
        ranked = sorted(quotes, key=lambda q: q.amount_inr or 10**9)
        return QuoteComparison(
            summary="Comparison: " + ", ".join(f"{q.business_name} ₹{q.amount_inr}" for q in ranked),
            ranked_quotes=ranked,
            recommended_index=0,
        )

    async def judge_nudge(self, ctx, candidate):
        self.judged.append(candidate)
        if candidate.kind.value in self.decisions:
            return self.decisions[candidate.kind.value]
        return NudgeDecision(send=True, text=f"Nudge: {candidate.reason}", reason="ok")


# ====================================================================== runner

Script = Callable[[CallBrief, Any, Any], Awaitable[CallResult]]


def result(brief: CallBrief, outcome: CallOutcome, **kw) -> CallResult:
    dial = {
        CallOutcome.BUSY: DialStatus.BUSY,
        CallOutcome.NO_ANSWER: DialStatus.NO_ANSWER,
        CallOutcome.VOICEMAIL: DialStatus.VOICEMAIL,
    }.get(outcome, DialStatus.ANSWERED)
    return CallResult(
        task_id=brief.task_id,
        provider="stub",
        to_phone=brief.target.phone,
        dial_status=dial,
        outcome=outcome,
        cost_inr_est=2.5,
        **kw,
    )


def quote(name: str, amount: int, slots=("Sat 4pm",), **kw) -> Quote:
    return Quote(business_name=name, amount_inr=amount, price_text=f"₹{amount}", available_slots=list(slots), **kw)


def offer_then_confirm(name: str, amount: int, slots=("4pm", "6pm")) -> Script:
    """Default founder flow: offer -> PENDING_APPROVAL; with approved_terms -> SUCCESS."""

    async def script(brief, ask_user, notify):
        if brief.can_commit([]):
            return result(brief, CallOutcome.SUCCESS, quotes=[quote(name, amount, slots)],
                          collected={"summary": f"Booked {name} {brief.approved_terms}", "time": slots[0]})
        return result(brief, CallOutcome.PENDING_APPROVAL, quotes=[quote(name, amount, slots)],
                      collected={"summary": f"{name} has {' or '.join(slots)}, ₹{amount}"})

    return script


def outcome(o: CallOutcome, **kw) -> Script:
    async def script(brief, ask_user, notify):
        return result(brief, o, **kw)

    return script


class StubRunner:
    """CallSessionRunner stub: per-phone scripts consumed in order (last one repeats)."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.scripts: dict[str, list[Script]] = {}
        self.default: Script = outcome(CallOutcome.SUCCESS)
        self.briefs: list[CallBrief] = []
        self.inbound: list[tuple[Any, CallBrief]] = []
        self.gate: asyncio.Event | None = None  # block calls until set
        self.active = 0
        self.max_active = 0

    def script(self, phone: str, *scripts: Script) -> None:
        self.scripts.setdefault(phone, []).extend(scripts)

    async def _do(self, brief, ask_user, notify):
        self.briefs.append(brief)
        queue = self.scripts.get(brief.target.phone)
        fn = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else self.default
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            return await fn(brief, ask_user, notify)
        finally:
            self.active -= 1

    async def run(self, brief, ask_user, notify_user=None):
        return await self._do(brief, ask_user, notify_user)

    async def run_inbound(self, leg, brief, ask_user, notify_user=None):
        self.inbound.append((leg, brief))
        r = await self._do(brief, ask_user, notify_user)
        return r.model_copy(update={"direction": "inbound"})

    def phones(self):
        return [b.target.phone for b in self.briefs]


# ====================================================================== channels


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[OutboundMessage, Urgency]] = []

    async def send(self, msg: OutboundMessage, *, urgency: Urgency = Urgency.NORMAL) -> SendReceipt:
        self.sent.append((msg, urgency))
        return SendReceipt(message_id=msg.id)

    def texts(self, user_id: str | None = None) -> list[str]:
        return [m.text or "" for m, _ in self.sent if user_id is None or m.user_id == user_id]

    def to_business(self):
        return [m for m, _ in self.sent if m.business_id or (m.template and not m.user_id)]

    def last(self) -> OutboundMessage:
        return self.sent[-1][0]


__all__ = [
    "AutonomySetting",
    "Fact",
    "FakeBrain",
    "Person",
    "Place",
    "Profile",
    "RecordingNotifier",
    "Repos",
    "StubRunner",
    "User",
    "datetime",
]
