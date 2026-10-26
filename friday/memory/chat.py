# ruff: noqa: E501
"""Chat commands for the memory list: "what do you remember about me" and "forget <item>"."""

from __future__ import annotations

import re
from typing import Any

from friday.memory.service import MemoryService, format_list

_I = re.IGNORECASE
LIST = re.compile(
    r"^\W*(?:what\s+do\s+you\s+(?:remember|know)\s+about\s+me|what\s+(?:all\s+)?do\s+you\s+remember"
    r"\s+about\s+me|mere\s+baare\s+(?:mein|me)\s+(?:kya|tumhe\s+kya)\s+(?:yaad|pata)\s+hai|"
    r"mere\s+baare\s+mein\s+kya\s+kya\s+yaad\s+hai|meri\s+memory|show\s+my\s+memory|"
    r"tumhe\s+mere\s+baare\s+mein\s+kya\s+yaad\s+hai)\W*$",
    _I,
)
FORGET = re.compile(
    r"^\W*(?:forget|bhool\s+jao|bhool\s+ja|bhul\s+jao)\s+(?:about\s+)?(?P<what>.{2,60}?)\W*$", _I
)


async def handle(repos: Any, clock: Any, user_id: str, text: str, lang: str = "hinglish"
                 ) -> str | None:
    """A reply, or ``None`` when the message is not about the memory list (so other handlers run)."""
    t = " ".join((text or "").split())
    svc = MemoryService(repos, clock)
    if LIST.match(t):
        return format_list(await svc.remember_list(user_id), lang)
    m = FORGET.match(t)
    if not m:
        return None
    needle = m.group("what").lower()
    hits = [i for i in await svc.remember_list(user_id)
            if i.kind in ("alias", "fact", "episode") and needle in i.text.lower()]
    if len(hits) != 1:
        return None  # none, or several: let the existing "forget" flow ask or handle events
    if await svc.forget(user_id, hits[0].id):
        return {"hinglish": "Theek hai, bhool gayi.", "hi": "ठीक है, भूल गई।",
                "en": "Okay, forgotten."}.get(lang, "Theek hai, bhool gayi.")
    return None
