"""When is the next reminder of a case due? Pure and table-driven (no clock, no store).

A reminder is identified by ``refund:<case_id>:<epoch>:<n>``: the epoch changes on every state
change, so a case that moves gets a fresh schedule, and ``n`` is the count already sent or expired
in that epoch, so a reminder is never sent twice. The schedule offsets are PROPOSALS the founder
approves (docs/REFUNDS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from friday.core.clock import at_ist, ist_date
from friday.refunds.config import RefundConfig
from friday.refunds.models import RefundCase, RefundState

S = RefundState

# state -> ([(days after the anchor, stage)], (tail days, tail stage) | None)
SCHEDULE: dict[RefundState, tuple[list[tuple[int, str]], tuple[int, str] | None]] = {
    S.SUSPECTED: ([(0, "suspect_ask"), (2, "suspect_again")], None),
    S.OPENED: ([(1, "requested_q"), (3, "followup")], (7, "checkin")),
    S.REQUESTED: ([(3, "checkin"), (7, "followup")], (7, "checkin")),
    S.VENDOR_ACKNOWLEDGED: ([(3, "checkin"), (7, "followup")], (7, "checkin")),
    S.PROMISED: ([(1, "received_q"), (4, "followup")], (7, "received_q")),  # anchor = promised day
    S.ESCALATED: ([(7, "checkin")], (7, "checkin")),
    S.REJECTED: ([(1, "rejected_q")], None),
    S.RECEIVED: ([(2, "short_q")], None),
}
FOLLOWUP_STAGES = frozenset({"followup"})


@dataclass(frozen=True)
class Reminder:
    key: str
    stage: str
    n: int
    due_at: datetime
    expires_at: datetime


def key_for(case: RefundCase, n: int) -> str:
    return f"refund:{case.id}:{case.state_epoch}:{n}"


def _anchor(case: RefundCase, cfg: RefundConfig) -> datetime:
    if case.state == S.PROMISED and case.promised_date is not None:
        return at_ist(case.promised_date, cfg.nudge_hour)
    return case.state_changed_at


def _due(anchor: datetime, days: int, cfg: RefundConfig) -> datetime:
    if days == 0:
        return anchor
    return at_ist(ist_date(anchor) + timedelta(days=days), cfg.nudge_hour)


def next_reminder(
    case: RefundCase, *, sent_in_epoch: int, sent_total: int, cfg: RefundConfig
) -> Reminder | None:
    """The reminder the case is waiting for next, or ``None`` (closed, muted, schedule over, or
    the per-case limit reached). ``sent_in_epoch`` counts sent AND expired nudges of this epoch."""
    if case.state == S.CLOSED or case.muted or sent_total >= cfg.max_nudges_per_case:
        return None
    sched = SCHEDULE.get(case.state)
    if sched is None:
        return None
    steps, tail = sched
    n = sent_in_epoch
    anchor = _anchor(case, cfg)
    if n < len(steps):
        days, stage = steps[n]
    elif tail is not None:
        every, stage = tail
        days = steps[-1][0] + every * (n - len(steps) + 1)
    else:
        return None
    due = _due(anchor, days, cfg)
    return Reminder(key_for(case, n), stage, n, due, due + timedelta(hours=cfg.expire_after_hours))
