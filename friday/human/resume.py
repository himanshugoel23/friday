# ruff: noqa: E501
"""Barge-in resume: after an interruption continue the unfinished point, not the whole sentence."""

from __future__ import annotations

import re

from friday.human.listener import split_sentences

_ACK = re.compile(
    r"^\s*(haan|han|ha|ji|ji haan|haan ji|boliye|boliyega|bolo|achha|accha|hmm+|ok(ay)?|theek hai|theek|"
    r"yes|yeah|go on|go ahead|continue|sun raha hoon|sun rahi hoon|bataiye|batao|हाँ|जी|बोलिए|अच्छा)"
    r"(\s+(ji|boliye|bataiye|haan|hai|sir|madam))*\s*[.!?]*\s*$",
    re.I,
)


def is_acknowledgement(text: str | None) -> bool:
    """A short 'go on' from the other side, not a new question or answer."""
    t = (text or "").strip()
    return bool(t) and len(t.split()) <= 4 and bool(_ACK.match(t))


def unfinished(full_text: str, sent_parts: int) -> str | None:
    """The part still to say. ``sent_parts`` sentences were fully queued; the last queued one may
    have been cut, so continue from its second clause when it has a comma, else from its start.
    None when nothing is left (everything was queued before the interruption and it was short)."""
    parts = split_sentences(full_text)
    if not parts:
        return None
    if sent_parts <= 0:
        return full_text  # cut before the first sentence ended: say it all
    if sent_parts >= len(parts):
        return None if len(parts) == 1 else parts[-1]  # only the last sentence may have been cut
    cut = parts[sent_parts - 1]
    rest = parts[sent_parts:]
    if "," in cut and len(cut.split()) > 6:
        tail = cut.split(",", 1)[1].strip()
        if tail:
            rest = [tail, *rest]
    else:
        rest = [cut, *rest]
    return " ".join(rest)


def with_connector(rest: str | None, connector: str | None) -> str | None:
    if not rest:
        return None
    return f"{connector} {rest[0].lower() + rest[1:]}" if connector else rest
