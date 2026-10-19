"""Event-aware proactive messages: speak first at the right moment, without nagging.

Planned from the life state:
  * ``after_event``  30-45 minutes after an interview/meeting/appointment ends
                     ("Interview kaisa gaya?")
  * ``before_event`` a reminder before it starts, with a travel-buffer hook
                     ("1:15 tak nikalna hoga")
  * ``bill_due``     two days before a bill is due (pay link when the bills module has one)
  * ``commitment``   when something the user asked to be reminded of is due (also repeating)
  * ``morning_brief`` one digest in the morning (skipped entirely when there is nothing to say)

Rules enforced here, in this order, for every message:
  1. already handled (dedupe key in the log)        -> never twice
  2. not due yet / stale                            -> wait / drop
  3. topic muted by the user ("mat poocho")         -> never
  4. PROTECTED event running                        -> held until it ends
  5. existing guardrails (``friday.proactive.guardrails.evaluate``): quiet hours, the daily cap
     (3 a day, extras go to the next morning brief), ignore-learning
  6. channel: text unless the user opted in to a voice note / call for THAT topic
Every text comes from ``copy.py`` and carries a one-clause reason. Event titles from calendars are
never put in a message (only the kind), so an invite cannot inject text into what we send.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from friday.core.clock import Clock, at_ist, ist_day_bounds, to_ist
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import AutonomyCategory, NudgeCandidate, NudgeKind, Urgency
from friday.lifestate import copy
from friday.lifestate.capture import TASK_REQUEST, capture_message
from friday.lifestate.models import (
    MAX_NOTE,
    CommitmentStatus,
    EventKind,
    EventStatus,
    Followup,
    LifeCommitment,
    LifeEvent,
    TopicPref,
    aware,
    clean_text,
    display_title,
)
from friday.lifestate.now import busy_until
from friday.lifestate.ports import BillRef, BillsPort, Sender, TravelBufferHook
from friday.lifestate.recur import next_occurrence, occurrences_between
from friday.lifestate.store import LifeStore
from friday.proactive.guardrails import evaluate

log = get_logger(__name__)

TOPICS = ("after_event", "before_event", "bill_due", "commitment", "morning_brief")
REMINDER_TOPICS = ("before_event", "bill_due", "commitment")

AFTER_DELAY: dict[EventKind, timedelta] = {
    EventKind.INTERVIEW: timedelta(minutes=40),
    EventKind.MEETING: timedelta(minutes=20),
    EventKind.APPOINTMENT: timedelta(minutes=30),
    EventKind.TRAVEL: timedelta(minutes=15),
}
BEFORE_LEAD: dict[EventKind, timedelta] = {
    EventKind.INTERVIEW: timedelta(minutes=90),
    EventKind.MEETING: timedelta(minutes=30),
    EventKind.APPOINTMENT: timedelta(minutes=60),
    EventKind.TRAVEL: timedelta(minutes=120),
}
TRAVEL_SLACK = timedelta(minutes=30)  # remind this long before the time you must leave
AFTER_STALE = timedelta(hours=6)  # a "how did it go" after 6 hours is no longer natural
BILL_LEAD_DAYS = 2
BILL_NUDGE_HOUR = 10
COMMITMENT_STALE = timedelta(hours=3)
IGNORED_AFTER = timedelta(hours=24)
BRIEF_MAX_LINES = 6
BRIEF_HOUR = 8


# --------------------------------------------------------------------------- planning (pure)
@dataclass(frozen=True)
class Planned:
    key: str
    topic: str  # e.g. "after_event:interview"
    due_at: datetime
    expires_at: datetime
    kind: EventKind | None = None
    event_id: str | None = None
    subject_start: datetime | None = None
    subject_end: datetime | None = None
    leave_by: datetime | None = None
    text_arg: str | None = None  # commitment text (the user's own words)
    bill: BillRef | None = None
    booking: bool = False
    urgency: Urgency = Urgency.NORMAL

    @property
    def base_topic(self) -> str:
        return self.topic.split(":")[0]


def plan_followups(
    events: Sequence[LifeEvent],
    commitments: Sequence[LifeCommitment],
    now: datetime,
    *,
    travel_minutes: dict[str, int] | None = None,
    bills: Sequence[BillRef] = (),
) -> list[Planned]:
    """Everything that could be said about the user's day, with when and until when."""
    now = aware(now)
    travel_minutes = travel_minutes or {}
    out: list[Planned] = []
    for e in events:
        if e.status != EventStatus.ACTIVE:
            continue
        ts = int(e.start.timestamp())
        if e.kind in AFTER_DELAY and e.end > e.start:
            due = e.end + AFTER_DELAY[e.kind]
            out.append(
                Planned(
                    key=f"after:{e.id}:{ts}",
                    topic=f"after_event:{e.kind.value}",
                    due_at=due,
                    expires_at=due + AFTER_STALE,
                    kind=e.kind,
                    event_id=e.id,
                    subject_start=e.start,
                    subject_end=e.end,
                )
            )
        if e.kind in BEFORE_LEAD and e.start > now:
            mins = travel_minutes.get(e.id)
            leave_by = e.start - timedelta(minutes=mins) if mins else None
            due = (leave_by - TRAVEL_SLACK) if leave_by else e.start - BEFORE_LEAD[e.kind]
            out.append(
                Planned(
                    key=f"before:{e.id}:{ts}",
                    topic=f"before_event:{e.kind.value}",
                    due_at=due,
                    expires_at=e.start - timedelta(minutes=5),
                    kind=e.kind,
                    event_id=e.id,
                    subject_start=e.start,
                    subject_end=e.end,
                    leave_by=leave_by,
                    booking=e.source.value == "booking",
                )
            )
        if e.kind == EventKind.BILL_DUE:
            d = to_ist(e.start).date()
            out.append(
                Planned(
                    key=f"bill:{e.id}:{ts}",
                    topic="bill_due",
                    due_at=at_ist(d - timedelta(days=BILL_LEAD_DAYS), BILL_NUDGE_HOUR),
                    expires_at=at_ist(d + timedelta(days=1), 0),
                    kind=e.kind,
                    event_id=e.id,
                    subject_start=e.start,
                )
            )
    known_bill_days = {to_ist(e.start).date() for e in events if e.kind == EventKind.BILL_DUE}
    for b in bills:  # W3 bills not mirrored as events
        if b.due_on in known_bill_days:
            continue
        out.append(
            Planned(
                key=f"billref:{b.id}:{b.due_on.isoformat()}",
                topic="bill_due",
                due_at=at_ist(b.due_on - timedelta(days=BILL_LEAD_DAYS), BILL_NUDGE_HOUR),
                expires_at=at_ist(b.due_on + timedelta(days=1), 0),
                kind=EventKind.BILL_DUE,
                subject_start=at_ist(b.due_on, 9),
                bill=b,
            )
        )
    for c in commitments:
        if c.status != CommitmentStatus.OPEN:
            continue
        dues = (
            occurrences_between(c.repeat, now - timedelta(hours=3), now + timedelta(days=1))
            if c.repeat
            else [c.due]
        )
        for d in dues:
            out.append(
                Planned(
                    key=f"commit:{c.id}:{int(d.timestamp())}",
                    topic="commitment",
                    due_at=d,
                    expires_at=d + COMMITMENT_STALE,
                    event_id=None,
                    text_arg=c.text,
                    subject_start=d,
                )
            )
    return sorted(out, key=lambda p: p.due_at)


