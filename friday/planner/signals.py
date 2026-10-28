# ruff: noqa: E501
"""Deterministic text signals shared by the heuristic decider and the policy guard.
English + Roman Hindi/Hinglish. Cheap, offline, no model."""

from __future__ import annotations

import re

_I = re.IGNORECASE

# named retailers / apps whose public pages show prices and stock
QUICK_COMMERCE = ("zepto", "blinkit", "instamart", "bigbasket", "big basket", "jiomart", "dunzo")
RETAILERS = (
    *QUICK_COMMERCE, "amazon", "flipkart", "myntra", "nykaa", "croma", "reliance digital", "dmart",
    "meesho", "zomato", "swiggy", "1mg", "pharmeasy", "netmeds", "bookmyshow", "makemytrip",
    "irctc", "uber", "ola", "rapido",
)  # fmt: skip
FOOD_APPS = ("zomato", "swiggy", "eatsure", "magicpin")

PRICE_RE = re.compile(
    r"\b(price|prices|rate|rates|cost|costs|kitne\s+ka|kitna|kitni|kitne|daam|dam|bhav|bhaav|mrp|"
    r"how\s+much|cheapest|sasta|offer|discount)\b",
    _I,
)
AVAIL_RE = re.compile(
    r"\b(in\s+stock|available|availability|stock|timing|timings|opening\s+hours|open\s+now|"
    r"closing\s+time|kab\s+tak\s+khula|review|reviews|rating|ratings|menu|delivery\s+time|eta)\b",
    _I,
)
CHECK_RE = re.compile(r"\b(check|find\s+out|look\s*up|search|dekho|dekh\s+do|bata\s+do|pata\s+karo)\b", _I)

KNOWLEDGE_RE = re.compile(
    r"^\s*(what\s+is|what\s+are|what's|who\s+is|who\s+was|when\s+did|why\s+(is|do|does)|how\s+(do|does|to)|"
    r"explain|define|meaning\s+of|translate|capital\s+of|kya\s+hota\s+hai|kya\s+hai|kaun\s+hai|"
    r"matlab\s+kya|kaise\s+(karte|kare|karein))\b|\bcapital\s+of\b",
    _I,
)

ORDER_RE = re.compile(r"\b(order|orders|mangwa|mangwao|mangwana|buy|khareed)\b|\bbook\s+a\s+(table|ticket|cab)\b", _I)
FOOD_RE = re.compile(r"\b(pizza|burger|biryani|food|khana|meal|lunch|dinner|breakfast|momos|thali|coffee|chai)\b", _I)

# a person at a local business is the only real source
LOCAL_RE = re.compile(
    r"\b(plumber|electrician|carpenter|painter|mechanic|ac\s+(repair|service)|pest\s+control|salon|barber|"
    r"parlour|parlor|spa|doctor|clinic|dentist|physio|lab\s+test|vet|tutor|trainer|gym|mover|movers|packers|"
    r"cleaner|maid|cook|driver|photographer|caterer|banquet|decorator|tailor|laundry|florist|"
    r"mistri|bijli\s*wala)\b",
    _I,
)
LOCAL_NEED_RE = re.compile(
    r"\b(find\s+me|get\s+me|need|want|send|book|booking|appointment|quote|quotes|tonight|today|tomorrow|"
    r"abhi|kal|aaj|chahiye|bulao|bhejo|dhundo|dhoondo|near\s+me|nearby)\b|paas\s+(mein|me)\b",
    _I,
)
EXPLICIT_CALL_RE = re.compile(
    r"\bcall\s+(them|him|her|the\s+(shop|store|vendor|place|restaurant|clinic)|and\s+(ask|check|book))\b|"
    r"\b(call|phone)\s+(karke|kar\s+ke)\b|\bcall\s+karke\b|\bphone\s+karke\b",
    _I,
)
PINCODE_RE = re.compile(r"(?<!\d)([1-9]\d{5})(?!\d)")

CALL_WORDS_RE = re.compile(
    r"\b(call|calls|calling|called|phone|ring|dial)\b|\b(call|phone|fone)\s+(karun|karungi|karna|karne|kar)\b",
    _I,
)


def retailer_in(text: str) -> str | None:
    low = text.lower()
    for name in RETAILERS:
        if re.search(rf"\b{re.escape(name)}\b", low):
            return name
    return None


def is_quick_commerce(retailer: str | None) -> bool:
    return bool(retailer) and any(q in (retailer or "") for q in QUICK_COMMERCE)


def has_lookup_signal(text: str) -> bool:
    """Public pages can answer: a price / availability / timing / review question."""
    return bool(PRICE_RE.search(text) or AVAIL_RE.search(text))


def has_local_signal(text: str) -> bool:
    return bool(LOCAL_RE.search(text) and (LOCAL_NEED_RE.search(text) or not has_lookup_signal(text)))


def explicit_call_request(text: str) -> bool:
    return bool(EXPLICIT_CALL_RE.search(text))


def lookup_can_answer(text: str) -> bool:
    """True when a lookup is the right tool: a named retailer with a price/availability/check word,
    or a price / stock question with no local-service need. An explicit "call them" always wins."""
    if explicit_call_request(text):
        return False
    r = retailer_in(text)
    if r and (has_lookup_signal(text) or CHECK_RE.search(text)):
        return not (r in FOOD_APPS and ORDER_RE.search(text) and not PRICE_RE.search(text))
    return bool(has_lookup_signal(text) and not has_local_signal(text))


def pincode_in(text: str) -> str | None:
    m = PINCODE_RE.search(text)
    return m.group(1) if m else None


def mentions_call(text: str) -> bool:
    return bool(CALL_WORDS_RE.search(text or ""))
