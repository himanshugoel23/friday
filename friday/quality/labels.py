"""Review labels, post-call ratings and the WhatsApp rating line.

NOT WIRED: nothing here sends a message. ``RATING_PROMPT`` is the text a future
template / follow-up would use, ``parse_rating_reply`` reads the answer, and
``TranscriptStore.record_rating`` stores it.
"""

from __future__ import annotations

import re

# The fixed set the founder tags calls with (docs/QUALITY_LOOP.md explains each one).
LABELS: tuple[str, ...] = (
    "robotic",
    "interrupted_me",
    "cut_me_off",
    "wrong_answer",
    "too_long",
    "good",
    "helpline_feel",
    "slow",
    "language_mismatch",
)
GOOD_LABELS = frozenset({"good"})

RATING_PROMPT = {
    "en": "How was your call with Friday? Reply 1 to 5 (5 is great), or 👍 / 👎.",
    "hinglish": (
        "Friday ke saath call kaisi rahi? 1 se 5 tak number bhejiye (5 sabse achha), ya 👍 / 👎."
    ),
}

_THUMBS_UP = re.compile(r"👍|\b(thumbs?\s*up|good|great|achha|accha|badhiya)\b", re.I)
_THUMBS_DOWN = re.compile(r"👎|\b(thumbs?\s*down|bad|poor|bura|bekar)\b", re.I)
_NUMBER = re.compile(r"(?<!\d)([1-5])(?!\d)")


def normalise_rating(value: int | str) -> int:
    """1-5 stays; thumbs up = 5, thumbs down = 1. Raises ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError("rating must be 1-5 or a thumb")
    if isinstance(value, int):
        if 1 <= value <= 5:
            return value
        raise ValueError("rating must be between 1 and 5")
    parsed = parse_rating_reply(str(value))
    if parsed is None:
        raise ValueError("rating must be 1-5 or a thumb")
    return parsed


def parse_rating_reply(text: str) -> int | None:
    """A caller's WhatsApp reply to ``RATING_PROMPT`` -> 1..5, or None if it is not a rating."""
    t = (text or "").strip()
    if not t:
        return None
    if t.lower() in ("up", "down"):
        return 5 if t.lower() == "up" else 1
    m = _NUMBER.search(t)
    if m and len(t) <= 12:
        return int(m.group(1))
    if _THUMBS_DOWN.search(t):
        return 1
    if _THUMBS_UP.search(t):
        return 5
    return None


def validate_labels(labels: list[str]) -> list[str]:
    bad = [x for x in labels if x not in LABELS]
    if bad:
        raise ValueError(f"unknown label(s) {bad}; choose from {', '.join(LABELS)}")
    return list(dict.fromkeys(labels))
