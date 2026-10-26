# ruff: noqa: E501
"""MemoryService: aliases from corrections, episodes, the "what do you remember" list.

Storage reuses what exists (no migration): ``Fact`` rows for alias candidates (key
``alias_seen:<heard>``) and episodes (key ``episode:<task id>``), and ``Person.aliases`` /
``Place.aliases`` for active aliases. Everything is scoped to one user. Secrets are never stored:
text is passed through ``redact_secrets`` first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import Fact, FactKind
from friday.voice.text import redact_secrets

log = get_logger(__name__)

ALIAS_PREFIX = "alias_seen:"
EPISODE_PREFIX = "episode:"
ALIAS_ACTIVE_AFTER = 2  # sightings before an inferred alias becomes active
MAX_ALIASES = 6
SIM_MIN = 0.5
EPISODE_DAYS = 365
_WS = re.compile(r"\s+")


def sounds_like(alias: str, canonical: str) -> bool:
    """True for a spelling or sound variant ("shriya" for "Shreya"): a mis-hearing fix we INFERRED.
    A relation word ("papa" for "Ramesh Sharma") is a reference the user gave."""
    a, c = _norm(alias), _norm(canonical)
    best = max([SequenceMatcher(None, a, c).ratio(),
                *(SequenceMatcher(None, a, t).ratio() for t in c.split())])
    return best >= 0.6


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


@dataclass(frozen=True)
class MemoryItem:
    id: str  # "person:<id>", "place:<id>", "fact:<id>", "alias:<kind>:<id>:<alias>"
    kind: str  # profile | person | place | fact | episode | alias
    text: str
    source: str  # said | done | inferred
    when: datetime | None = None


class MemoryService:
    def __init__(self, repos: Any, clock: Any) -> None:
        self.repos, self.clock = repos, clock

    def _now(self) -> datetime:
        return self.clock.now()

    # ------------------------------------------------------------------ aliases
    async def _targets(self, user_id: str) -> list[tuple[str, Any, list[str]]]:
        out: list[tuple[str, Any, list[str]]] = []
        for p in await self.repos.people.list_for_owner(user_id):
            out.append(("person", p, [p.name, *p.aliases]))
        for pl in await self.repos.places.list_for_owner(user_id):
            out.append(("place", pl, [pl.label, *pl.aliases]))
        return out

    async def note_misheard(self, user_id: str, heard: str, meant: str, *,
                            confirmed: bool = False) -> str:
        """Record that ``heard`` was really ``meant`` (a saved person or place). Returns
        ``ignored`` | ``recorded`` | ``promoted``. An alias goes live after two sightings or one
        confirmation; it must sound like the name, may not equal another entry, and is capped."""
        h, m = _norm(heard), _norm(meant)
        if not h or not m or h == m or len(h) < 3 or any(c.isdigit() for c in h):
            return "ignored"
        if redact_secrets(heard) != heard or redact_secrets(meant) != meant:
            return "ignored"
        targets = await self._targets(user_id)
        owner = next(((k, o, names) for k, o, names in targets
                      if m in {_norm(n) for n in names}), None)
        if owner is None:
            return "ignored"  # only known people and places get aliases
        kind, obj, names = owner
        canonical = names[0]
        if SequenceMatcher(None, h, _norm(canonical)).ratio() < SIM_MIN and not confirmed:
            return "ignored"
        for _k, _o, other in targets:
            if _o is not obj and h in {_norm(n) for n in other}:
                return "ignored"  # would point at someone else
        if h in {_norm(n) for n in names}:
            return "ignored"
        facts = await self.repos.facts.list_for_user(user_id)
        key = ALIAS_PREFIX + h
        cand = next((f for f in facts if f.key == key), None)
        count = (int(cand.value.rsplit("|", 1)[1]) if cand and "|" in cand.value else 0) + 1
        if confirmed or count >= ALIAS_ACTIVE_AFTER:
            if len(obj.aliases) >= MAX_ALIASES:
                return "ignored"
            obj.aliases = [*obj.aliases, h]
            repo = self.repos.people if kind == "person" else self.repos.places
            await repo.upsert(obj)
            if cand is not None:
                await self.repos.facts.delete(cand.id)
            log.info("memory alias promoted kind=%s", kind)
            return "promoted"
        await self.repos.facts.upsert(Fact(
            user_id=user_id, kind=FactKind.PATTERN, key=key, value=f"{canonical}|{count}",
            confidence=0.5))
        return "recorded"

    async def forget_alias(self, user_id: str, alias: str) -> bool:
        a = _norm(alias)
        done = False
        for kind, obj, _names in await self._targets(user_id):
            if a in {_norm(x) for x in obj.aliases}:
                obj.aliases = [x for x in obj.aliases if _norm(x) != a]
                await (self.repos.people if kind == "person" else self.repos.places).upsert(obj)
                done = True
        for f in await self.repos.facts.list_for_user(user_id):
            if f.key == ALIAS_PREFIX + a:
                await self.repos.facts.delete(f.id)
                done = True
        return done

    # ------------------------------------------------------------------ episodes
    async def record_episode(self, user_id: str, task_id: str, goal: str, outcome: str,
                             with_whom: str | None = None) -> bool:
        goal, outcome = redact_secrets(goal or "").strip(), redact_secrets(outcome or "").strip()
        if not goal:
            return False
        parts = [goal[:120], outcome[:40]] + ([with_whom[:60]] if with_whom else [])
        await self.repos.facts.upsert(Fact(
            user_id=user_id, kind=FactKind.GENERAL, key=EPISODE_PREFIX + task_id,
            value=" | ".join(parts), confidence=1.0))
        return True

    async def episodes(self, user_id: str, limit: int = 5) -> list[Fact]:
        facts = [f for f in await self.repos.facts.list_for_user(user_id)
                 if f.key.startswith(EPISODE_PREFIX)]
        return sorted(facts, key=lambda f: f.updated_at, reverse=True)[:limit]

    async def purge_expired(self, user_id: str, days: int = EPISODE_DAYS) -> int:
        cutoff = self._now() - timedelta(days=days)
        n = 0
        for f in await self.repos.facts.list_for_user(user_id):
            if f.key.startswith(EPISODE_PREFIX) and f.updated_at < cutoff:
                n += int(await self.repos.facts.delete(f.id))
        return n

    # ------------------------------------------------------------------ the list
    async def remember_list(self, user_id: str) -> list[MemoryItem]:
        """Everything Friday holds about this user, one line each, with source and date."""
        items: list[MemoryItem] = []
        prof = await self.repos.profiles.get_or_default(user_id)
        bits = [b for b in (prof.name, prof.city) if b]
        if bits:
            items.append(MemoryItem("profile:me", "profile", ", ".join(bits), "said"))
        for p in await self.repos.people.list_for_owner(user_id):
            rel = f" ({p.relation})" if p.relation else ""
            items.append(MemoryItem(f"person:{p.id}", "person", p.name + rel, "said", p.created_at))
            for a in p.aliases:
                items.append(MemoryItem(f"alias:person:{p.id}:{a}", "alias",
                                        f"'{a}' means {p.name}",
                                        "inferred" if sounds_like(a, p.name) else "said",
                                        p.updated_at))
        for pl in await self.repos.places.list_for_owner(user_id):
            if pl.ephemeral:
                continue
            items.append(MemoryItem(f"place:{pl.id}", "place", pl.label, "said", pl.created_at))
            for a in pl.aliases:
                items.append(MemoryItem(f"alias:place:{pl.id}:{a}", "alias",
                                        f"'{a}' means {pl.label}",
                                        "inferred" if sounds_like(a, pl.label) else "said",
                                        pl.updated_at))
        for f in await self.repos.facts.list_for_user(user_id):
            if f.key.startswith(ALIAS_PREFIX):
                continue
            kind = "episode" if f.key.startswith(EPISODE_PREFIX) else "fact"
            src = "done" if kind == "episode" else ("inferred" if f.kind == FactKind.PATTERN else "said")
            label = f.value if kind == "episode" else f"{f.key.replace('_', ' ')}: {f.value}"
            items.append(MemoryItem(f"fact:{f.id}", kind, label, src, f.updated_at))
        return items

    async def forget(self, user_id: str, item_id: str) -> bool:
        """Forget one item from the list by its id (aliases, facts, episodes, a person, a place)."""
        kind, _, rest = item_id.partition(":")
        if kind == "alias":
            _k, _, tail = rest.partition(":")
            _oid, _, alias = tail.partition(":")
            return await self.forget_alias(user_id, alias)
        if kind == "fact":
            f = await self.repos.facts.get(rest)
            return bool(f and f.user_id == user_id and await self.repos.facts.delete(rest))
        return False  # people and places are removed by their own commands


def format_list(items: list[MemoryItem], lang: str = "hinglish", *, limit: int = 25) -> str:
    """The user-facing list: one line each with its source and date, newest first."""
    from friday.memory import copy

    if not items:
        return copy.line("empty", lang)
    rows = sorted(items, key=lambda i: i.when.timestamp() if i.when else 0.0)
    rows = rows[-limit:]
    lines = [copy.line("header", lang)]
    for it in rows:
        when = f", {it.when:%d %b}" if it.when else ""
        lines.append(f"- {it.text} ({copy.line('source_' + it.source, lang)}{when})")
    lines.append(copy.line("footer", lang))
    return "\n".join(lines)