def topic_candidates(topic: str) -> list[str]:
    """Pref keys that govern ``topic``: itself, its base, the reminders group, and "all"."""
    base = topic.split(":")[0]
    keys = [topic, base]
    if base in REMINDER_TOPICS:
        keys.append("reminders")
    keys.append("all")
    return list(dict.fromkeys(keys))


def is_muted(prefs: Sequence[TopicPref], topic: str) -> bool:
    keys = set(topic_candidates(topic))
    return any(p.muted and p.topic in keys for p in prefs)


def channel_for(prefs: Sequence[TopicPref], topic: str) -> str:
    """Text unless the user opted in to something else for this topic (most specific wins)."""
    by_topic = {p.topic: p for p in prefs}
    for key in topic_candidates(topic):
        p = by_topic.get(key)
        if p is not None and p.channel != "text":
            return p.channel
    return "text"


# --------------------------------------------------------------------------- rendering
def render(p: Planned, now: datetime) -> str:
    if p.base_topic == "after_event":
        assert p.kind is not None and p.subject_end is not None
        return copy.after_event(p.kind, p.subject_end)
    if p.base_topic == "before_event":
        assert p.kind is not None and p.subject_start is not None
        return copy.before_event(p.kind, p.subject_start, p.leave_by)
    if p.base_topic == "bill_due":
        due = p.subject_start or p.due_at
        days = (to_ist(due).date() - to_ist(now).date()).days
        return copy.bill_due(days, due, now, p.bill.pay_link if p.bill else None)
    return copy.commitment_due(p.text_arg or "")


