"""The user's memory, in the small form the Speech Understander needs (names, places, shops, recent talk).

No phone numbers, addresses, notes or account details ever go in: only the words a mis-heard name could be
fixed with. ``vocab`` is the same material as lower-case tokens, used by the grounding check in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from friday.core.models import ConversationContext, Direction

_TOKEN = re.compile(r"[\wऀ-ॿ']+", re.U)
_LONG_DIGITS = re.compile(r"\d[\d\s\-.]{5,}\d")


def _clip(text: str, n: int = 140) -> str:
    text = _LONG_DIGITS.sub("#", " ".join((text or "").split()))
    return text if len(text) <= n else text[: n - 1] + "…"


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if len(t) > 1}


@dataclass
class MemoryView:
    user_name: str | None = None
    city: str | None = None
    language: str | None = None
    people: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    businesses: list[str] = field(default_factory=list)
    open_tasks: list[str] = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    question: str | None = None  # what Friday just asked the user (a short answer follows)
    vocab: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)  # learned spoken form -> saved name

    def payload(self) -> dict[str, Any]:
        """What the model sees (JSON-able, no empty keys)."""
        out: dict[str, Any] = {
            "user_name": self.user_name,
            "city": self.city,
            "language": self.language,
            "people": self.people,
            "places": self.places,
            "shops": self.businesses,
            "open_requests": self.open_tasks,
            "recent_chat": self.recent,
            "friday_just_asked": self.question,
        }
        return {k: v for k, v in out.items() if v}


def _sounds_like(alias: str, canonical: str) -> bool:
    from friday.memory.service import sounds_like

    return sounds_like(alias, canonical)


def build_memory(ctx: ConversationContext | None, *, limit: int = 12) -> MemoryView:
    if ctx is None:
        return MemoryView()
    mv = MemoryView(
        user_name=(ctx.profile.name if ctx.profile else None),
        city=(ctx.profile.city if ctx.profile else None),
        language=(ctx.profile.language.value if ctx.profile and ctx.profile.language else None),
    )
    for p in ctx.people[:limit]:
        label = p.name + (f" ({p.relation})" if p.relation else "")
        if p.aliases:
            label += " aka " + ", ".join(p.aliases[:3])
        mv.people.append(label)
        for a in p.aliases:
            if _sounds_like(a, p.name):
                mv.aliases[a.lower()] = p.name
        mv.vocab |= _tokens(p.name) | set().union(*[_tokens(a) for a in p.aliases[:3]] or [set()])
    for pl in ctx.places[:limit]:
        label = pl.label + (f" aka {', '.join(pl.aliases[:3])}" if pl.aliases else "")
        mv.places.append(label)
        for a in pl.aliases:
            if _sounds_like(a, pl.label):
                mv.aliases[a.lower()] = pl.label
        mv.vocab |= _tokens(pl.label) | set().union(*[_tokens(a) for a in pl.aliases[:3]] or [set()])
    seen: set[str] = set()
    for b in ctx.known_businesses[:limit]:
        if b.name and b.name.lower() not in seen:
            seen.add(b.name.lower())
            mv.businesses.append(b.name)
            mv.vocab |= _tokens(b.name)
    for t in ctx.open_tasks[:5]:
        goal = getattr(getattr(t, "spec", None), "goal", None)
        if goal:
            mv.open_tasks.append(_clip(goal, 100))
            mv.vocab |= _tokens(goal)
    for turn in (ctx.recent or [])[-4:]:
        who = "user" if turn.direction == Direction.INBOUND else "friday"
        mv.recent.append(f"{who}: {_clip(turn.text)}")
    if ctx.pending_question is not None:
        mv.question = _clip(ctx.pending_question.text, 160)
    if mv.user_name:
        mv.vocab |= _tokens(mv.user_name)
    return mv
