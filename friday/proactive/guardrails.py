"""Proactive guardrails (BRIEF Proactive v1, PRD US-10.2). Pure + deterministic.

Order: consent -> autonomy "stop" -> ignore-learning -> quiet hours -> daily cap.
SAFETY bypasses everything except consent; URGENT bypasses the cap and ignore-learning.
Reminders for appointments Friday booked (and the briefing) are exempt from the cap
but still respect quiet hours.

Founder rule (2026-10-12): at most 3 separate messages a day OR one morning digest. A normal nudge
that would exceed the cap (or any normal nudge when ``proactive_digest_only``) is not dropped: it
becomes a line of the next morning digest, unless it would be stale by then.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from friday.core.clock import at_ist, is_quiet_hours, next_quiet_hours_end, to_ist
from friday.core.config import Settings
from friday.core.models import (
    AutonomySetting,
    NudgeCandidate,
    NudgeKind,
    Urgency,
)

CAP_EXEMPT_KINDS = frozenset(
    {NudgeKind.TASK_REMINDER, NudgeKind.TASK_RESULT, NudgeKind.MORNING_BRIEFING}
)
BACKOFF_MIN_GAP = timedelta(days=2)  # after 2 ignores: at most every other day (doubling)
SUPPRESS_FOR = timedelta(days=30)  # after 3 ignores: off for 30 days


@dataclass(frozen=True)
class Verdict:
    action: Literal["send", "schedule", "suppress", "digest"]
    reason: str = ""
    send_at: datetime | None = None


def next_briefing_at(now: datetime, hour: int) -> datetime:
    local = to_ist(now)
    today = at_ist(local.date(), hour)
    return today if now < today else at_ist(local.date() + timedelta(days=1), hour)


def _digest(c: NudgeCandidate, now: datetime, hour: int, why: str) -> Verdict:
    at = next_briefing_at(now, hour)
    expires = c.data.get("expires_at")
    if isinstance(expires, datetime) and expires <= at:
        return Verdict("suppress", f"{why}; stale by the next digest")
    return Verdict("digest", why, send_at=at)


def evaluate(
    c: NudgeCandidate,
    *,
    now: datetime,
    settings: Settings,
    autonomy: AutonomySetting | None = None,
    sent_today: int = 0,
    ignore_streak: int = 0,
    last_ignored_at: datetime | None = None,
    last_sent_same_kind: datetime | None = None,
    recipient_consent_ok: bool = True,
    briefing_hour_ist: int = 8,
) -> Verdict:
    safety = c.urgency == Urgency.SAFETY
    normal = c.urgency == Urgency.NORMAL
    if not recipient_consent_ok:
        return Verdict("suppress", "recipient has not opted in")
    if autonomy is not None and not autonomy.enabled and not safety:
        return Verdict("suppress", f"user stopped {c.category.value} nudges")
    if normal and c.kind not in CAP_EXEMPT_KINDS:
        threshold = settings.ignore_learning_threshold
        if ignore_streak >= threshold and (
            last_ignored_at is None or now - last_ignored_at < SUPPRESS_FOR
        ):
            return Verdict("suppress", f"ignored {ignore_streak} in a row")
        if (
            ignore_streak >= max(1, threshold - 1)
            and last_sent_same_kind is not None
            and now - last_sent_same_kind < BACKOFF_MIN_GAP
        ):
            return Verdict("suppress", "backing off after ignores")
    if (
        normal
        and c.kind not in CAP_EXEMPT_KINDS
        and getattr(settings, "proactive_digest_only", False)
    ):
        return _digest(c, now, briefing_hour_ist, "digest-only mode")
    if not safety and is_quiet_hours(now, settings.quiet_hours_start, settings.quiet_hours_end):
        end = next_quiet_hours_end(now, settings.quiet_hours_start, settings.quiet_hours_end)
        expires = c.data.get("expires_at")
        if isinstance(expires, datetime) and expires <= end:
            return Verdict("suppress", "stale by the end of quiet hours")
        return Verdict("schedule", "quiet hours", send_at=end)
    if normal and c.kind not in CAP_EXEMPT_KINDS and sent_today >= settings.proactive_daily_cap:
        return _digest(c, now, briefing_hour_ist, "daily cap reached")
    return Verdict("send")