def why_of(p: Planned) -> str:
    """The reason clause on its own (also stored as the candidate's reason)."""
    if p.base_topic == "after_event" and p.kind and p.subject_end:
        return copy.why_after_event(p.kind, p.subject_end)
    if p.base_topic == "before_event" and p.kind and p.subject_start:
        return copy.why_before_event(p.kind, p.subject_start)
    if p.base_topic == "bill_due":
        return copy.why_bill(p.subject_start or p.due_at)
    return copy.why_commitment()


def _nudge_kind(p: Planned) -> tuple[NudgeKind, AutonomyCategory]:
    if p.base_topic == "after_event":
        return NudgeKind.FOLLOW_UP, AutonomyCategory.FOLLOW_UPS
    if p.base_topic == "before_event":
        kind = NudgeKind.TASK_REMINDER if p.booking else NudgeKind.DATE_BASED
        return kind, AutonomyCategory.REMINDERS
    return NudgeKind.DATE_BASED, AutonomyCategory.REMINDERS


# --------------------------------------------------------------------------- results
Action = Literal[
    "sent", "deferred", "held_quiet", "digest", "muted", "expired", "suppressed", "failed"
]


@dataclass
class Outcome:
    key: str
    topic: str
    action: Action
    text: str | None = None
    release_at: datetime | None = None
    reason: str = ""
    channel: str = "text"


@dataclass
class Brief:
    text: str | None
    lines: list[str] = field(default_factory=list)
    suggestion: str | None = None
    more: int = 0


# --------------------------------------------------------------------------- repeats
async def roll_repeats(store: LifeStore, user_id: str, now: datetime) -> int:
    """Events with a repeat rule (a monthly bill) get their next occurrence once they are over."""
    now = aware(now)
    made = 0
    for e in await store.events_between(user_id, now - timedelta(days=40), now):
        if e.repeat is None or e.status != EventStatus.ACTIVE or e.end >= now:
            continue
        nxt = next_occurrence(e.repeat, e.start, anchor=to_ist(e.start).date())
        if nxt is None:
            continue
        nxt_event = e.model_copy(
            update={
                "id": LifeEvent(user_id=user_id, title="x", start=now, end=now).id,
                "start": nxt,
                "end": nxt + (e.end - e.start),
                "repeat": e.repeat,
                "note": None,
                "source_ref": None,
            }
        )
        e.repeat = None
        await store.save_event(e)
        await store.save_event(nxt_event)
        made += 1
    return made


