"""Task-engine events (subclasses of the core ``Event``; no core change needed)."""

from __future__ import annotations

from friday.core.events import Event


class WellbeingAlertRaised(Event):
    """A13: a check-in sounded wrong (or nobody answered). The proactive engine turns
    it into a SAFETY nudge (bypasses cap + quiet hours)."""

    task_id: str
    user_id: str
    person_id: str | None = None
    text: str


class BusinessContactLogged(Event):
    """E.33/35: an inbound contact that matched no task (ops log; no user notified)."""

    phone: str
    kind: str  # missed_unmatched | message_unmatched | message_taken
