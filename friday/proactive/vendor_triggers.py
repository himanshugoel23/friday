"""Vendor-lifecycle nudges (phase 1: vendor calling must be proactive end to end).

All of them come from what the user did with Friday (their own requests and bookings, as Tasks):

* ``category_cadence``: a vendor visit Friday booked is due again (haircut ~4 weeks, car service
  ~6 months, pest control ~3 months, vet ~1 year) -> "book the usual?"
* ``open_quotes``: quotes came back 20-48 h ago and the user booked nothing in that category.
* ``unanswered_vendors``: vendors did not pick up and no quote exists for that request.

Pure functions over tasks (like triggers.py); the engine adds the guardrails, the daily cap of 3 /
morning digest rule, quiet hours and the judge.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import ist_date
from friday.core.models import (
    AutonomyCategory,
    CallOutcome,
    NudgeCandidate,
    NudgeKind,
    Task,
    TaskStatus,
    TaskType,
)
from friday.tasks.engine import ROLE_VENDOR_QUOTE
from friday.vendors.packs import pack_for

# days until the same service is due again (only where a regular cycle is real)
CADENCE_DAYS: dict[str, int] = {
    "salon": 28, "car_service": 180, "pest_control": 90, "vet_pet": 365, "laundry_tailor": 0,
}
CADENCE_WINDOW = timedelta(days=7)
QUOTE_FOLLOWUP_AFTER = timedelta(hours=20)
QUOTE_FOLLOWUP_UNTIL = timedelta(hours=48)


def _cat(t: Task) -> str | None:
    pack = pack_for(t.spec.category) or pack_for(t.spec.goal)
    return pack.key if pack else None


def _when(t: Task) -> datetime:
    appt = t.result.appointment_at if t.result else None
    return appt or t.created_at


def _booked(t: Task) -> bool:
    return (
        t.status == TaskStatus.COMPLETED
        and t.type == TaskType.BOOKING
        and t.last_outcome == CallOutcome.SUCCESS
        and bool(t.result and t.result.success)
        and (t.delegation.granted or t.role != ROLE_VENDOR_QUOTE)
    )


def category_cadence(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    by_cat: dict[str, list[Task]] = {}
    for t in tasks:
        cat = _cat(t)
        if cat and CADENCE_DAYS.get(cat) and _booked(t) and t.parent_task_id is None:
            by_cat.setdefault(cat, []).append(t)
    out = []
    for cat, items in by_cat.items():
        if len(items) != 1:
            continue  # two or more repeats: the learned pattern trigger owns it
        last = items[0]
        due = _when(last) + timedelta(days=CADENCE_DAYS[cat])
        if due <= now <= due + CADENCE_WINDOW:
            where = last.target.name if last.target else cat
            out.append(NudgeCandidate(
                user_id=user_id, kind=NudgeKind.PATTERN, category=AutonomyCategory.ROUTINES,
                reason=f"{CADENCE_DAYS[cat] // 7 or 1} weeks since {last.spec.goal} ({where})"
                if CADENCE_DAYS[cat] < 100 else f"{last.spec.goal} ({where}) is due again",
                due_at=due, task_id=last.id, person_id=last.beneficiary.person_id,
                dedupe_key=f"cadence:{cat}:{ist_date(_when(last))}",
                data={"proposed_from_task": last.id, "expires_at": due + CADENCE_WINDOW},
            ))
    return out


def _quote_tasks(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if t.role == ROLE_VENDOR_QUOTE and not t.delegation.granted]


def open_quotes(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    out = []
    groups: dict[str, list[Task]] = {}
    for t in _quote_tasks(tasks):
        cat = _cat(t)
        in_window = QUOTE_FOLLOWUP_AFTER <= now - t.created_at <= QUOTE_FOLLOWUP_UNTIL
        if cat and in_window and t.last_outcome in (CallOutcome.SUCCESS, CallOutcome.PARTIAL):
            groups.setdefault(cat, []).append(t)
    for cat, items in groups.items():
        first = min(t.created_at for t in items)
        if any(_booked(t) and t.created_at >= first for t in tasks if _cat(t) == cat):
            continue
        out.append(NudgeCandidate(
            user_id=user_id, kind=NudgeKind.FOLLOW_UP, category=AutonomyCategory.FOLLOW_UPS,
            reason=f"{len(items)} {cat.replace('_', ' ')} quotes are still waiting for your pick",
            due_at=first + QUOTE_FOLLOWUP_AFTER, task_id=items[0].id,
            dedupe_key=f"openquotes:{cat}:{ist_date(first)}",
            data={"expires_at": first + QUOTE_FOLLOWUP_UNTIL},
        ))
    return out


def unanswered_vendors(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    out = []
    groups: dict[str, list[Task]] = {}
    for t in _quote_tasks(tasks):
        cat = _cat(t)
        if cat and QUOTE_FOLLOWUP_AFTER <= now - t.created_at <= QUOTE_FOLLOWUP_UNTIL:
            groups.setdefault(cat, []).append(t)
    for cat, items in groups.items():
        quoted = any(t.last_outcome in (CallOutcome.SUCCESS, CallOutcome.PARTIAL) for t in items)
        missed = [t for t in items if t.last_outcome in (
            CallOutcome.NO_ANSWER, CallOutcome.BUSY, CallOutcome.VOICEMAIL)]
        if quoted or not missed:
            continue
        first = min(t.created_at for t in items)
        out.append(NudgeCandidate(
            user_id=user_id, kind=NudgeKind.FOLLOW_UP, category=AutonomyCategory.FOLLOW_UPS,
            reason=f"{len(missed)} {cat.replace('_', ' ')} vendors did not pick up; retry?",
            due_at=first + QUOTE_FOLLOWUP_AFTER, task_id=missed[0].id,
            dedupe_key=f"unanswered:{cat}:{ist_date(first)}",
            data={"expires_at": first + QUOTE_FOLLOWUP_UNTIL},
        ))
    return out