# --------------------------------------------------------------------------- scheduler
class FollowupScheduler:
    def __init__(
        self,
        store: LifeStore,
        sender: Sender,
        settings: Settings,
        clock: Clock,
        *,
        bills: BillsPort | None = None,
        travel: TravelBufferHook | None = None,
        extra_sent_today: Callable[[str], Awaitable[int]] | None = None,
    ) -> None:
        """``extra_sent_today(user_id)`` adds messages sent by the other proactive triggers, so the
        daily cap (3) is shared with them."""
        self.store, self.sender, self.settings, self.clock = store, sender, settings, clock
        self.bills, self.travel, self.extra_sent_today = bills, travel, extra_sent_today

    # ------------------------------------------------------------------ one user, one pass
    async def run_user(self, user_id: str) -> list[Outcome]:
        now = self.clock.now()
        await roll_repeats(self.store, user_id, now)
        events = await self.store.events_between(
            user_id, now - timedelta(hours=14), now + timedelta(days=3)
        )
        commitments = await self.store.list_commitments(user_id, status="open")
        prefs = await self.store.list_topics(user_id)
        refs = await self.bills.pending_bills(user_id, now) if self.bills else []
        travel_minutes: dict[str, int] = {}
        if self.travel:
            for e in events:
                if e.location and e.start > now:
                    mins = await self.travel.minutes_needed(e)
                    if mins:
                        travel_minutes[e.id] = mins
        plan = plan_followups(events, commitments, now, travel_minutes=travel_minutes, bills=refs)
        out: list[Outcome] = []
        for p in plan:
            if p.due_at > now or await self.store.get_followup(user_id, p.key):
                continue
            res = await self._consider(user_id, p, now, events, prefs)
            if res is not None:
                out.append(res)
        return out

    async def run_all(self, user_ids: Sequence[str]) -> dict[str, list[Outcome]]:
        return {u: await self.run_user(u) for u in user_ids}

    async def _record(
        self,
        user_id: str,
        p: Planned,
        status: str,
        now: datetime,
        text: str | None = None,
        sent: bool = False,
    ) -> None:
        await self.store.save_followup(
            Followup(
                user_id=user_id,
                key=p.key,
                topic=p.topic,
                event_id=p.event_id,
                status=status,  # type: ignore[arg-type]
                text=text,
                due_at=p.due_at,
                sent_at=now if sent else None,
                created_at=now,
            )
        )

    async def _consider(
        self,
        user_id: str,
        p: Planned,
        now: datetime,
        events: list[LifeEvent],
        prefs: list[TopicPref],
    ) -> Outcome | None:
        if now >= p.expires_at:
            await self._record(user_id, p, "expired", now)
            return Outcome(p.key, p.topic, "expired", reason="stale")
        if is_muted(prefs, p.topic):
            await self._record(user_id, p, "muted", now)
            return Outcome(p.key, p.topic, "muted", reason="topic muted by the user")
        end = busy_until(events, now, protected_only=True)
        if end is not None and p.urgency != Urgency.URGENT:
            return Outcome(
                p.key, p.topic, "deferred", release_at=end, reason="protected event running"
            )
        cand_kind, category = _nudge_kind(p)
        cand = NudgeCandidate(
            user_id=user_id,
            kind=cand_kind,
            category=category,
            urgency=p.urgency,
            reason=why_of(p),
            due_at=p.due_at,
            dedupe_key=p.key,
            data={"expires_at": p.expires_at},
        )
        streak, last_ignored, last_sent = await self._ignore_state(user_id, p.base_topic, now)
        verdict = evaluate(
            cand,
            now=now,
            settings=self.settings,
            sent_today=await self._sent_today(user_id, now),
            ignore_streak=streak,
            last_ignored_at=last_ignored,
            last_sent_same_kind=last_sent,
        )
        text = render(p, now)
        if verdict.action == "suppress":
            await self._record(user_id, p, "suppressed", now)
            return Outcome(p.key, p.topic, "suppressed", reason=verdict.reason)
        if verdict.action == "schedule":
            return Outcome(
                p.key, p.topic, "held_quiet", release_at=verdict.send_at, reason=verdict.reason
            )
        if verdict.action == "digest":
            await self._record(user_id, p, "digest", now, text=text)
            return Outcome(p.key, p.topic, "digest", text=text, reason=verdict.reason)
        channel = channel_for(prefs, p.topic)
        ok = await self.sender.send(user_id, text, channel=channel, dedupe_key=p.key)
        if not ok:
            return Outcome(p.key, p.topic, "failed", text=text, reason="sender refused")
        await self._record(user_id, p, "sent", now, text=text, sent=True)
        return Outcome(p.key, p.topic, "sent", text=text, channel=channel)

    async def _sent_today(self, user_id: str, now: datetime) -> int:
        start, end = ist_day_bounds(now)
        n = await self.store.count_sent_between(user_id, start, end)
        if self.extra_sent_today is not None:
            n += await self.extra_sent_today(user_id)
        return n

    async def _ignore_state(
        self, user_id: str, base_topic: str, now: datetime
    ) -> tuple[int, datetime | None, datetime | None]:
        """Consecutive messages of this topic that got no reply within 24h (newest first)."""
        sent = [
            f
            for f in await self.store.list_followups(user_id)
            if f.status == "sent" and f.sent_at and f.topic.split(":")[0] == base_topic
        ]
        sent.sort(key=lambda f: f.sent_at or now, reverse=True)
        streak, last_ignored = 0, None
        for f in sent:
            assert f.sent_at is not None
            if f.responded_at is not None:
                break
            if now - f.sent_at < IGNORED_AFTER:
                continue  # still waiting for an answer: neither ignored nor answered
            streak += 1
            last_ignored = last_ignored or f.sent_at
        return streak, last_ignored, (sent[0].sent_at if sent else None)

    # ------------------------------------------------------------------ morning brief
    async def send_morning_brief(self, user_id: str) -> Outcome | None:
        now = self.clock.now()
        local = to_ist(now)
        key = f"brief:{local.date().isoformat()}"
        if local.hour < BRIEF_HOUR or await self.store.get_followup(user_id, key):
            return None
        stub = Planned(
            key=key, topic="morning_brief", due_at=now, expires_at=now + timedelta(hours=6)
        )
        prefs = await self.store.list_topics(user_id)
        if is_muted(prefs, "morning_brief"):
            await self._record(user_id, stub, "muted", now)
            return Outcome(key, "morning_brief", "muted")
        cand = NudgeCandidate(
            user_id=user_id,
            kind=NudgeKind.MORNING_BRIEFING,
            category=AutonomyCategory.BRIEFING,
            reason=copy.why_brief(),
            due_at=now,
            dedupe_key=key,
            data={"expires_at": stub.expires_at},
        )
        verdict = evaluate(cand, now=now, settings=self.settings, briefing_hour_ist=BRIEF_HOUR)
        if verdict.action == "schedule":
            return Outcome(key, "morning_brief", "held_quiet", release_at=verdict.send_at)
        if verdict.action != "send":
            await self._record(user_id, stub, "suppressed", now)
            return Outcome(key, "morning_brief", "suppressed", reason=verdict.reason)
        held = [
            f
            for f in await self.store.list_followups(user_id)
            if f.status == "digest" and f.text and now - f.created_at < timedelta(hours=36)
        ]
        brief = await build_morning_brief(
            self.store,
            user_id,
            now,
            bills=self.bills,
            travel=self.travel,
            digest_lines=[f.text for f in held if f.text],
        )
        if brief.text is None:  # nothing to say: say nothing
            await self._record(user_id, stub, "suppressed", now)
            return Outcome(key, "morning_brief", "suppressed", reason="nothing to report")
        channel = channel_for(prefs, "morning_brief")
        if not await self.sender.send(user_id, brief.text, channel=channel, dedupe_key=key):
            return Outcome(key, "morning_brief", "failed", text=brief.text)
        await self._record(user_id, stub, "sent", now, text=brief.text, sent=True)
        for f in held:
            f.status = "digested"
            await self.store.save_followup(f)
        return Outcome(key, "morning_brief", "sent", text=brief.text, channel=channel)

    # ------------------------------------------------------------------ replies
    async def handle_reply(self, user_id: str, text: str) -> ReplyResult:
        now = self.clock.now()
        cmd = parse_mute_command(text)
        recent = await self._last_sent(user_id, now)
        if cmd is not None:
            topic = cmd.topic or (recent.topic.split(":")[0] if recent else "all")
            if cmd.action == "mute":
                await self.store.set_topic(user_id, topic, muted=True)
                if recent and not cmd.topic:
                    recent.responded_at = now
                    await self.store.save_followup(recent)
                return ReplyResult(True, copy.mute_done(topic), "mute", topic)
            if cmd.action == "unmute":
                await self.store.set_topic(user_id, topic, muted=False)
                return ReplyResult(True, copy.unmute_done(topic), "unmute", topic)
            assert cmd.channel is not None
            await self.store.set_topic(user_id, topic, muted=False, channel=cmd.channel)
            return ReplyResult(True, copy.channel_set(topic, cmd.channel), "channel", topic)
        if recent is None:
            return ReplyResult(False)
        recent.responded_at = now
        await self.store.save_followup(recent)
        if recent.topic.split(":")[0] != "after_event" or not recent.event_id:
            return ReplyResult(False)
        if TASK_REQUEST.search(text):
            return ReplyResult(False)  # a request, not an answer: let the normal handlers run
        ev = await self.store.get_event(user_id, recent.event_id)
        if ev is None:
            return ReplyResult(False)
        ev.note = clean_text(f"{ev.note} | {text}" if ev.note else text, MAX_NOTE)
        await self.store.save_event(ev)
        reply = copy.note_saved()
        cap = await capture_message(self.store, user_id, text, now)
        if cap.status == "captured" and cap.reply:
            reply += " " + cap.reply
        return ReplyResult(True, reply, "note", "after_event", event_id=ev.id)

    async def _last_sent(self, user_id: str, now: datetime) -> Followup | None:
        cands = [
            f
            for f in await self.store.list_followups(user_id)
            if f.status == "sent"
            and f.topic != "morning_brief"
            and f.responded_at is None
            and f.sent_at is not None
            and now - f.sent_at <= IGNORED_AFTER
        ]
        return max(cands, key=lambda f: f.sent_at or now, default=None)


