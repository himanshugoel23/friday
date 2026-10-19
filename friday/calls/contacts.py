"""Per-user contact book for calls (A2.1). No phone-book sync: a contact appears only when the
user shares a contact card or types a number. The number is stored encrypted (the column type
uses the existing AES-GCM field encryption) next to a keyed hash used for lookups. Every query is
scoped by ``user_id``: one user's book is never visible to another.

``resolve`` returns found / ambiguous / none / number; a number the user typed or a contact never
used before must be CONFIRMED BACK ("ends in 3210, right?") before the first call; the gate asks
if that has not happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from friday.calls import copy
from friday.calls.classify import normalise
from friday.calls.numbers import NumberHasher, canonical, digits_of, is_emergency
from friday.core.clock import Clock, SystemClock, utcnow
from friday.core.models import new_id

RELATION_WORDS: dict[str, frozenset[str]] = {
    "mother": frozenset({"mummy", "mom", "maa", "ma", "mother", "amma", "mummy ji", "mataji"}),
    "father": frozenset({"papa", "dad", "pitaji", "father", "baba", "abbu", "pappa"}),
    "brother": frozenset({"bhaiya", "bhai", "brother", "bhaiyya"}),
    "sister": frozenset({"didi", "behen", "behan", "sister", "di"}),
    "wife": frozenset({"wife", "patni", "biwi"}),
    "husband": frozenset({"husband", "pati"}),
    "friend": frozenset({"dost", "friend", "yaar"}),
}
_HONORIFICS = re.compile(r"\b(ji|sir|madam|saab|sahab|uncle|aunty|auntie)\b")


@dataclass
class Contact:
    user_id: str
    name: str
    number: str = field(repr=False)  # E.164
    number_hash: str
    nicknames: list[str] = field(default_factory=list)
    relationship: str | None = None
    confirmed_at: datetime | None = None
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)

    @property
    def confirmed(self) -> bool:
        return self.confirmed_at is not None

    def last4(self) -> str:
        return digits_of(self.number)[-4:]


class ContactStore(Protocol):
    async def list_for_user(self, user_id: str) -> list[Contact]: ...
    async def get(self, user_id: str, contact_id: str) -> Contact | None: ...
    async def find_by_hash(self, user_id: str, number_hash: str) -> Contact | None: ...
    async def save(self, contact: Contact) -> Contact: ...
    async def delete(self, user_id: str, contact_id: str) -> bool: ...


class MemoryContactStore:
    def __init__(self) -> None:
        self._rows: dict[str, Contact] = {}

    async def list_for_user(self, user_id: str) -> list[Contact]:
        return [c for c in self._rows.values() if c.user_id == user_id]

    async def get(self, user_id: str, contact_id: str) -> Contact | None:
        c = self._rows.get(contact_id)
        return c if c and c.user_id == user_id else None

    async def find_by_hash(self, user_id: str, number_hash: str) -> Contact | None:
        return next(
            (
                c
                for c in self._rows.values()
                if c.user_id == user_id and c.number_hash == number_hash
            ),
            None,
        )

    async def save(self, contact: Contact) -> Contact:
        self._rows[contact.id] = contact
        return contact

    async def delete(self, user_id: str, contact_id: str) -> bool:
        c = await self.get(user_id, contact_id)
        if c is None:
            return False
        del self._rows[contact_id]
        return True


@dataclass
class Resolution:
    status: str  # found | ambiguous | none | number | invalid
    contact: Contact | None = None
    candidates: list[Contact] = field(default_factory=list)
    number: str | None = field(default=None, repr=False)  # a number the user typed (E.164)

    @property
    def needs_confirmation(self) -> bool:
        if self.status == "found":
            return not (self.contact and self.contact.confirmed)
        return self.status == "number"


def _clean(ref: str) -> str:
    return _HONORIFICS.sub("", normalise(ref)).strip()


def _relation_of(word: str) -> str | None:
    return next((rel for rel, words in RELATION_WORDS.items() if word in words), None)


class ContactBook:
    def __init__(
        self, store: ContactStore, hasher: NumberHasher, clock: Clock | None = None
    ) -> None:
        self.store, self.hasher = store, hasher
        self.clock: Clock = clock or SystemClock()

    async def add(
        self,
        user_id: str,
        name: str,
        number: str,
        *,
        nicknames: list[str] | tuple[str, ...] = (),
        relationship: str | None = None,
        confirmed: bool = False,
    ) -> Contact:
        if is_emergency(number):
            raise ValueError("emergency numbers cannot be saved as contacts")
        e164 = canonical(number)
        if e164 is None:
            raise ValueError("not a dialable phone number")
        h = self.hasher.hash(e164)
        existing = await self.store.find_by_hash(user_id, h)
        names = [normalise(n) for n in nicknames if n.strip()]
        if existing:  # same number again: update the labels, keep confirmation
            existing.name = name.strip() or existing.name
            existing.nicknames = sorted(set(existing.nicknames) | set(names))
            existing.relationship = relationship or existing.relationship
            return await self.store.save(existing)
        c = Contact(
            user_id=user_id,
            name=name.strip(),
            number=e164,
            number_hash=h,
            nicknames=names,
            relationship=relationship,
            confirmed_at=self.clock.now() if confirmed else None,
        )
        return await self.store.save(c)

    async def confirm(self, user_id: str, contact_id: str) -> Contact | None:
        c = await self.store.get(user_id, contact_id)
        if c is None:
            return None
        c.confirmed_at = self.clock.now()
        return await self.store.save(c)

    async def remove(self, user_id: str, contact_id: str) -> bool:
        return await self.store.delete(user_id, contact_id)

    async def resolve(self, user_id: str, ref: str) -> Resolution:
        """Who does the user mean by ``ref`` ("mummy", "Sharma ji", "98765 43210")?"""
        if re.search(r"\d{5,}", ref) or is_emergency(ref):
            e164 = canonical(ref)
            if e164 is None:
                return Resolution("invalid")
            known = await self.store.find_by_hash(user_id, self.hasher.hash(e164))
            if known:
                return Resolution("found", contact=known)
            return Resolution("number", number=e164)
        want = _clean(ref)
        if not want:
            return Resolution("none")
        want_rel = _relation_of(want)
        scored: list[tuple[int, Contact]] = []
        for c in await self.store.list_for_user(user_id):
            score = self._score(c, want, want_rel)
            if score:
                scored.append((score, c))
        if not scored:
            return Resolution("none")
        best = max(s for s, _ in scored)
        top = [c for s, c in scored if s == best]
        if len(top) == 1:
            return Resolution("found", contact=top[0], candidates=top)
        return Resolution("ambiguous", candidates=top)

    @staticmethod
    def _score(c: Contact, want: str, want_rel: str | None) -> int:
        name = _clean(c.name)
        nicks = {_clean(n) for n in c.nicknames}
        if want == name or want in nicks:
            return 4
        if want_rel and c.relationship and _relation_of(_clean(c.relationship)) == want_rel:
            return 3
        if want_rel and c.relationship and _clean(c.relationship) == want_rel:
            return 3
        tokens = set(name.split()) | {t for n in nicks for t in n.split()}
        if want in tokens:
            return 2
        if len(want) >= 3 and (name.startswith(want) or any(n.startswith(want) for n in nicks)):
            return 1
        return 0

    # ------------------------------------------------------------------ user-facing prompts
    @staticmethod
    def disambiguation_options(candidates: list[Contact]) -> str:
        """Names with the last 4 digits, never full numbers: "Rakesh (…3210) / Anil (…8841)"."""
        return " / ".join(f"{c.name} (…{c.last4()})" for c in candidates)

    @staticmethod
    def ask_which(ref: str, candidates: list[Contact], lang: str = copy.DEFAULT_LANGUAGE) -> str:
        return copy.line(
            "ask_which_contact",
            lang,
            ref=ref,
            options=ContactBook.disambiguation_options(candidates),
        )

    @staticmethod
    def confirm_number_back(name: str, number: str, lang: str = copy.DEFAULT_LANGUAGE) -> str:
        return copy.line("confirm_number_back", lang, name=name, masked=digits_of(number)[-4:])
