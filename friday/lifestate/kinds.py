"""Deterministic guess of an event kind from words (Hinglish and English).

Used for the user's own messages and for calendar titles. The result only picks a kind label and
the default "protected" flag; the text itself is never executed or followed as an instruction.
"""

from __future__ import annotations

import re

from friday.lifestate.models import PROTECTED_BY_DEFAULT, EventKind

_P = re.IGNORECASE
KIND_PATTERNS: list[tuple[EventKind, re.Pattern[str]]] = [
    (
        EventKind.BILL_DUE,
        re.compile(
            r"\b(bill|bijli|electricity|light bill|paani|water bill|gas|wifi|broadband|internet|"
            r"recharge|emi|rent|kiraya|premium|insurance|credit card|card payment|due date)\b",
            _P,
        ),
    ),
    (
        EventKind.INTERVIEW,
        re.compile(r"\b(interview|interviw|intervew|hr round|technical round|screening)\b", _P),
    ),
    (
        EventKind.APPOINTMENT,
        re.compile(
            r"\b(dentist|doctor|dr\.?|clinic|hospital|checkup|check-up|appointment|haircut|salon|"
            r"barber|physio|physiotherapy|therapy|vaccine|vaccination|blood test|lab test|"
            r"scan|eye test|parlour|parlor)\b",
            _P,
        ),
    ),
    (
        EventKind.TRAVEL,
        re.compile(
            r"\b(flight|train|bus|airport|station|yatra|safar|travel|journey|trip|cab)\b", _P
        ),
    ),
    (
        EventKind.MEETING,
        re.compile(
            r"\b(meeting|meet|standup|stand-up|sync|presentation|demo|review|client|catch ?up)\b",
            _P,
        ),
    ),
    (
        EventKind.PERSONAL,
        re.compile(
            r"\b(birthday|bday|party|shaadi|wedding|dinner|lunch|movie|match|puja|pooja|function|"
            r"anniversary|gym|class|school|pta)\b",
            _P,
        ),
    ),
]


def guess_kind(text: str) -> EventKind:
    for kind, pat in KIND_PATTERNS:
        if pat.search(text or ""):
            return kind
    return EventKind.OTHER


def default_protected(kind: EventKind) -> bool:
    return kind in PROTECTED_BY_DEFAULT
