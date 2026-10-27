# ruff: noqa: E501
"""Every USER-FACING WhatsApp text and button of the urgent-call escalation.
STATUS: PENDING_FOUNDER_APPROVAL for all of them (same pattern as friday/receptionist/copy.py).
The spoken line is in ``lines.py`` and also needs audio approval.
"""

from __future__ import annotations

import re

LINE_STATUS = "PENDING_FOUNDER_APPROVAL"
LANGS = ("hinglish", "en")

BUTTONS = {  # titles are <= 20 characters (WhatsApp limit)
    "ack": {"hinglish": "Acknowledge", "en": "Acknowledge"},
}

TEXTS: dict[str, dict[str, str]] = {
    "alert.hint": {
        "hinglish": "Agar aap {minutes} minute mein Acknowledge nahi karenge, toh Friday aapko call karegi.",
        "en": "If you do not tap Acknowledge within {minutes} minutes, Friday will call you.",
    },
    "alert.hint.emergency": {
        "hinglish": "Yeh emergency lag rahi hai. Agar aap {minutes} minute mein Acknowledge nahi karenge, toh Friday aapko call karegi (raat mein bhi).",
        "en": "This looks like an emergency. If you do not tap Acknowledge within {minutes} minutes, Friday will call you (even at night).",
    },
    "reply.ack": {
        "hinglish": "Theek hai, acknowledge ho gaya. Ab main call nahi karungi.",
        "en": "Okay, acknowledged. I will not call you.",
    },
    "reply.stale": {
        "hinglish": "Yeh alert ab active nahi hai.",
        "en": "That alert is no longer active.",
    },
    "exhausted": {
        "hinglish": "Maine aapko {n} baar call kiya, par baat nahi ho payi. Upar wala urgent message dekh lijiye.",
        "en": "I called you {n} time(s) but could not reach you. Please look at the urgent message above.",
    },
    "optin.on": {
        "hinglish": "Theek hai. Jab koi urgent call aayegi aur aap {minutes} minute mein Acknowledge nahi karenge, Friday sirf aapke apne number par call karegi. Band karne ke liye likhiye: urgent call band.",
        "en": "Okay. When an urgent call comes in and you do not tap Acknowledge within {minutes} minutes, Friday will call only your own number. To stop, write: urgent call off.",
    },
    "optin.off": {
        "hinglish": "Theek hai, ab Friday urgent call ke liye aapko call nahi karegi. WhatsApp alert aata rahega.",
        "en": "Okay, Friday will no longer call you for urgent calls. You will still get the WhatsApp alert.",
    },
    "optin.minutes": {
        "hinglish": "Theek hai, ab {minutes} minute baad call karungi.",
        "en": "Okay, I will call after {minutes} minutes.",
    },
    "optin.unavailable": {
        "hinglish": "Urgent call ki suvidha abhi chalu nahi hai.",
        "en": "Urgent-call escalation is not available right now.",
    },
    "optin.status.on": {
        "hinglish": "Urgent call chalu hai: {minutes} minute mein Acknowledge nahi kiya toh Friday aapko call karegi (max {calls} baar).",
        "en": "Urgent call is on: if you do not acknowledge within {minutes} minutes Friday will call you (at most {calls} times).",
    },
    "optin.status.off": {
        "hinglish": "Urgent call band hai.",
        "en": "Urgent call is off.",
    },
}

_SLOT = re.compile(r"\{(\w+)\}")


def t(key: str, lang: str = "hinglish", **slots: object) -> str:
    text = TEXTS[key][lang if lang in LANGS else "hinglish"]
    return _SLOT.sub(lambda m: str(slots[m.group(1)]), text)


def button_title(action: str, lang: str = "hinglish") -> str:
    return BUTTONS[action][lang if lang in LANGS else "hinglish"]


def all_texts() -> list[tuple[str, str, str]]:
    out = [(f"urgw.{k}.{lang}", lang, TEXTS[k][lang]) for k in TEXTS for lang in LANGS]
    out += [(f"urgw.button.{k}.{lang}", lang, BUTTONS[k][lang]) for k in BUTTONS for lang in LANGS]
    return out
