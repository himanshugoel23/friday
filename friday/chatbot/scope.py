"""Is this message outside what Friday is for? And masking text before it is stored.

Friday answers about the user's own world (calls, cards and bills, their day, vendors) and politely
redirects general-knowledge or off-topic questions ("main aapke kaam ke liye hoon"). The test is
deliberately narrow and rule-based: a message is OUT only when it looks like a general-knowledge or
entertainment ask AND carries no word from Friday's own world. Everything else (including every
doubt) is left to the existing flows and the brain, so a real request is never redirected.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE

# words from Friday's own world: their presence always means "in scope" (or at least "not ours to
# redirect")
IN_SCOPE = re.compile(
    r"\b(calls?|calling|called|phone|fone|ring|missed|reminders?|remind|yaad|bills?|cards?|bachat|"
    r"savings?|save|meeting|interview|appointment|booking|book|salon|parlour|haircut|plumber|"
    r"electrician|carpenter|painter|mechanic|doctor|clinic|hotel|taxi|cab|order|delivery|quotes?|"
    r"vendor|contact|number|location|ghar|office|google|calendar|gmail|delete|forget|bhool|menu|"
    r"help|stop|human|support|mummy|papa|bhaiya|didi|wife|husband|rent|emi|loan|insurance|"
    r"recharge|ticket|flight|train|bus)\b|"
    r"कॉल|फोन|बिल|कार्ड|रिमाइंडर|याद",
    _I,
)


# general knowledge / entertainment / homework: the narrow list of "this is not ours"
_OUT_PATTERNS = [
    r"\b(?:who|what|which)\s+(?:is|are|was|were)\s+(?:the\s+)?(?:capital|president|prime\s+minister|"
    r"population|meaning|full\s+form|speed|height|distance|currency)\b",
    r"\bcapital\s+of\b",
    r"\b(?:prime\s+minister|president|chief\s+minister)\s+of\b",
    r"\bwho\s+(?:is|was|invented|discovered|wrote|won|painted|founded)\b",
    r"\b(?:meaning|full\s+form)\s+of\b",
    r"\b(?:tell|say|sunao|suna\s+do|sunao\s+koi)\b.{0,15}\b(?:joke|chutkula|shayari|poem|story|kahani|kavita)\b",
    r"\b(?:joke|chutkula|shayari|kavita|poem|riddle|paheli)\b",
    r"\bwrite\s+(?:me\s+)?(?:a|an|the)?\s*(?:poem|essay|story|code|program|song|letter|email)\b",
    r"\b(?:essay|assignment|homework|code\s+in|python\s+program|javascript)\b",
    r"\b(?:translate|translation)\b",
    r"\b(?:cricket|ipl|world\s+cup|match|score|football|fifa)\b.{0,20}\b(?:score|result|jeeta|jeet|kaun|who|winner|live)\b",
    r"\b(?:horoscope|rashifal|rashi|kundli|zodiac)\b",
    r"\b(?:news|samachar|khabar|headlines)\b",
    r"\b(?:stock|share|sensex|nifty|bitcoin|crypto)\s+(?:price|rate|today|ka)\b",
    r"\b(?:recipe|recipes|banane\s+ki\s+vidhi|kaise\s+banate)\b",
    r"\b(?:weather|mausam|temperature|barish)\b",
    r"\b(?:movie|film|song|gaana|gana|web\s*series)\b.{0,20}\b(?:suggest|recommend|batao|best|konsi|kaun\s+si)\b",
    r"\b\d+\s*[\+\-\*/x×÷]\s*\d+\s*(?:=|kitna|equals|\?)",
    r"\bkitne\s+(?:hote|hoti|hain)\s+hain\b",
    r"\b(?:kaun\s+(?:hai|tha|the)|kya\s+hota\s+hai|kya\s+hai)\b.{0,25}\b(?:pradhan\s*mantri|rashtrapati|"
    r"duniya|world|universe|bharat|india|chand|sooraj|suraj)\b",
    r"\bkisne\s+(?:banaya|likha|khoja|jeeta)\b",
    r"\b(?:chatgpt|gemini|siri|alexa)\b",
    r"\b(?:i\s+am\s+bored|bore\s+ho\s+raha|bore\s+ho\s+rahi|mujhse\s+baat\s+karo|"
    r"tum\s+kaun\s+ho\s+asli|are\s+you\s+human)\b",
]
_OUT = [re.compile(p, _I) for p in _OUT_PATTERNS]
# "weather" is in the list but a weather/forecast question for a trip is the brain's job when it
# names a place or a plan; only the bare question is redirected
_WEATHER_WITH_PLAN = re.compile(r"\b(?:trip|travel|flight|train|plan|jaana|jana)\b", _I)


def is_out_of_scope(text: str | None) -> bool:
    """True only for a clear general-knowledge or entertainment ask with nothing of Friday's own
    world in it."""
    t = (text or "").strip()
    if not t or len(t) > 240 or len(t.split()) < 2:
        return False
    if IN_SCOPE.search(t):
        return False
    if any(p.search(t) for p in _OUT):
        return not _WEATHER_WITH_PLAN.search(t)
    return False


# ---------------------------------------------------------------------- masking for storage
_PHONE_LIKE = re.compile(r"(?<!\w)\+?\d[\d\s().\-]{5,}\d(?!\w)")
_LONG_DIGITS = re.compile(r"\d{4,}")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_URL = re.compile(r"https?://\S+|www\.\S+", _I)


def mask_numbers(text: str | None, limit: int = 200) -> str:
    """Text safe to keep for the founder's review: phone-like numbers, long digit runs (card, OTP,
    account), emails and links are replaced; the length is capped."""
    t = " ".join((text or "").split())
    t = _URL.sub("<link>", t)
    t = _EMAIL.sub("<email>", t)
    t = _PHONE_LIKE.sub("<number>", t)
    t = _LONG_DIGITS.sub("<number>", t)
    return t if len(t) <= limit else t[: limit - 1] + "…"
