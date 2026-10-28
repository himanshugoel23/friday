# ruff: noqa: E501
"""The user's own lingo dictionary: names, home area, nearby places, family, favourite shops, words they use.

Storage reuses ``Fact`` rows (key ``dict:<kind>:<word>``), so it is per user, shows up in "what do you
remember about me", is removed by "forget <word>" and by the existing delete-everything flow (DPDP), and
needs no migration. A "heard form" (a spelling the user typed for this word) becomes ACTIVE after two sightings
or one confirmation, the same rule as ``friday/memory`` aliases; people and places that already exist as
``Person`` / ``Place`` rows keep using ``MemoryService.note_misheard`` for that.
No phone numbers, e-mail addresses, OTP/PIN wording or long digit runs are ever stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import ConversationContext, Fact, FactKind
from friday.speech.fuzzy import Entity, norm
from friday.voice.text import redact_secrets

log = get_logger(__name__)
PREFIX = "dict:"
KINDS = ("place", "person", "shop", "word")
ACTIVE_AFTER = 2
MAX_ENTRIES = 200
MAX_HEARD = 6
_BAD = re.compile(r"\d{5,}|@")


@dataclass
class DictEntry:
    written: str
    kind: str = "word"
    heard: list[str] = field(default_factory=list)  # active heard forms
    seen: dict[str, int] = field(default_factory=dict)  # candidate heard forms -> sightings
    fact_id: str | None = None

    def entity(self) -> Entity:
        return Entity(self.written, self.kind, "dictionary", tuple(self.heard))


def _key(kind: str, written: str) -> str:
    return f"{PREFIX}{kind}:{norm(written)}"


def _pack(e: DictEntry) -> str:
    return json.dumps({"w": e.written, "k": e.kind, "h": e.heard, "s": e.seen}, ensure_ascii=False)


def _unpack(f: Fact) -> DictEntry | None:
    try:
        d = json.loads(f.value)
        return DictEntry(str(d["w"]), str(d.get("k", "word")), [str(x) for x in d.get("h", [])],
                         {str(k): int(v) for k, v in dict(d.get("s", {})).items()}, f.id)
    except (ValueError, KeyError, TypeError):
        return None


def acceptable(text: str) -> bool:
    t = (text or "").strip()
    return bool(2 <= len(t) <= 40 and redact_secrets(t) == t and not _BAD.search(t))


class UserDictionary:
    def __init__(self, repos: Any) -> None:
        self.repos = repos

    async def _facts(self, user_id: str) -> list[Fact]:
        return [f for f in await self.repos.facts.list_for_user(user_id) if f.key.startswith(PREFIX)]

    async def list(self, user_id: str) -> list[DictEntry]:
        return [e for f in await self._facts(user_id) if (e := _unpack(f)) is not None]

    async def add(self, user_id: str, written: str, kind: str = "word", heard: str | None = None) -> DictEntry | None:
        """Add or extend a word. Returns None when refused (secret-looking, too long, full)."""
        written = " ".join((written or "").split())
        kind = kind if kind in KINDS else "word"
        if not acceptable(written) or (heard is not None and not acceptable(heard)):
            return None
        facts = await self._facts(user_id)
        existing = next((f for f in facts if f.key == _key(kind, written)), None)
        if existing is None and len(facts) >= MAX_ENTRIES:
            return None
        entry = (_unpack(existing) if existing else None) or DictEntry(written, kind)
        entry.written = written  # the user's latest spelling/casing wins
        if heard and norm(heard) != norm(written) and norm(heard) not in {norm(h) for h in entry.heard} and len(entry.heard) < MAX_HEARD:
            entry.heard.append(" ".join(heard.split()).lower())
        await self._save(user_id, entry, existing)
        return entry

    async def _save(self, user_id: str, entry: DictEntry, existing: Fact | None) -> None:
        fact = existing or Fact(user_id=user_id, kind=FactKind.GENERAL, key=_key(entry.kind, entry.written), value="")
        fact.value = _pack(entry)
        await self.repos.facts.upsert(fact)

    async def note_heard(self, user_id: str, written: str, heard: str, *, confirmed: bool = False) -> str:
        """The user typed ``heard`` and it was ``written``. 'recorded' | 'promoted' | 'ignored'."""
        if not acceptable(heard) or norm(heard) == norm(written):
            return "ignored"
        facts = await self._facts(user_id)
        f = next((x for x in facts if (e := _unpack(x)) and norm(e.written) == norm(written)), None)
        if f is None:
            return "ignored"
        entry = _unpack(f)
        if entry is None:
            return "ignored"
        h = " ".join(heard.split()).lower()
        if h in entry.heard:
            return "ignored"
        entry.seen[h] = entry.seen.get(h, 0) + 1
        if confirmed or entry.seen[h] >= ACTIVE_AFTER:
            if len(entry.heard) >= MAX_HEARD:
                return "ignored"
            entry.heard.append(h)
            entry.seen.pop(h, None)
            await self._save(user_id, entry, f)
            return "promoted"
        await self._save(user_id, entry, f)
        return "recorded"

    async def remove(self, user_id: str, word: str) -> bool:
        n = norm(word)
        done = False
        for f in await self._facts(user_id):
            e = _unpack(f)
            if e is not None and (norm(e.written) == n or n in {norm(h) for h in e.heard}):
                if norm(e.written) == n:
                    done = bool(await self.repos.facts.delete(f.id)) or done
                else:
                    e.heard = [h for h in e.heard if norm(h) != n]
                    await self._save(user_id, e, f)
                    done = True
        return done

    async def clear(self, user_id: str) -> int:
        n = 0
        for f in await self._facts(user_id):
            n += int(bool(await self.repos.facts.delete(f.id)))
        return n


# ---------------------------------------------------------------- entities from everything Friday knows
def _address_pieces(text: str | None) -> list[str]:
    out = []
    for part in re.split(r"[,\n]", text or ""):
        p = " ".join(part.split())
        if 4 <= len(p) <= 30 and not re.search(r"\d{3,}", p) and len(p.split()) <= 3:
            out.append(p)
    return out


def entities_from_context(ctx: ConversationContext | None, entries: list[DictEntry] | None = None) -> list[Entity]:
    """The user's own entities, most specific first: dictionary, saved places, people, shops, profile city."""
    out: list[Entity] = [e.entity() for e in (entries or [])]
    if ctx is not None:
        for pl in ctx.places:
            if pl.ephemeral:
                continue
            out.append(Entity(pl.label, "place", "place", tuple(a.lower() for a in pl.aliases)))
            if pl.city:
                out.append(Entity(pl.city, "place", "place"))
            out.extend(Entity(p, "place", "place") for p in _address_pieces(pl.formatted_address or pl.address_text))
        for p in ctx.people:
            out.append(Entity(p.name, "person", "person", tuple(a.lower() for a in p.aliases)))
            first = p.name.split()[0] if p.name.split() else ""
            if first and first != p.name and len(first) >= 4:
                out.append(Entity(first, "person", "person", tuple(a.lower() for a in p.aliases)))
        seen: set[str] = set()
        for b in ctx.known_businesses:
            if b.name and b.name.lower() not in seen:
                seen.add(b.name.lower())
                out.append(Entity(b.name, "shop", "shop"))
        if ctx.profile and ctx.profile.city:
            out.append(Entity(ctx.profile.city, "place", "profile"))
    dedup: dict[tuple[str, str], Entity] = {}
    for e in out:
        dedup.setdefault((norm(e.written), e.kind), e)
    return [e for e in dedup.values() if norm(e.written)]


def home_area(ctx: ConversationContext | None) -> str | None:
    """Where 'near me' means: the user's Home place city/label, else the profile city."""
    if ctx is None:
        return None
    for pl in ctx.places:
        if not pl.ephemeral and pl.label.lower() in {"home", "ghar"} and (pl.city or pl.formatted_address):
            pieces = _address_pieces(pl.formatted_address)
            return pl.city or (pieces[-1] if pieces else None)
    if ctx.profile and ctx.profile.city:
        return ctx.profile.city
    for pl in ctx.places:
        if not pl.ephemeral and pl.city:
            return pl.city
    return None