@dataclass
class ReplyResult:
    handled: bool
    reply: str | None = None
    kind: Literal["mute", "unmute", "channel", "note"] | None = None
    topic: str | None = None
    event_id: str | None = None


# --------------------------------------------------------------------------- mute parsing
@dataclass(frozen=True)
class MuteCommand:
    action: Literal["mute", "unmute", "channel"]
    topic: str | None = None  # None: "the thing you just sent"
    channel: Literal["text", "voice_note", "call"] | None = None


_BARE = re.compile(
    r"^\s*(stop|stop it|bas|bas karo|band karo|band kar do|mat poocho|mat pucho|mat puchho|"
    r"mat poochna|mat bhejo|ye mat bhejo|yeh mat bhejo|ab mat poocho|aur mat poocho|"
    r"nahi chahiye)\s*[.!]?\s*$",
    re.I,
)
_MUTE_CUE = re.compile(
    r"\b(mat\s+(?:poocho|pucho|puchho|poochna|puchna|bhejo|bhejna|batao|dilao|yaad)|"
    r"band\s*(?:kar|karo|kardo)?|stop|rok\s*do|nahi\s+chahiye|disable|off)\b",
    re.I,
)
_UNMUTE_CUE = re.compile(
    r"\b(phir\s*se|dobara|wapas|firse|again|unmute|chalu|shuru|resume)\b", re.I
)
_VOICE = re.compile(r"\b(voice\s*-?note|vn)\b", re.I)
_CALL = re.compile(r"\b(call\s+karke|phone\s+karke|call\s+par|call\s+pe|call\s+kar\s+ke)\b", re.I)
_TEXTONLY = re.compile(r"\b(text|message|msg)\s+(?:par|pe|hi|mein|me)\b", re.I)
_KIND_WORDS = (
    ("interview", "interview"),
    ("meeting", "meeting"),
    ("appointment", "appointment"),
    ("doctor", "appointment"),
    ("dentist", "appointment"),
    ("safar", "travel"),
    ("travel", "travel"),
)


