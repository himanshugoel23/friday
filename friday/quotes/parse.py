# ruff: noqa: E501
"""Offline understanding of a WhatsApp salon request (English / Hindi / Hinglish).

Deterministic on purpose: it runs without an LLM key and the same way in tests. It extracts
services (only ones the salon playbook can say), who it is for, when, a budget, an explicit
"book it" intent and a location phrase. Anything it cannot find stays empty and the flow asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from friday.brain.lang import detect_language
from friday.brain.textutil import extract_budget, norm, parse_when
from friday.core.clock import IST, ensure_utc, to_ist
from friday.core.models import Language

SERVICE_PATTERNS: list[tuple[str, str]] = [
    ("hair spa", r"hair\s*spa|हेयर\s*स्पा"),
    ("hair colour", r"hair\s*colou?r|hair\s*dye|colou?ring|हेयर\s*कलर"),
    ("head massage", r"head\s*massage|champi|चम्पी|चंपी"),
    ("haircut", r"hair\s*cut(ting)?|cutting|baal\s*kat\w*|bal\s*kat\w*|हेयरकट|बाल\s*कट\w*"),
    ("beard trim", r"beard|dadhi|daadhi|दाढ़ी|दाढी|बीयर्ड"),
    ("shave", r"\bshav(e|ing)\b|शेव"),
    ("facial", r"facial|फेशियल"),
    ("manicure", r"manicure|मैनिक्योर"),
    ("pedicure", r"pedicure|पेडिक्योर"),
    ("waxing", r"\bwax(ing)?\b|वैक्सिंग"),
    ("threading", r"threading|थ्रेडिंग"),
    ("keratin", r"keratin|केराटिन"),
    ("massage", r"\bmassage\b|मसाज"),
]
SALON_WORDS = re.compile(
    r"salon|saloon|parlou?r|barber|beauty|पार्लर|सैलून|सलून|"
    + "|".join(p for _, p in SERVICE_PATTERNS),
    re.I,
)
VENUE_WORDS = re.compile(r"salon|saloon|parlou?r|barber|पार्लर|सैलून|सलून", re.I)
REQUEST_CUES = re.compile(
    r"chahiye|chaiye|karwana|karwani|karana|karna hai|kaatna|katwana|book|appointment|need|want|"
    r"looking|quote|rate|price|get a|i'?d like|चाहिए|करवाना|कटवाना|बुक",
    re.I,
)
QUOTE_WORDS = re.compile(
    r"quote|rate|price|kitna|kitne|charges?|bhav|cost|कोट|रेट|कीमत|कितना|कितने|चार्ज", re.I
)
CITY_WORDS = {
    "gurgaon": "gurgaon",
    "gurugram": "gurgaon",
    "ggn": "gurgaon",
    "gurgram": "gurgaon",
    "गुड़गांव": "gurgaon",
    "गुरुग्राम": "gurgaon",
    "गुड़गाँव": "gurgaon",
    "bangalore": "bangalore",
    "bengaluru": "bangalore",
    "blr": "bangalore",
    "bangaluru": "bangalore",
    "बेंगलुरु": "bangalore",
    "बैंगलोर": "bangalore",
    "बेंगलोर": "bangalore",
}
OTHER_CITIES = (
    "delhi|new delhi|noida|ghaziabad|faridabad|mumbai|bombay|pune|hyderabad|chennai|kolkata|"
    "ahmedabad|jaipur|lucknow|chandigarh|indore|kochi|surat|nagpur|bhopal|patna|mysore|mysuru|"
    "दिल्ली|नोएडा|मुंबई|पुणे|हैदराबाद|चेन्नई|कोलकाता"
)
OTHER_CITY_RE = re.compile(rf"(?<![\w]){OTHER_CITIES}(?![\w])", re.I)
_CITY_ALT = "|".join(sorted((re.escape(w) for w in CITY_WORDS), key=len, reverse=True))
CITY_RE = re.compile(rf"(?<![\w])({_CITY_ALT})(?![\w])", re.I)
_STOP_NAMES = {
    "kal", "aaj", "parso", "mujhe", "mera", "meri", "ek", "a", "the", "any", "best", "good",
    "nearby", "near", "please", "hi", "hello", "need", "want", "book", "find", "get", "looking",
    "aur", "ya", "sasta", "achha", "accha", "koi", "hey", "namaste", "ji", "mere", "apne",
    "kisi", "ladies", "gents", "unisex", "beauty", "hair",
}
NAMED_BUSINESS_RE = re.compile(
    r"\b((?:[A-Z][\w'&.-]*\s+){1,4})(?:Unisex\s+)?(?:Salon|Saloon|Parlou?r|Studio|Spa)\b"
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")

STOP_RE = re.compile(
    r"^\s*(stop|unsubscribe|stop all|band karo|band kar do|sab band|ruk jao|ruko|रुको|बंद करो|"
    r"बंद कर दो)\s*[.!]*\s*$",
    re.I,
)
CANCEL_RE = re.compile(
    r"^\s*(cancel|cancel karo|cancel kar do|rehne do|reh ne do|chhodo|mat karo|nahi chahiye|"
    r"no need|never mind|nevermind|रहने दो|कैंसल)\s*[.!]*\s*$",
    re.I,
)
NO_RE = re.compile(r"^\s*(no|nahi|nahin|nope|na|नहीं|ना)\s*[.!]*\s*$", re.I)
STATUS_RE = re.compile(
    r"^\s*(status|result|results|update|quotes?|kya hua|kya hua\?|kahan tak|any update|"
    r"stat|स्टेटस|क्या हुआ|रिज़ल्ट)\s*[?.!]*\s*$",
    re.I,
)
YES_RE = re.compile(
    r"^\s*(yes|y|yeah|yep|ok|okay|haan|han|ha|haa|ji|ji haan|haan ji|call karo|call kar do|"
    r"kar do|karo|theek hai|thik hai|sure|go ahead|हाँ|हां|ठीक है|कर दो|करो)\s*[.!]*\s*$",
    re.I,
)
CHANGE_RE = re.compile(
    r"^\s*(change|badlo|badal do|badal|doosre|dusre|dusra|doosra|other|others|another|"
    r"बदलो|दूसरे)\s*[.!]*\s*$",
    re.I,
)
SELF_RE = re.compile(r"\b(mere liye|meri|apne liye|for me|for myself|mujhe|myself|मेरे लिए)\b", re.I)
OTHER_RE = re.compile(
    r"\b(?:(?P<name>[A-Za-z]{2,15})\s+ke\s+liye|for\s+(?:my\s+)?(?P<name2>[A-Za-z]{2,15}))\b"
    r"|(?P<hname>[ऀ-ॿ]{2,15})\s+के\s+लिए",
    re.I,
)
SOMEONE_RE = re.compile(r"\b(kisi aur|kisi ke liye|someone else|somebody else|किसी और)\b", re.I)
RELATIONS = {
    "papa", "dad", "father", "mummy", "mom", "mother", "bhai", "brother", "behen", "bhabhi",
    "sister", "wife", "husband", "beta", "son", "daughter", "beti", "friend", "dost", "uncle",
    "chacha", "mama", "boss", "wifey", "bete", "patni", "pati", "पापा", "मम्मी", "भाई",
    "बहन", "बेटा", "बेटी", "दोस्त", "पत्नी", "पति",
}
_NOT_NAMES = {"me", "myself", "us", "you", "him", "her", "them", "the", "a", "an", "my", "self"}
BOOK_RE = re.compile(r"\b(book\s+(kar|karo|kardo|it|this|that)|pakka\s+kar|slot\s+book|book\s+kar)", re.I)


_NOISE = {
    "kal", "aaj", "parso", "shaam", "subah", "raat", "dopahar", "haircut", "parlour", "parlor",
    "salon", "saloon", "mein", "me", "in", "at", "near", "for", "a", "the", "chahiye", "hai",
    "hoon", "main", "mai", "i", "am", "karwana", "karna", "book", "beard", "trim", "facial",
    "tomorrow", "today", "evening", "morning", "need", "want", "pm", "baje", "and",
    "aur", "to", "ke", "ka", "ki", "se", "pas", "paas", "city", "please", "hair", "cut",
}
BAJE_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:baje|bje|बजे)", re.I)


@dataclass
class Parsed:
    lang: str = "hinglish"
    services: list[str] = field(default_factory=list)
    for_name: str | None = None
    for_other_unnamed: bool = False
    when_text: str | None = None
    when_start: datetime | None = None
    when_end: datetime | None = None
    exact_time: bool = False
    day_set: bool = False
    budget_inr: int | None = None
    book_intent: bool = False
    location_text: str | None = None
    city: str | None = None
    other_city: bool = False


def ui_lang(text: str | None, default: str = "hinglish") -> str:
    """en | hinglish | hi, mirroring how the user writes (script and word choice)."""
    if not text or not text.strip():
        return default
    lang = detect_language(text, Language.HINGLISH if default != "en" else Language.EN)
    if lang == Language.HI:
        return "hi"
    if lang == Language.EN:
        return "en"
    if lang == Language.HINGLISH:
        return "hi" if re.search(r"[ऀ-ॿ]", text) and not re.search(r"[A-Za-z]{3,}", text) else (
            "hinglish"
        )
    return "en"


def looks_like_request(text: str | None) -> bool:
    """A generic salon/parlour request (no named business, no phone number)."""
    if not text:
        return False
    if PHONE_RE.search(text):
        return False
    if not SALON_WORDS.search(text):
        return False
    if not VENUE_WORDS.search(text) and not REQUEST_CUES.search(text):
        return False  # "haan beard bhi": a service word alone is an answer, not a request
    for m in NAMED_BUSINESS_RE.finditer(text):
        words = [w for w in m.group(1).split() if w]
        if words and not all(w.lower().strip(".,") in _STOP_NAMES for w in words):
            return False
    return True


def find_services(text: str) -> list[str]:
    out: list[str] = []
    for name, pat in SERVICE_PATTERNS:
        if re.search(pat, text, re.I) and name not in out:
            out.append(name)
    if "head massage" in out and "massage" in out:
        out.remove("massage")
    return out


def _period_word(start_min: int | None) -> str:
    if start_min is None:
        return ""
    h = start_min // 60
    return "subah" if h < 12 else "dopahar" if h < 16 else "shaam" if h < 20 else "raat"


def canonical_when(text: str, now: datetime) -> tuple[str | None, datetime | None, datetime | None, bool, bool]:
    """(Hinglish phrase, window start, window end, exact, day_given) for the user's time words."""
    w = parse_when(text, now)
    if w.start_min is None and not w.found and BAJE_RE.search(text):
        w.dates = []  # a bare "6 baje": the day comes from the conversation
    elif not w.found:
        return None, None, None, False, False
    if w.start_min is None:  # "kal 5 baje": no am/pm word, salons are open 9-9
        m = BAJE_RE.search(text)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            if h < 24:
                if h < 9:
                    h += 12
                elif h == 12:
                    h = 12
                w.start_min, w.exact = h * 60 + mi, True
    today = to_ist(now).date()
    day = None
    if w.dates:
        offset = (w.dates[0] - today).days
        day = {0: "aaj", 1: "kal", 2: "parso"}.get(offset)
        if day is None and 0 <= offset <= 6:
            day = w.dates[0].strftime("%A")
    parts = [p for p in (day,) if p]
    if w.start_min is not None:
        parts.append(_period_word(w.start_min))
        if w.exact:
            h = (w.start_min // 60) % 12 or 12
            m = w.start_min % 60
            parts.append(f"{h}:{m:02d} baje" if m else f"{h} baje")
    phrase = " ".join(p for p in parts if p) or None
    start, end = w.window()
    return phrase, start, end, w.exact, bool(w.dates)


def parse_location_phrase(text: str) -> str | None:
    t = text.strip()
    m = re.search(r"(?:sector|sec)\s*-?\s*\d+[a-z]?", t, re.I)
    if m:
        phrase = m.group(0)
        extra = CITY_RE.search(t)
        if extra:
            phrase += " " + extra.group(1)
        return phrase.strip()
    m = re.search(r"(?:near|nearby|around|ke paas|paas|pass)\s+([A-Za-z0-9][\w ,.-]{2,40})", t, re.I)
    if m is None:  # "in/at <place>" only when it names a city or has a number (sector 56)
        m = re.search(r"\b(?:in|at)\s+([A-Za-z0-9][\w ,.-]{2,40})", t, re.I)
        if m and not (CITY_RE.search(m.group(1)) or re.search(r"\d", m.group(1))):
            m = None
    if m:
        cand = re.split(
            r"\b(?:mein|me|karwana|chahiye|haircut|for|ke liye|kal|aaj|tomorrow|today|please)\b",
            m.group(1),
            maxsplit=1,
            flags=re.I,
        )[0].strip(" ,.")
        if cand and len(cand.split()) <= 5:
            return cand
    c = CITY_RE.search(t)
    if c:
        before = re.findall(r"[A-Za-z0-9\u0900-\u097F]+", t[: c.start()])
        area: list[str] = []
        for w in reversed(before[-3:]):
            if w.lower() in _NOISE:
                break
            area.insert(0, w)
        return " ".join([*area, c.group(1)])  # a bare city is too wide: the flow asks for the area
    return None


def city_only(text: str | None) -> bool:
    """True when the place is just a city name (too wide: ask for the area)."""
    rest = CITY_RE.sub(" ", text or "")
    rest = re.sub(r"\b(in|at|near|mein|me|main|hoon|hu|city|shehar|se|ka|ki|ke)\b", " ", rest, flags=re.I)
    return not re.search(r"[A-Za-z0-9\u0900-\u097F]{2,}", rest)


def parse_request(text: str, now: datetime, *, default_lang: str = "hinglish") -> Parsed:
    p = Parsed(lang=ui_lang(text, default_lang))
    t = text or ""
    n = norm(t)
    p.services = find_services(t)
    phrase, start, end, exact, day_set = canonical_when(t, now)
    p.when_text, p.when_start, p.when_end, p.exact_time, p.day_set = phrase, start, end, exact, day_set
    budget, _ = extract_budget(t)
    p.budget_inr = budget
    if SOMEONE_RE.search(t):
        p.for_other_unnamed = True
    m = OTHER_RE.search(t)
    if m:
        name = (m.group("name") or m.group("name2") or m.group("hname") or "").strip()
        if name and name.lower() not in _NOT_NAMES and name.lower() not in _STOP_NAMES:
            p.for_name = name.title() if name.isascii() else name
            p.for_other_unnamed = False
    p.book_intent = bool(BOOK_RE.search(t)) and not QUOTE_WORDS.search(t)
    c = CITY_RE.search(t)
    if c:
        p.city = CITY_WORDS[c.group(1).lower()]
    elif OTHER_CITY_RE.search(t):
        p.other_city = True
    p.location_text = parse_location_phrase(t)
    _ = n
    return p


def when_datetimes(phrase_start: datetime | None, exact: bool) -> datetime | None:
    if phrase_start is None or not exact:
        return None
    return ensure_utc(phrase_start)


def slot_window(start: datetime, minutes: int = 5) -> tuple[datetime, datetime]:
    return start - timedelta(minutes=minutes), start + timedelta(minutes=minutes)


_ = IST
