# ruff: noqa: E501
"""Chat commands for the user's own dictionary (view / add / remove / delete all). Wording PENDING approval.

    my words | show my words | mere words        list
    add word|place|shop|name <X>                  add (e.g. "add place Sonipat")
    forget word <X> | remove word <X>             remove one
    forget all my words | delete my words         delete the whole dictionary

"what do you remember about me" / "forget <X>" (friday/memory/chat.py) already cover the same rows.
"""

from __future__ import annotations

import re
from typing import Any

from friday.speech.userdict import KINDS, UserDictionary

_I = re.IGNORECASE
LIST = re.compile(r"^\W*(?:my\s+words|show\s+my\s+words|mere\s+words|my\s+dictionary|meri\s+dictionary)\W*$", _I)
ADD = re.compile(r"^\W*(?:add|save|yaad\s+rakho)\s+(?P<kind>word|place|shop|name|person)\s+(?P<w>.{2,40}?)\W*$", _I)
REMOVE = re.compile(r"^\W*(?:forget|remove|delete|bhool\s+jao)\s+(?:the\s+)?word\s+(?P<w>.{2,40}?)\W*$", _I)
CLEAR = re.compile(r"^\W*(?:forget|delete|remove|clear|bhool\s+jao)\s+(?:all\s+)?(?:my\s+)?(?:words|dictionary)\W*$|^\W*delete\s+all\s+my\s+words\W*$", _I)

LINES = {
    "empty": {"en": "I have no saved words for you yet. Say 'add place <name>' to teach me one.",
              "hinglish": "Abhi aapke liye koi saved word nahi hai. 'add place <naam>' bolkar sikha sakte hain."},
    "header": {"en": "Words I know for you:", "hinglish": "Aapke liye yeh words yaad hain:"},
    "added": {"en": "Saved: {w}.", "hinglish": "Save kar liya: {w}."},
    "refused": {"en": "I can't save that one (it looks like a number or secret, or the list is full).",
                "hinglish": "Yeh save nahi kar sakti (number ya secret jaisa lag raha hai, ya list full hai)."},
    "removed": {"en": "Removed: {w}.", "hinglish": "Hata diya: {w}."},
    "missing": {"en": "I don't have {w} saved.", "hinglish": "{w} save nahi hai."},
    "cleared": {"en": "Done, all your saved words are deleted ({n}).", "hinglish": "Ho gaya, aapke saare saved words delete ({n})."},
}


def _line(key: str, lang: str, **kw: object) -> str:
    row = LINES[key]
    return row["en" if lang == "en" else "hinglish"].format(**kw)


async def handle(repos: Any, user_id: str, text: str, lang: str = "hinglish") -> str | None:
    t = " ".join((text or "").split())
    ud = UserDictionary(repos)
    if CLEAR.match(t):
        return _line("cleared", lang, n=await ud.clear(user_id))
    if LIST.match(t):
        rows = await ud.list(user_id)
        if not rows:
            return _line("empty", lang)
        body = "\n".join(f"- {e.written} ({e.kind})" + (f", also typed as: {', '.join(e.heard)}" if e.heard else "") for e in rows[:30])
        return f"{_line('header', lang)}\n{body}"
    if m := ADD.match(t):
        kind = {"name": "person"}.get(m.group("kind").lower(), m.group("kind").lower())
        entry = await ud.add(user_id, m.group("w"), kind if kind in KINDS else "word")
        return _line("added", lang, w=entry.written) if entry else _line("refused", lang)
    if m := REMOVE.match(t):
        w = m.group("w")
        return _line("removed", lang, w=w) if await ud.remove(user_id, w) else _line("missing", lang, w=w)
    return None
