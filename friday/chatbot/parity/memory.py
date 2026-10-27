"""Item 2: "what do you remember about me" recap with a numbered list, and "forget" commands.

Works against a small store port, so tests use an in-memory fake and the service can adapt the real
memory service. The recap is numbered so "forget 2" is unambiguous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from friday.chatbot.parity import copy

_I = re.IGNORECASE
RECAP = re.compile(
    r"^\W*(?:what\s+(?:all\s+)?do\s+you\s+(?:remember|know)\s+about\s+me|"
    r"mere\s+baare\s+(?:mein|me)\s+kya\s+(?:kya\s+)?(?:yaad|pata)\s+hai|meri\s+memory|show\s+my\s+memory)\W*$",
    _I,
)
FORGET = re.compile(r"^\W*(?:forget|bhool\s+jao|bhul\s+jao)\s+(?P<what>all|everything|sab|\d{1,3})\W*$", _I)


@dataclass(frozen=True)
class MemoryItem:
    id: str
    text: str


class MemoryStore(Protocol):
    async def list_items(self, user_id: str) -> list[MemoryItem]: ...
    async def forget(self, user_id: str, item_id: str) -> bool: ...
    async def forget_all(self, user_id: str) -> int: ...


async def handle(store: MemoryStore, user_id: str, text: str, lang: str = "hinglish") -> str | None:
    """A reply, or None when the message is not a recap/forget command."""
    t = " ".join((text or "").split())
    if RECAP.match(t):
        items = await store.list_items(user_id)
        if not items:
            return copy.line("memory_empty", lang)
        rows = "\n".join(f"{i}. {it.text}" for i, it in enumerate(items, 1))
        return f"{copy.line('memory_head', lang)}\n{rows}\n{copy.line('memory_offer', lang)}"
    m = FORGET.match(t)
    if not m:
        return None
    what = m.group("what").lower()
    if what in ("all", "everything", "sab"):
        await store.forget_all(user_id)
        return copy.line("memory_forgot_all", lang)
    items = await store.list_items(user_id)
    n = int(what)
    if not 1 <= n <= len(items):
        return copy.line("memory_unknown", lang)
    item = items[n - 1]
    if not await store.forget(user_id, item.id):
        return copy.line("memory_unknown", lang)
    return copy.line("memory_forgot", lang, what=item.text)
