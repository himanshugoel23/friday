"""Simulated small-business replies from a ``simworld`` persona (AI-13 fake path).
Deterministic: same persona + transcript -> same reply."""

from __future__ import annotations

from typing import Any

from friday.core.models import Language

from ..schemas import BusinessReplyOut
from ..textutil import extract_amounts, has_any, norm


def _lang(persona: dict[str, Any], turn: int) -> Language:
    lang = Language(persona.get("language") or "hinglish")
    switch = persona.get("switches_to")
    if switch and turn >= 2:
        return Language(switch)
    return lang


def reply(business: dict[str, Any], transcript: list[dict[str, Any]]) -> BusinessReplyOut:
    persona = business.get("persona") or {}
    friday_turns = [t for t in transcript if t.get("speaker") == "friday"]
    biz_turns = [t for t in transcript if t.get("speaker") == "callee"]
    turn = len(biz_turns)
    lang = _lang(persona, turn)
    en = lang in (Language.EN, Language.KN, Language.TA, Language.TE, Language.ML)
    last = norm(friday_turns[-1]["text"]) if friday_turns else ""

    def r(en_text: str, hi_text: str, *, hangup: bool = False) -> BusinessReplyOut:
        return BusinessReplyOut(text=en_text if en else hi_text, language=lang, hangup=hangup)

    limit = persona.get("hangs_up_after_turns")
    if limit and turn >= limit:
        return r("Sorry, I have to go.", "Achha, baad mein baat karte hain.", hangup=True)
    if not friday_turns or turn == 0:
        return BusinessReplyOut(text=persona.get("greeting") or "Hello?", language=lang)
    if persona.get("asks_if_ai") and turn == 1:
        return r("Wait - are you a robot?", "Ek minute - aap robot ho kya?")
    prices: dict[str, int] = persona.get("prices") or {}
    slots: list[str] = persona.get("slots") or []
    stock: dict[str, bool] = persona.get("stock") or {}
    said = " ".join(norm(t["text"]) for t in friday_turns)
    mentioned = [amount for name, amount in prices.items() if norm(name) in said]
    base = mentioned[0] if mentioned else (min(prices.values()) if prices else None)
    if has_any(last, ("discount", "kam kar", "best price", "could you do", "kar sakte hain kya")):
        pct = int(persona.get("max_discount_pct") or 0)
        if pct and base:
            offered = extract_amounts(last)
            floor = int(round(base * (1 - pct / 100)))
            new = max(floor, min(offered) if offered else floor)
            return r(f"Okay, {new} final.", f"Theek hai, {new} final.")
        return r("Sorry, price is fixed.", "Nahi, price fixed hai.")
    if has_any(last, ("confirm kar dijiye", "please confirm", "confirm it", "sahi hai")):
        return r("Yes, done. Please come 10 minutes early.",
                 "Haan, done. 10 minute pehle aa jaana.")
    if has_any(last, ("call back", "hold kar sakte", "hold it", "rakh sakte")):
        hours = persona.get("holds_room_hours")
        return r(f"Okay, I'll hold it{' for ' + str(hours) + ' hours' if hours else ''}.",
                 f"Theek hai, rakh deta hoon{' ' + str(hours) + ' ghante' if hours else ''}.")
    for item, ok in stock.items():
        if item in last:
            return r("Yes, we have it in stock." if ok else "Sorry, out of stock.",
                     "Haan, hai." if ok else "Nahi, khatam hai.")
    if has_any(last, ("price", "kitna", "cost", "charge", "rate", "fees")) and prices:
        name, amount = min(prices.items(), key=lambda kv: (norm(kv[0]) not in said, kv[1]))
        return r(f"{name} is {amount} rupees.", f"{name} ka {amount} lagega.")
    if has_any(last, ("slot", "available", "time", "kab", "when", "room")) and slots:
        price = f" {base} rupees." if base else ""
        return r(f"We have {' or '.join(slots[:2])}.{price}",
                 f"{' ya '.join(slots[:2])} hai.{(' ' + str(base) + ' lagega.') if base else ''}")
    if has_any(last, ("include", "shaamil")):
        notes = persona.get("notes") or ["basic service"]
        return r(f"That includes {notes[0]}.", f"Usme {notes[0]} included hai.")
    return r("Okay, tell me.", "Haan ji, boliye.")