def _topic_from(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\b(sab|saare|saari|sabhi|all|everything|koi bhi|kuch bhi)\b", t):
        return "all"
    if re.search(r"\b(brief|digest|subah)\b", t):
        return "morning_brief"
    if re.search(r"\b(bill|bills)\b", t):
        return "bill_due"
    asks = re.search(r"\b(poocho|pucho|puchho|poochna|puchna|kaisa|kaise|follow\s*up)\b", t)
    remind = re.search(r"\b(reminder|reminders|yaad|alert|alerts)\b", t)
    for word, kind in _KIND_WORDS:
        if word in t:
            return f"before_event:{kind}" if remind and not asks else f"after_event:{kind}"
    if asks:
        return "after_event"
    if remind:
        return "reminders"
    return None


def parse_mute_command(text: str) -> MuteCommand | None:
    """'mat poocho', 'stop', 'interview ke baare mein mat poocho', 'bill ke reminder band karo',
    'phir se poocho', 'interview ke baad voice note bhejo'. Short messages only (<= 12 words),
    so ordinary sentences containing 'band' or 'stop' are never taken as commands."""
    t = (text or "").strip()
    if not t or len(t.split()) > 12:
        return None
    if _BARE.match(t):
        return MuteCommand("mute")
    topic = _topic_from(t)
    ch: Literal["text", "voice_note", "call"] | None = None
    if _VOICE.search(t):
        ch = "voice_note"
    elif _CALL.search(t):
        ch = "call"
    elif _TEXTONLY.search(t):
        ch = "text"
    if ch is not None and topic is not None:
        return MuteCommand("channel", topic, ch)
    if _UNMUTE_CUE.search(t) and topic is not None and not _MUTE_CUE.search(t):
        return MuteCommand("unmute", topic)
    if _MUTE_CUE.search(t) and topic is not None:
        return MuteCommand("mute", topic)
    return None


# --------------------------------------------------------------------------- morning brief
async def build_morning_brief(
    store: LifeStore,
    user_id: str,
    now: datetime,
    *,
    bills: BillsPort | None = None,
    travel: TravelBufferHook | None = None,
    max_lines: int = BRIEF_MAX_LINES,
    digest_lines: Sequence[str] = (),
) -> Brief:
    """Today's events, reminders and bills in at most ``max_lines`` lines plus one suggestion.
    Returns ``Brief(text=None)`` when there is nothing to say (the brief is then not sent)."""
    now = aware(now)
    start, end = ist_day_bounds(now)
    today: date = to_ist(now).date()
    events = [
        e
        for e in await store.events_between(user_id, start, end)
        if e.kind != EventKind.BILL_DUE and e.end > e.start
    ]
    events.sort(key=lambda e: e.start)
    lines: list[str] = []
    for e in events:
        label = e.title if e.source.value == "user" else display_title(e)
        lines.append(copy.brief_event_line(e.kind, label, e.start))

    for c in await store.list_commitments(user_id, status="open"):
        dues = (
            occurrences_between(c.repeat, start - timedelta(seconds=1), end)
            if c.repeat
            else [c.due]
        )
        for d in dues:
            if start <= d < end:
                lines.append(copy.brief_commitment_line(c.text, d))

    week = await store.events_between(user_id, start, start + timedelta(days=BILL_LEAD_DAYS + 1))
    seen_days: set[date] = set()
    for b in sorted((e for e in week if e.kind == EventKind.BILL_DUE), key=lambda e: e.start):
        d = to_ist(b.start).date()
        seen_days.add(d)
        lines.append(copy.brief_bill_line((d - today).days))
    if bills is not None:
        for ref in await bills.pending_bills(user_id, now):
            if ref.due_on in seen_days or (ref.due_on - today).days > BILL_LEAD_DAYS:
                continue
            lines.append(copy.brief_bill_line((ref.due_on - today).days))
    lines.extend(digest_lines)

    if not lines:
        return Brief(text=None)
    suggestion = await _suggest(events, today, now, travel, any("bill aaj" in ln for ln in lines))
    shown = lines[:max_lines]
    more = len(lines) - len(shown)
    return Brief(
        text=copy.brief(shown, suggestion, more), lines=shown, suggestion=suggestion, more=more
    )


async def _suggest(
    events: list[LifeEvent],
    today: date,
    now: datetime,
    travel: TravelBufferHook | None,
    bill_today: bool,
) -> str | None:
    busy = [e for e in events if e.end > e.start]
    for a, b in zip(busy, busy[1:], strict=False):
        if b.start < a.end:
            return copy.suggest_clash()
    if travel is not None:
        for e in busy:
            if e.protected and e.location and e.start > now:
                mins = await travel.minutes_needed(e)
                if mins:
                    return copy.suggest_leave(e.start, e.start - timedelta(minutes=mins))
    if bill_today:
        return copy.suggest_bill()
    return None


# --------------------------------------------------------------------------- notifier adapter
class NotifierSender:
    """Sends proactive text through ``friday.channels.notifier.Notifier.notify_user``.

    Voice notes and calls are NOT implemented yet: a topic that opted in to them falls back to
    text (never the other way round: nothing is ever sent as a call without the opt-in)."""

    def __init__(self, notifier: object) -> None:
        self._n = notifier

    async def send(
        self, user_id: str, text: str, *, channel: str = "text", dedupe_key: str | None = None
    ) -> bool:
        receipt = await self._n.notify_user(user_id, text)  # type: ignore[attr-defined]
        return bool(getattr(receipt, "ok", False))
