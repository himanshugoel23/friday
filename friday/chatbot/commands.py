"""Recognising the few words that always mean the same thing, and the answers inside the flow.

Everything is matched on the whole short message (a command is a command only when it is the
message), so "stop calling mummy" or "help me book a salon" are never taken for "stop" or "menu".
"""

from __future__ import annotations

import re

_I = re.IGNORECASE


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# --------------------------------------------------------------------------- commands
_PUNCT = re.compile(r"[.!?,;:।]+$")


def norm(text: str | None) -> str:
    t = " ".join((text or "").strip().lower().split())
    return _PUNCT.sub("", t).strip()


MENU = re.compile(
    r"^(?:menu|help|madad|madat|options|मदद|मेनू|मेन्यू)(?:\s+(?:dikhao|dikha\s+do|batao|chahiye|please|plz))?$|"
    r"^(?:tum|aap|app)?\s*(?:kya|kya\s+kya)\s+kar\s+(?:sakti|sakte|sakta|paati|pati)\s+(?:ho|hain|hai)$|"
    r"^what\s+can\s+you\s+do$|^(?:show\s+)?(?:the\s+)?menu$|^help\s+me$|^tum\s+kya\s+kar\s+sakti\s+ho$",
    _I,
)
HUMAN = re.compile(
    r"^(?:human|insaan|insan|इंसान|support|agent|real\s+person|customer\s+care|"
    r"insaan\s+se\s+baat(?:\s+karao|\s+karni\s+hai)?|kisi\s+se\s+baat\s+karao|"
    r"team\s+se\s+baat(?:\s+karao)?|talk\s+to\s+(?:a\s+)?(?:human|person)|"
    r"i\s+want\s+(?:a\s+)?(?:human|person))(?:\s*[:\-]\s*(?P<rest>.{1,200}))?$",
    _I,
)
STOP = re.compile(
    r"^(?:stop|stop\s+messages|messages?\s+band\s+karo|band\s+karo|unsubscribe|"
    r"khud\s+se\s+message\s+mat\s+bhejo|बंद\s+करो|रुको\s+मैसेज)$",
    _I,
)
RESUME = re.compile(
    r"^(?:start|resume|chalu\s+karo|chalu\s+kar\s+do|messages?\s+chalu\s+karo|चालू\s+करो)$", _I
)
DELETE_ALL = re.compile(
    r"^(?:delete\s+(?:everything|all|my\s+data|all\s+my\s+data)|erase\s+(?:everything|my\s+data)|"
    r"(?:sab|sab\s+kuch|saara\s+data|mera\s+data|mera\s+sab\s+data)\s+(?:delete|mita|mitao)(?:\s+(?:karo|kar\s+do|do))?|"
    r"delete\s+karo\s+sab|forget\s+everything)$",
    _I,
)

SKIP = re.compile(
    r"^(?:skip|baad\s+mein|baad\s+me|later|rehne\s+do|chhodo|chodo|no\s+thanks|nahi\s+batana|"
    r"pass|छोड़ें|छोड़ो|बाद\s+में)$",
    _I,
)
YES = re.compile(
    r"^(?:haan|han|ha|haa|haan\s+ji|ji|ji\s+haan|yes|y|yeah|yep|ok|okay|ok\s+ji|theek\s+hai|thik\s+hai|"
    r"theek|thik|sure|bilkul|chalo|agree|i\s+agree|accha|achha|"
    r"haan\s*,?\s*theek\s+hai|haan\s*,?\s*thik\s+hai|हाँ|हां|ठीक\s+है|जी)$",
    _I,
)
NO = re.compile(
    r"^(?:nahi|nahin|nhi|na|no|nope|mat|nahi\s+chahiye|abhi\s+nahi|no\s+thanks|"
    r"नहीं|नही|मत)$",
    _I,
)
DETAILS = re.compile(
    r"^(?:details?|detail\s+batao|info|more|aur\s+batao|more\s+info|kya\s+kya\s+logi|kaise|kyun|why|"
    r"kya\s+hai\s+yeh|yeh\s+kya\s+hai|विवरण)$",
    _I,
)
GREETING = re.compile(
    r"^(?:hi+|hello+|hey+|hlo|helo|namaste|namaskar|नमस्ते|start|menu|help)\s*[!.]*$", _I
)
_NOT_A_NAME = _words(
    "hi hii hello hey hlo namaste ok okay haan han yes no nahi nope menu help stop start skip "
    "thanks thank shukriya kya kaun why what who"
)

