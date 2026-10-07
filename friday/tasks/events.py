"""Task-engine events (subclasses of the core ``Event``; no core change needed)."""

from __future__ import annotations

from friday.core.events import Event, WellbeingAlertRaised  # noqa: F401  (moved to core)


class BusinessContactLogged(Event):
    """E.33/35: an inbound contact that matched no task (ops log; no user notified)."""

    phone: str
    kind: str  # missed_unmatched | message_unmatched | message_taken
