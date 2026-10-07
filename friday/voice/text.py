"""Text helpers for the voice pipeline (pure functions, no I/O).

* ``strip_fillers``    - US-19.4: remove "umm"/"uh"/"hmm", fake breaths, stage directions
                         before anything reaches TTS. Meaningful acks ("Ji", "Theek hai")
                         are kept.
* ``redact_secrets``   - hard rule 9 / US-33: OTP/PIN/CVV digits heard on a call are
                         never stored in transcripts.
* ``detect_language``  - script + romanised-Hindi heuristic used by the fake STT and the
                         simulator (real STT vendors return the detected language).
* ``mask_digits``      - DTMF / identifiers in transcripts and logs.
"""

from __future__ import annotations

import re

from friday.core.models import Language

# --------------------------------------------------------------------------- fillers

_FILLER_WORD = re.compile(
    r"(?<![\w'])(?:u+m+|u+h+m*|h+m+|e+r+m+|e+h+|a+h+|mm+|erm|uhh+|hmmm*)(?![\w'])[,.…]*",
    re.I,
)
_STAGE = re.compile(
    r"[\[(*<]\s*(?:sighs?|breath(?:es|ing)?|inhales?|exhales?|laughs?|chuckles?|"
    r"pause[sd]?|typing|keyboard\s+sounds?|clears?\s+throat|coughs?|hesitat\w*)\s*[\])*>]",
    re.I,
)
_ELLIPSIS_HESITATION = re.compile(r"\s*(?:\.{3,}|…)\s*")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?।])")
_LEADING_PUNCT = re.compile(r"^[\s,.;:!?-]+")
_DOUBLE_COMMA = re.compile(r",\s*,+")


def strip_fillers(text: str) -> str:
    """Remove disfluencies and stage directions. Never changes meaning-carrying words."""
    if not text:
        return ""
    out = _STAGE.sub(" ", text)
    out = _FILLER_WORD.sub(" ", out)
    out = _ELLIPSIS_HESITATION.sub(". ", out)
    out = _DOUBLE_COMMA.sub(",", out)
    out = _MULTI_SPACE.sub(" ", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = re.sub(r"([,.])\s*\.", ".", out)
    out = _LEADING_PUNCT.sub("", out)
    return re.sub(r"[,;:]\s*$", "", out.strip())


# --------------------------------------------------------------------------- secrets

_SECRET_CONTEXT = re.compile(
    r"\b(otp|o\.t\.p|one[- ]?time|cvv|cvc|m?pin|t-?pin|pass(word|code)|verification code|"
    r"card number|card no)\b|ओटीपी|पिन|पासवर्ड",
    re.I,
)
_DIGIT_RUN = re.compile(r"\d(?:[ \-.]?\d)*")


def redact_secrets(text: str) -> str:
    """Replace digit runs (>=3 digits) that follow OTP/PIN/CVV/password wording.

    "Mera OTP 4 8 2 9 1 3 hai" -> "Mera OTP [redacted] hai".
    """
    if not text or not _SECRET_CONTEXT.search(text):
        return text
    out: list[str] = []
    pos = 0
    for m in _DIGIT_RUN.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        before = text[max(0, m.start() - 40) : m.start()]
        if len(digits) >= 3 and _SECRET_CONTEXT.search(before):
            out.append(text[pos : m.start()])
            out.append("[redacted]")
            pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def mask_digits(value: str, keep: int = 4) -> str:
    """'7012345678#' -> '••••••5678#' (keeps the last ``keep`` digits, *, #, w)."""
    digits = [i for i, ch in enumerate(value) if ch.isdigit()]
    if len(digits) <= 2:
        return value
    hide = set(digits[: max(0, len(digits) - keep)])
    return "".join("•" if i in hide else ch for i, ch in enumerate(value))


# --------------------------------------------------------------------------- language

_SCRIPTS: list[tuple[str, str, Language]] = [
    ("ঀ", "৿", Language.BN),
    ("਀", "੿", Language.PA),
    ("઀", "૿", Language.GU),
    ("଀", "୿", Language.OR),
    ("஀", "௿", Language.TA),
    ("ఀ", "౿", Language.TE),
    ("ಀ", "೿", Language.KN),
    ("ഀ", "ൿ", Language.ML),
    ("ऀ", "ॿ", Language.HI),
]
# Marathi shares Devanagari with Hindi; these words are common in Marathi only.
_MARATHI_MARKERS = re.compile(
    r"(आहे|नाही|आहेत|काय|मी |तुम्ही|आम्ही|करतो|करते|पाहिजे|होय|बोला|कसे|आपण|झाले|मिळेल|आणि|किती)"
)
_HINDI_ROMAN = {
    "hai",
    "hain",
    "hoon",
    "hun",
    "kya",
    "nahi",
    "nahin",
    "ji",
    "aap",
    "aapka",
    "aapko",
    "main",
    "mein",
    "karti",
    "karta",
    "kar",
    "karke",
    "kal",
    "theek",
    "thik",
    "haan",
    "han",
    "bhai",
    "kitna",
    "kitne",
    "chahiye",
    "ke",
    "ki",
    "ka",
    "se",
    "ho",
    "raha",
    "rahi",
    "dijiye",
    "boliye",
    "achha",
    "acha",
    "accha",
    "abhi",
    "baje",
    "wala",
    "wali",
    "hum",
    "humare",
    "tak",
    "toh",
    "bhi",
    "par",
    "pe",
    "lekin",
    "kaise",
    "kab",
    "kahan",
    "kuch",
    "sakte",
    "sakti",
    "namaste",
    "namaskar",
    "dhanyavaad",
    "shukriya",
    "ek",
    "do",
    "teen",
    "minute",
    "bolo",
    "batao",
    "bataiye",
    "milega",
    "milegi",
    "hoga",
    "hogi",
    "rakh",
    "ruko",
    "jaldi",
    "taraf",
    "baat",
    "wapas",
    "phir",
    "aaj",
    "subah",
    "shaam",
    "raat",
    "dawai",
    "khana",
}
_HINDI_ROMAN |= {
    "liye", "karo", "karna", "karni", "papa", "mummy", "aur", "ko", "yeh", "woh", "wo",
    "hoga", "chahte", "gaya", "gayi", "kijiye", "batana", "matlab",
}  # fmt: skip
_WORD = re.compile(r"[a-zA-Z']+")


def detect_language(text: str, default: Language = Language.EN) -> Language:
    """Best-effort language of an utterance (script first, then romanised Hindi)."""
    if not text or not text.strip():
        return default
    counts: dict[Language, int] = {}
    latin = 0
    for ch in text:
        if "a" <= ch.lower() <= "z":
            latin += 1
            continue
        for lo, hi, lang in _SCRIPTS:
            if lo <= ch <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if counts:
        lang, n = max(counts.items(), key=lambda kv: kv[1])
        if lang == Language.HI and _MARATHI_MARKERS.search(text):
            lang = Language.MR
        if lang == Language.HI and latin > n:
            return Language.HINGLISH  # mostly Roman with some Devanagari
        return lang
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return default
    hindi = sum(1 for w in words if w in _HINDI_ROMAN)
    if hindi and hindi / len(words) >= 0.2:
        return Language.HINGLISH
    return Language.EN


def contains_any(text: str, needles: tuple[str, ...] | list[str] | set[str]) -> bool:
    low = text.lower()
    return any(n in low for n in needles)