LANG_WORDS: dict[str, str] = {
    "hinglish": "hinglish", "roman": "hinglish", "roman hindi": "hinglish",
    "hindi english": "hinglish",
    "hindi": "hi", "हिंदी": "hi", "हिन्दी": "hi", "shuddh hindi": "hi", "devanagari": "hi",
    "english": "en", "angrezi": "en", "अंग्रेज़ी": "en", "अंग्रेजी": "en", "en": "en",
}  # fmt: skip

_NAME_PREFIX = re.compile(
    r"^(?:mera\s+naam|mera\s+name|my\s+name\s+is|i\s+am|i'm|main|mai|naam|name|call\s+me|"
    r"mujhe|मेरा\s+नाम|मैं)\s+",
    _I,
)
_NAME_SUFFIX = re.compile(r"\s+(?:hai|hoon|hun|bulao|bulana|bulaiye|bolo|है|हूँ)$", _I)
_NAME_OK = re.compile(r"^[^\W\d_][\w'.\- ]{0,38}$", re.UNICODE)
_REQUESTISH = re.compile(
    r"\?|\b(?:call|karo|kar\s+do|chahiye|please|plz|batao|dikhao|kya|kaise|kab|kitna|kaun|"
    r"book|order|remind|yaad|bill|card|menu|help|stop|delete)\b",
    _I,
)


def parse_name(text: str | None) -> str | None:
    """A first name (or name) from "Rahul", "mera naam Rahul hai", "I am Rahul"; None when the
    message is not a name (a greeting, a question, a request, a number)."""
    t = " ".join((text or "").split())
    if not t or len(t) > 60:
        return None
    t = _NAME_SUFFIX.sub("", _NAME_PREFIX.sub("", t)).strip(" .!,")
    if not t or len(t.split()) > 3 or t.lower() in _NOT_A_NAME:
        return None
    if _REQUESTISH.search(t) or not _NAME_OK.match(t):
        return None
    if any(w.lower() in _NOT_A_NAME for w in t.split()):
        return None
    return " ".join(w[:1].upper() + w[1:] for w in t.split())


def parse_language(text: str | None) -> str | None:
    t = norm(text)
    if t in LANG_WORDS:
        return LANG_WORDS[t]
    for word, code in LANG_WORDS.items():
        if len(word) > 3 and re.search(rf"\b{re.escape(word)}\b", t):
            return code
    return None


def parse_city(text: str | None) -> str | None:
    """A city from "Pune", "main Pune mein hoon", "Mumbai me"; None for anything else."""
    t = " ".join((text or "").split()).strip(" .!,")
    if not t or len(t) > 60 or re.search(r"\d", t):
        return None
    t = re.sub(r"^(?:main|mai|hum|i\s+am\s+in|i'm\s+in|in|from|se)\s+", "", t, flags=_I)
    t = re.sub(
        r"\s+(?:mein|me|se|mai|hoon|hun|hai|rehta\s+hoon|rehti\s+hoon|में|मैं)$", "", t, flags=_I
    )
    t = re.sub(r"\s+(?:mein|me|hoon|hun|में)$", "", t, flags=_I).strip(" .!,")
    if not t or len(t.split()) > 3 or t.lower() in _NOT_A_NAME or _REQUESTISH.search(t):
        return None
    if not _NAME_OK.match(t):
        return None
    return " ".join(w[:1].upper() + w[1:] for w in t.split())


