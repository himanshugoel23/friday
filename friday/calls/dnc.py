"""Global do-not-call registry for consumer calls (A5.3).

* Keyed by ``NumberHasher.hash`` (HMAC with the blind-index key): the plain number is never stored,
  so the table cannot be read back into a phone list. Same key => same hash for every user, so an
  opt-out made on one user's call protects the recipient from ALL users (cross-user).
* Entries are added from opt-out events (the callee said so on a call, or a wrong person was
  reached) and from a recipient's report. A user's own data erasure never removes an entry: it
  protects a third party, not the user.
* Checked before EVERY dial (``CallGate``). Export and delete exist for a recipient's
  data-subject request: ``export(number)`` returns what we hold about that number (the hash is
  recomputed from the number the requester gives us), ``delete(number)`` removes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from friday.calls.classify import normalise
from friday.calls.numbers import NumberHasher, canonical
from friday.core.clock import Clock, SystemClock

REASONS = frozenset({"opt_out_call", "wrong_person", "recipient_report", "user_request", "admin"})


@dataclass(frozen=True)
class DncEntry:
    number_hash: str
    reason: str
    source: str  # opaque event/source label, never a number or a user phone
    created_at: datetime


class DncStore(Protocol):
    async def add(self, entry: DncEntry) -> bool: ...  # False if already present
    async def get(self, number_hash: str) -> DncEntry | None: ...
    async def delete(self, number_hash: str) -> bool: ...
    async def count(self) -> int: ...


class MemoryDncStore:
    def __init__(self) -> None:
        self.rows: dict[str, DncEntry] = {}

    async def add(self, entry: DncEntry) -> bool:
        if entry.number_hash in self.rows:
            return False
        self.rows[entry.number_hash] = entry
        return True

    async def get(self, number_hash: str) -> DncEntry | None:
        return self.rows.get(number_hash)

    async def delete(self, number_hash: str) -> bool:
        return self.rows.pop(number_hash, None) is not None

    async def count(self) -> int:
        return len(self.rows)


class DncRegistry:
    def __init__(self, store: DncStore, hasher: NumberHasher, clock: Clock | None = None) -> None:
        self.store, self.hasher = store, hasher
        self.clock: Clock = clock or SystemClock()

    def _hash(self, number: str) -> str | None:
        e164 = canonical(number)
        return self.hasher.hash(e164) if e164 else None

    async def add(self, number: str, reason: str, source: str = "") -> bool:
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        h = self._hash(number)
        if h is None:
            return False
        return await self.store.add(DncEntry(h, reason, source[:60], self.clock.now()))

    async def add_hash(self, number_hash: str, reason: str, source: str = "") -> bool:
        if reason not in REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        return await self.store.add(DncEntry(number_hash, reason, source[:60], self.clock.now()))

    async def is_blocked(self, number: str) -> bool:
        h = self._hash(number)
        return h is not None and await self.store.get(h) is not None

    async def is_hash_blocked(self, number_hash: str) -> bool:
        return await self.store.get(number_hash) is not None

    async def export(self, number: str) -> list[dict[str, str]]:
        """What we hold about ``number`` (for the person it belongs to). Never the number itself."""
        h = self._hash(number)
        entry = await self.store.get(h) if h else None
        if entry is None:
            return []
        return [
            {
                "reason": entry.reason,
                "recorded_at": entry.created_at.isoformat(),
                "note": "stored only as a keyed hash; the number itself is not kept",
            }
        ]

    async def delete(self, number: str) -> bool:
        h = self._hash(number)
        return bool(h) and await self.store.delete(h)


# ------------------------------------------------------------------ opt-out phrase detection

_OPT_OUT = re.compile(
    "|".join(
        [
            r"\bdobara (call|phone|fone) (mat|na|nahi)\b",
            r"\bphir se (call|phone) (mat|na|nahi)\b",
            r"\b(call|phone|fone) (mat|na) (karo|karna|karein|kijiye|kijiyega|karenge|karna)\b",
            r"\bmujhe (call|phone) (mat|na) \w+\b",
            r"\bdo not call\b",
            r"\bdon t call (me )?(again|anymore)\b",
            r"\bstop calling\b",
            r"\bnever call (me )?again\b",
            r"\bremove (my )?(number|me)\b",
            r"\bdnd\b",
            r"\bnumber (hata|delete|remove|block)",
            r"\b(call|phone) band kar",
            r"\bcall karna band\b",
            r"\bmat (call|phone) karo\b",
            r"\bnahi chahiye (aapki|friday ki|ye) call\b",
            r"दोबारा (फोन|कॉल) (मत|न)",
            r"फोन मत करो",
            r"कॉल मत करो",
            r"नंबर हटा",
        ]
    ),
    re.I,
)
_WRONG_NUMBER = re.compile(
    r"\bwrong number\b|\bgalat number\b|\bgalat (insaan|aadmi|jagah)\b|\bye (woh|wo) nahi\b"
    r"|\bnahi hai yahan\b|गलत नंबर|\bnot (him|her|the person)\b|\bmain wo nahi hoon\b",
    re.I,
)


def detect_opt_out(text: str) -> bool:
    """Did the callee ask not to be called again? (Deterministic; W2 uses it live too.)"""
    return bool(_OPT_OUT.search(normalise(text)))


def detect_wrong_number(text: str) -> bool:
    return bool(_WRONG_NUMBER.search(normalise(text)))
