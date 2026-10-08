"""Task-engine events. ``WellbeingAlertRaised`` now lives in core (re-exported)."""

from __future__ import annotations

from friday.core.events import Event, WellbeingAlertRaised

__all__ = ["BusinessContactLogged", "WellbeingAlertRaised"]


class BusinessContactLogged(Event):
    """E.33/35: an inbound contact that matched no task (ops log; no user notified)."""

    phone: str
    kind: str  # missed_unmatched | message_unmatched | message_taken
