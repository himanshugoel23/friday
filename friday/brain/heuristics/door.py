"""Front door, deterministic side of a conversational turn.

* ``next_turn`` is the fake LLM's ``call_turn`` answer for the front door AND the fallback when
  the real model's output is missing / invalid: the existing deterministic lines, in an order
  that matches the live design (what do you need -> name -> consent -> request).
* ``scenarios_for`` picks which few-shot examples are worth their tokens this turn.
* ``sanitize`` bounds whatever a model returned (length, slot shape) before code looks at it.

The SAFETY decisions (consent, read-back, no task before both) are NOT here: they are made by
the call loop in ``friday/voice/frontdoor.py``, whatever this returns.
"""

from __future__ import annotations

import re
from typing import Any

from friday.brain import frontdoor as fd
from friday.core.models import Language

from ..schemas import DoorAction, DoorTurnOut

_REQUEST_WORDS = re.compile(
    r"\b(book|call|find|order|get|cancel|check|ask|arrange|schedule|reserve|remind|need|want|"
    r"chahiye|chahie|karo|karna|kar do|kardo|dhundo|batao|bata do|status|update|appointment|"
    r"haircut|table|cab|plumber|doctor|quote|price|kal|aaj|parso|tomorrow|today|tonight)\b|"
    r"बुक|कॉल|चाहिए|करना|करो|कल|आज|अपॉइंटमेंट",
    re.I,
)
_NAME_PHRASE = re.compile(
    r"\b(my\s+name|name\s+is|mera\s+naam|mera\s+nam|this\s+is|i\s+am|i'?m|call\s+me)\b|मेरा\s+नाम",
    re.I,
)
_ASKED_NAME = re.compile(r"\b(naam|name)\b|नाम", re.I)
_CHANGE_MIND = re.compile(
    r"\b(actually|instead|rather|wait|ruko|nahi\s+nahi|no\s+no|change|badal|scratch\s+that)\b|रुको",
    re.I,
)

MAX_SAY = 280
MAX_REQUEST = 240


def looks_like_request(text: str) -> bool:
    t = (text or "").strip()
    return len(t.split()) >= 3 or bool(_REQUEST_WORDS.search(t))


def _bare_name(text: str) -> str | None:
    """A name when the caller clearly gave one: 'Asha', 'my name is Priya Nair'."""
    name = fd.extract_name(text)
    if name is None:
        return None
    if _NAME_PHRASE.search(text) or len(name.split()) <= 2:
        return name
    return None


def friday_asked_name(recent: list[dict[str, Any]]) -> bool:
    return any(t.get("who") == "friday" and _ASKED_NAME.search(t.get("text", "")) for t in recent)


def scenarios_for(payload: dict[str, Any]) -> list[str]:
    """Which example scenarios fit this turn (cheap rules; the order is the priority)."""
    slots = payload.get("slots") or {}
    door = payload.get("door") or {}
    heard = payload.get("heard") or ""
    out: list[str] = []
    if fd.asks_if_bot(heard):
        out.append("human")
    if fd.asks_who(heard):
        out.append("capabilities")
    if fd.wants_to_end(heard):
        out.append("goodbye")
    if _CHANGE_MIND.search(heard):
        out.append("change_mind")
    if not door.get("can_call_businesses", True) and looks_like_request(heard):
        out.append("pilot_refusal")
    if len(heard.split()) <= 1 and not fd.yes_no(heard):
        out.append("unclear")
    if slots.get("request") and not slots.get("consented"):
        out.append("consent")
    if door.get("known"):
        out.append("returning")
    if not slots.get("request"):
        out.append("first_request" if looks_like_request(heard) else "opening")
    if not slots.get("name"):
        out.append("name")
    return list(dict.fromkeys(out))


def sanitize(out: DoorTurnOut) -> DoorTurnOut:
    say = re.sub(r"\s+", " ", out.say or "").strip()[:MAX_SAY]
    name = (out.name or "").strip()[:40] or None
    request = re.sub(r"\s+", " ", out.request or "").strip()[:MAX_REQUEST] or None
    return DoorTurnOut(
        say=say, action=out.action, name=name, language=out.language, request=request
    )


def next_turn(p: dict[str, Any]) -> DoorTurnOut:
    """The deterministic turn: same inputs, same output."""
    door = p.get("door") or {}
    slots = p.get("slots") or {}
    heard = (p.get("heard") or "").strip()
    recent = p.get("recent") or []
    lang = Language(door.get("reply_language") or "hinglish")
    consented = bool(slots.get("consented"))
    name = slots.get("name")
    request = slots.get("request")

    if fd.asks_who(heard) and len(heard.split()) <= 8:
        key = "capabilities" if door.get("can_call_businesses", True) else "capabilities_pilot"
        return DoorTurnOut(say=fd.line(key, lang))

    last_friday = next((t for t in reversed(recent) if t.get("who") == "friday"), None)
    asked_now = bool(last_friday and _ASKED_NAME.search(last_friday.get("text", "")))
    new_name = None
    phrased = bool(_NAME_PHRASE.search(heard))
    may_be_name = not name and (not request or asked_now or phrased)
    if may_be_name and not (request and looks_like_request(heard) and not phrased):
        new_name = _bare_name(heard)
    named = new_name or name

    if consented:
        if looks_like_request(heard) or len(heard.split()) >= 2:
            return DoorTurnOut(action=DoorAction.CONFIRM_REQUEST, request=heard)
        return DoorTurnOut(say=fd.line("didnt_catch", lang))

    if new_name and not request:
        return DoorTurnOut(say=fd.line("name_ack", lang, name=new_name), name=new_name)

    new_request = None
    if new_name is None and (looks_like_request(heard) or (request and len(heard.split()) >= 2)):
        # the latest request-like words win; a changed mind replaces the old request, a bare
        # extra detail ("Looks Unisex") is added to it
        replace = not request or _CHANGE_MIND.search(heard)
        new_request = heard if replace else f"{request}. {heard}"
    req = new_request or request

    if req:
        if not named and not friday_asked_name(recent) and not slots.get("consent_asked"):
            return DoorTurnOut(say=fd.line("ask_name_natural", lang), request=req)
        return DoorTurnOut(action=DoorAction.ASK_CONSENT, request=req, name=new_name)

    return DoorTurnOut(say=fd.line("ask_need", lang) if len(heard.split()) <= 1
                       else fd.line("didnt_catch", lang))
