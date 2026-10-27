"""Item 5: calendar clash and new-invite heads-up, as pure detectors over event lists."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from friday.chatbot.parity import copy


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    invited: bool = False  # someone else's invite, not yet accepted
    all_day: bool = False


def clashes(events: list[Event]) -> list[tuple[Event, Event]]:
    """Pairs that overlap in time (touching end == start is not a clash). All-day events are ignored."""
    timed = sorted((e for e in events if not e.all_day and e.end > e.start), key=lambda e: e.start)
    out: list[tuple[Event, Event]] = []
    for i, a in enumerate(timed):
        for b in timed[i + 1 :]:
            if b.start >= a.end:
                break
            out.append((a, b))
    return out


def new_invites(events: list[Event], seen_ids: set[str]) -> list[Event]:
    return [e for e in events if e.invited and e.id not in seen_ids]


def _when(e: Event) -> str:
    return e.start.strftime("%d %b %H:%M").lstrip("0")


def heads_up(events: list[Event], seen_ids: set[str], lang: str = "hinglish") -> list[str]:
    """Messages to send (empty when there is nothing new). One line per clash and per new invite."""
    out = [
        copy.line("clash_head", lang, a=a.title, b=b.title, when=_when(b)) for a, b in clashes(events)
    ]
    out += [copy.line("new_invite", lang, title=e.title, when=_when(e)) for e in new_invites(events, seen_ids)]
    return out
