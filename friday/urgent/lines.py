# ruff: noqa: E501
"""EVERY line Friday may SPEAK when she rings the user about an urgent call. One module, so the
founder reviews one place.

STATUS: PENDING_FOUNDER_APPROVAL for every line (hear-before-change, CLAUDE.md rule 3). No audio has
been generated. ``LINE_STATUS`` is checked by the real dial adapter (``telephony.py``): while it is not
``APPROVED`` the real call REFUSES to dial, so nothing can reach a phone before the founder has heard
the audio and a reviewed commit flips this constant (and the docs table in docs/URGENT_ESCALATION.md).

Rules the lines obey (tests enforce them):
* The listener is the user themselves, so the line may use the name the user chose ({user}); it never
  says who called, what they said, a number, a place or any private fact (a phone call is overheard;
  the details are on WhatsApp).
* No digits, no promise, no question that needs an answer (the call is a nudge, not a conversation).
* Female forms in Hindi. Roman for ``hinglish``, Devanagari for ``hi``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
APPROVED = "APPROVED"
LANGS = ("hinglish", "hi", "en")

LINES: dict[str, dict[str, str]] = {
    "ring.urgent": {
        "hinglish": "Hello {user}, main Friday bol rahi hoon. Aapke liye ek urgent message aaya hai. Kripya abhi WhatsApp dekh lijiye. Thank you.",
        "hi": "हैलो {user}, मैं फ्राइडे बोल रही हूँ। आपके लिए एक urgent मैसेज आया है। कृपया अभी WhatsApp देख लीजिए। थैंक यू।",
        "en": "Hello {user}, this is Friday. There is an urgent message for you. Please check WhatsApp now. Thank you.",
    },
    "ring.emergency": {
        "hinglish": "Hello {user}, main Friday bol rahi hoon. Aapke liye ek emergency message aaya hai. Kripya abhi WhatsApp dekh lijiye. Thank you.",
        "hi": "हैलो {user}, मैं फ्राइडे बोल रही हूँ। आपके लिए एक emergency मैसेज आया है। कृपया अभी WhatsApp देख लीजिए। थैंक यू।",
        "en": "Hello {user}, this is Friday. There is an emergency message for you. Please check WhatsApp now. Thank you.",
    },
}

_SLOT = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class PendingLine:
    id: str
    language: str
    text: str
    status: str = LINE_STATUS


def required_slots(key: str) -> frozenset[str]:
    return frozenset(_SLOT.findall(LINES[key]["hinglish"]))


def say(key: str, lang: str = "hinglish", **slots: str) -> str:
    """The fixed line ``key`` in ``lang`` with its slots filled. Missing slot -> KeyError."""
    text = LINES[key][lang if lang in LANGS else "hinglish"]
    return _SLOT.sub(lambda m: slots[m.group(1)], text)


def all_lines() -> list[PendingLine]:
    return [PendingLine(f"urg.{k}.{lang}", lang, LINES[k][lang]) for k in LINES for lang in LANGS]


def approved() -> bool:
    return LINE_STATUS == APPROVED
