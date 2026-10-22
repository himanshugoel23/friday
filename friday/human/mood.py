"""Mood adaptation: if the other side sounds rushed or annoyed, shorter lines, ONE quick apology,
no extra questions. Rules only (no model). Stop / do-not-call requests stay with the call engine."""

from __future__ import annotations

import re

from friday.human.listener import shorten, split_sentences

RUSHED = re.compile(
    r"\b(jaldi|jldi|busy|hurry|quick(ly)?|time nahi|waqt nahi|fursat nahi|jaldi bolo|short mein|"
    r"jaldi batao|abhi nahi|in a hurry|rush)\b|जल्दी|व्यस्त|टाइम नहीं|वक़्त नहीं",
    re.I,
)
ANNOYED = re.compile(
    r"\b(baar baar|kitni baar|disturb|pareshan|irritat\w*|annoy\w*|bakwas|faltu|kyun (call|phone)|"
    r"why do you keep|stop (it|this)|leave me|dimag|tang)\b|बार बार|परेशान|फालतू|बकवास",
    re.I,
)


def detect(text: str) -> str:
    """'annoyed' | 'rushed' | 'neutral'."""
    if not text:
        return "neutral"
    if ANNOYED.search(text):
        return "annoyed"
    if RUSHED.search(text):
        return "rushed"
    return "neutral"


class MoodAdapter:
    MAX_WORDS = 12

    def __init__(self) -> None:
        self.mood = "neutral"
        self.apologised = False
        self.events = 0

    def observe(self, callee_text: str) -> None:
        m = detect(callee_text)
        if m != "neutral":
            if self.mood == "neutral":
                self.events += 1
            self.mood = m if not (self.mood == "annoyed" and m == "rushed") else "annoyed"

    @property
    def active(self) -> bool:
        return self.mood != "neutral"

    def needs_apology(self) -> bool:
        return self.active and not self.apologised

    def adapt(self, text: str) -> str:
        """Fewer words and at most one question. Disclosure / safety lines are never touched."""
        if not self.active:
            return text
        parts = split_sentences(text)
        kept: list[str] = []
        asked = False
        for s in parts:
            if s.rstrip().endswith("?"):
                if asked:
                    continue
                asked = True
            kept.append(s)
        return shorten(" ".join(kept), self.MAX_WORDS)
