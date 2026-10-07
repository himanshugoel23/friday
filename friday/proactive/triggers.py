"""Proactive triggers (ARCHITECTURE §3.6). Pure functions: snapshot in, candidates out.

Every candidate carries a stable ``dedupe_key`` (one nudge per key, ever) and, where it
can go stale, ``data["expires_at"]``.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from friday.core.clock import at_ist, ist_date, to_ist
from friday.core.config import Settings
from friday.core.models import (
    AutonomyCategory,
    CallOutcome,
    Fact,
    FactKind,
    NudgeCandidate,
    NudgeKind,
    Profile,
    Task,
    TaskStatus,
    TaskType,
    Urgency,
)
from friday.tasks.categories import category_for

URGENT_REMINDER_WINDOW = timedelta(hours=2)  # PRD US-10.2: reminder <2h away is urgent
FOLLOW_UP_STALE = timedelta(hours=48)
PATTERN_SLACK = timedelta(days=3)
_BOOKINGISH = {
    TaskType.BOOKING,
    TaskType.HEALTHCARE,
    TaskType.ORDER,
    TaskType.SERVICE_COORDINATION,
}


def _cand(user_id: str, **kw) -> NudgeCandidate:
    return NudgeCandidate(user_id=user_id, **kw)


def task_reminders(
    user_id: str, tasks: list[Task], now: datetime, s: Settings
) -> list[NudgeCandidate]:
    out = []
    lead = timedelta(minutes=s.task_reminder_lead_min)
    for t in tasks:
        r = t.result
        if t.status != TaskStatus.COMPLETED or r is None or not r.success or not r.appointment_at:
            continue
        appt = r.appointment_at
        if appt <= now:
            continue
        where = t.target.name if t.target else "your appointment"
        common = dict(
            kind=NudgeKind.TASK_REMINDER,
            category=AutonomyCategory.REMINDERS,
            task_id=t.id,
            person_id=t.beneficiary.person_id,
            due_at=appt,
            data={"expires_at": appt, "appointment_at": appt.isoformat()},
        )
        if appt - now <= lead:
            out.append(
                _cand(
                    user_id,
                    urgency=Urgency.URGENT
                    if appt - now <= URGENT_REMINDER_WINDOW
                    else Urgency.NORMAL,
                    reason=f"appointment at {where} in {(appt - now).seconds // 60} min",
                    dedupe_key=f"reminder:{t.id}:soon",
                    **common,
                )
            )
        local = to_ist(appt)
        if local.hour < 12:
            evening = at_ist(local.date() - timedelta(days=1), 20)
            if evening <= now < appt and appt - now > lead:
                out.append(
                    _cand(
                        user_id,
                        reason=f"appointment at {where} tomorrow morning",
                        dedupe_key=f"reminder:{t.id}:eve",
                        **common,
                    )
                )
    return out


def follow_ups(user_id: str, tasks: list[Task], now: datetime, s: Settings) -> list[NudgeCandidate]:
    out = []
    for t in tasks:
        r = t.result
        if t.status != TaskStatus.COMPLETED or r is None:
            continue
        if r.follow_up_at and r.follow_up_at <= now < r.follow_up_at + FOLLOW_UP_STALE:
            out.append(
                _cand(
                    user_id,
                    kind=NudgeKind.FOLLOW_UP,
                    category=AutonomyCategory.FOLLOW_UPS,
                    reason=f"follow up on: {t.spec.goal}",
                    due_at=r.follow_up_at,
                    task_id=t.id,
                    person_id=t.beneficiary.person_id,
                    dedupe_key=f"followup:{t.id}",
                    data={"expires_at": r.follow_up_at + FOLLOW_UP_STALE},
                )
            )
        care = r.care
        if t.type == TaskType.CUSTOMER_CARE and care and care.promised_date and not care.resolved:
            due = at_ist(care.promised_date, 10) + timedelta(hours=s.care_followup_grace_h)
            if now >= due:
                out.append(
                    _cand(
                        user_id,
                        kind=NudgeKind.FOLLOW_UP,
                        category=AutonomyCategory.FOLLOW_UPS,
                        reason=f"{care.company or 'company'} promised a fix by "
                        f"{care.promised_date} "
                        f"(ticket {care.ticket_number or '-'}); it has passed",
                        due_at=due,
                        task_id=t.id,
                        dedupe_key=f"care:{t.id}:{care.promised_date}",
                    )
                )
    return out


_LEADS = [
    (re.compile(r"rent|bill|emi|fee|due", re.I), (1,)),
    (re.compile(r"expir|renew|insurance|licen[cs]e|passport|policy", re.I), (30, 7)),
    (re.compile(r"birthday|anniversar", re.I), (3,)),
]


def lead_days(fact: Fact) -> tuple[int, ...]:
    text = f"{fact.key} {fact.value}"
    for rx, leads in _LEADS:
        if rx.search(text):
            return leads
    return (1,)


def date_facts(user_id: str, facts: list[Fact], now: datetime) -> list[NudgeCandidate]:
    out = []
    today = ist_date(now)
    for f in facts:
        if f.kind != FactKind.DATE or f.due_on is None:
            continue
        for lead in lead_days(f):
            if today == f.due_on - timedelta(days=lead):
                out.append(
                    _cand(
                        user_id,
                        kind=NudgeKind.DATE_BASED,
                        category=AutonomyCategory.FAMILY
                        if f.person_id
                        else AutonomyCategory.REMINDERS,
                        reason=f"{f.key.replace('_', ' ')}: {f.value} on {f.due_on} ({lead} days)",
                        due_at=at_ist(f.due_on, 9),
                        fact_id=f.id,
                        person_id=f.person_id,
                        dedupe_key=f"fact:{f.id}:{f.due_on}:{lead}",
                    )
                )
    return out


def patterns(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    """>=2 regular repeats of the same booking (stdev <= 30% of mean) -> nudge at
    last + mean (up to +3 days), once per cycle (US-9.4)."""
    groups: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        if (
            t.status == TaskStatus.COMPLETED
            and t.type in _BOOKINGISH
            and t.last_outcome == CallOutcome.SUCCESS
            and t.parent_task_id is None
        ):
            key = t.spec.business_id or (t.target.phone if t.target else None) or t.spec.category
            if key:
                groups[key].append(t)
    out = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda t: _when(t))
        times = [_when(t) for t in items]
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
        mean = statistics.mean(gaps)
        if mean < 86400 * 3:
            continue
        if len(gaps) > 1 and statistics.pstdev(gaps) > 0.3 * mean:
            continue
        due = times[-1] + timedelta(seconds=mean)
        if due <= now <= due + PATTERN_SLACK:
            last = items[-1]
            weeks = round(mean / (86400 * 7))
            out.append(
                _cand(
                    user_id,
                    kind=NudgeKind.PATTERN,
                    category=AutonomyCategory.ROUTINES,
                    reason=f"about {weeks} weeks since {last.spec.goal} "
                    f"({last.target.name if last.target else key})",
                    due_at=due,
                    task_id=last.id,
                    person_id=last.beneficiary.person_id,
                    dedupe_key=f"pattern:{key}:{ist_date(times[-1])}",
                    data={"proposed_from_task": last.id},
                )
            )
    return out


def _when(t: Task) -> datetime:
    return (
        t.result.appointment_at if t.result and t.result.appointment_at else None
    ) or t.created_at


def recurring_due(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    out = []
    for t in tasks:
        rule = t.recurrence
        if t.parent_task_id or rule is None or t.status.is_terminal or rule.next_run_at is None:
            continue
        if now <= rule.next_run_at <= now + timedelta(hours=24):
            out.append(
                _cand(
                    user_id,
                    kind=NudgeKind.RECURRING_DUE,
                    category=category_for(t.type)
                    if t.type != TaskType.RECURRING_BOOKING
                    else AutonomyCategory.ROUTINES,
                    reason=f"next in series '{t.spec.goal}' is booked at "
                    f"{to_ist(rule.next_run_at):%a %I:%M %p}",
                    due_at=rule.next_run_at,
                    task_id=t.id,
                    person_id=t.beneficiary.person_id,
                    dedupe_key=f"recurring:{t.id}:{ist_date(rule.next_run_at)}",
                    data={"expires_at": rule.next_run_at},
                )
            )
    return out


def stay_reminders(user_id: str, tasks: list[Task], now: datetime) -> list[NudgeCandidate]:
    out = []
    for t in tasks:
        hb = t.result.hotel_booking if t.result else None
        if hb is None or t.status != TaskStatus.COMPLETED:
            continue
        evening = at_ist(hb.check_in - timedelta(days=1), 18)
        check_in = at_ist(hb.check_in, 12)
        if evening <= now < check_in:
            out.append(
                _cand(
                    user_id,
                    kind=NudgeKind.TASK_REMINDER,
                    category=AutonomyCategory.REMINDERS,
                    reason=f"check-in at {hb.property.name} tomorrow"
                    f"{' (' + hb.property.address + ')' if hb.property.address else ''}",
                    due_at=check_in,
                    task_id=t.id,
                    person_id=t.beneficiary.person_id,
                    dedupe_key=f"stay:{hb.id}",
                    data={"expires_at": check_in},
                )
            )
    return out


def wellbeing_alerts(user_id: str, tasks: list[Task]) -> list[NudgeCandidate]:
    out = []
    for t in tasks:
        if t.type == TaskType.WELLBEING_CHECKIN and t.result and t.result.alert:
            out.append(
                alert_candidate(
                    user_id, t.id, t.beneficiary.person_id, t.result.alert, t.updated_at
                )
            )
    return out


def alert_candidate(user_id, task_id, person_id, text, at) -> NudgeCandidate:
    return _cand(
        user_id,
        kind=NudgeKind.WELLBEING_ALERT,
        category=AutonomyCategory.FAMILY,
        urgency=Urgency.SAFETY,
        reason=text,
        due_at=at,
        task_id=task_id,
        person_id=person_id,
        dedupe_key=f"wellbeing:{task_id}",
    )


def morning_briefing(
    user_id: str, profile: Profile, tasks: list[Task], facts: list[Fact], now: datetime
) -> list[NudgeCandidate]:
    if not profile.morning_briefing:
        return []
    local = to_ist(now)
    if not profile.briefing_hour_ist <= local.hour < profile.briefing_hour_ist + 2:
        return []
    today = local.date()
    appts = [
        t
        for t in tasks
        if t.result and t.result.appointment_at and ist_date(t.result.appointment_at) == today
    ]
    due = [f for f in facts if f.due_on and today <= f.due_on <= today + timedelta(days=3)]
    open_ = [t for t in tasks if not t.status.is_terminal and t.parent_task_id is None]
    if not (appts or due or open_):
        return []  # nothing to say -> skip the day (US-9.5)
    lines = [f"{t.spec.goal} at {to_ist(t.result.appointment_at):%I:%M %p}" for t in appts]
    lines += [f"{f.key.replace('_', ' ')}: {f.value} ({f.due_on})" for f in due]
    lines += [f"open: {t.spec.goal}" for t in open_[:3]]
    return [
        _cand(
            user_id,
            kind=NudgeKind.MORNING_BRIEFING,
            category=AutonomyCategory.BRIEFING,
            reason="; ".join(lines[:6]),
            due_at=now,
            dedupe_key=f"briefing:{today}",
            data={"lines": lines[:6]},
        )
    ]