# --------------------------------------------------------------------------- first wins
_WIN_SINGLE = {
    "card": frozenset({"card", "cards", "bachat", "savings", "kaun sa card", "कार्ड"}),
    "day": frozenset({"din", "day", "mera din", "my day", "दिन", "मेरा दिन"}),
    "call": frozenset({"call", "calls", "phone", "kisi ko call", "कॉल", "फोन"}),
}


def parse_win(text: str | None) -> str | None:
    """Only the title of a first-win button (or a one-word equivalent) counts; anything longer is
    a real request for the router."""
    t = norm(text)
    for key, words in _WIN_SINGLE.items():
        if t in words:
            return key
    return None


# --------------------------------------------------------------------------- places and nicknames
HOME_WORDS = re.compile(r"^(?:ghar|home|house|mera\s+ghar|घर)$", _I)
OFFICE_WORDS = re.compile(r"^(?:office|offc|work|kaam|daftar|workplace|ऑफिस|दफ्तर)$", _I)
_LABEL_OK = re.compile(r"^[^\W\d_][\w'.\- ]{0,28}$", re.UNICODE)


def parse_place_label(text: str | None) -> tuple[str, list[str]] | None:
    """(label, aliases) for "ghar", "office" or a short own name ("mummy ka ghar"); None when the
    message is not a label."""
    t = " ".join((text or "").split()).strip(" .!,")
    if not t or len(t.split()) > 4 or not _LABEL_OK.match(t) or "?" in t:
        return None
    if HOME_WORDS.match(t):
        return "Home", ["ghar", "home"]
    if OFFICE_WORDS.match(t):
        return "Office", ["office", "kaam"]
    if _REQUESTISH.search(t) or t.lower() in _NOT_A_NAME:
        return None
    label = " ".join(w[:1].upper() + w[1:] for w in t.split())
    return label, [t.lower()]


def parse_nickname(text: str | None) -> str | None:
    """ "mummy", "Bhaiya", "Rakesh uncle" -> the nickname to store; None when it is not one."""
    t = " ".join((text or "").split()).strip(" .!,")
    if not t or len(t.split()) > 3 or len(t) > 30 or "?" in t or re.search(r"\d", t):
        return None
    if not _NAME_OK.match(t) or t.lower() in _NOT_A_NAME or _REQUESTISH.search(t):
        return None
    return t


# --------------------------------------------------------------------------- phone numbers
_PHONE = re.compile(r"(?<![\w])(\+?\d[\d\s\-().]{8,17}\d)(?![\w])")
_FILLER = re.compile(
    r"\b(?:number|no|num|mobile|phone|contact|ka|ki|ke|ye|yeh|yah|hai|save|karo|kar|do|isko|isse|"
    r"is|ko|ye|this|is|my|the|number\s+hai|add)\b",
    _I,
)


def split_phone(text: str | None) -> tuple[str, str] | None:
    """(number text, leftover words) when the message is basically one phone number with at most a
    short label ("mummy 98765 43210", "98765 43210"); None otherwise. Messages with 13 or more
    digits are never taken (a card number is not a phone number)."""
    t = " ".join((text or "").split())
    if not t or len(t) > 80:
        return None
    digits = re.sub(r"\D", "", t)
    if len(digits) < 10 or len(digits) > 13:
        return None
    m = _PHONE.search(t)
    if not m:
        return None
    rest = _FILLER.sub(" ", (t[: m.start()] + " " + t[m.end() :]))
    rest = " ".join(re.sub(r"[^\w\s'\-]", " ", rest, flags=re.UNICODE).split())
    if len(rest.split()) > 3 or "?" in t:
        return None
    return m.group(1), rest


def mask_last2(e164: str) -> str:
    """Confirm a number back with its last two digits hidden (a +91 number keeps its grouping)."""
    d = re.sub(r"\D", "", e164)
    if e164.startswith("+91") and len(d) == 12:
        national = d[2:]
        return f"+91 {national[:5]} {national[5:8]}XX"
    return f"+{d[:-2]}XX" if len(d) > 4 else "XX"
