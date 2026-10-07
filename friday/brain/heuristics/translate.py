"""Deterministic phrase-lexicon translator for the fake path (translator mode,
B18). Meaning-preserving for common call phrases; numbers, times, amounts and
names pass through unchanged."""

from __future__ import annotations

import re

from friday.core.models import Language

from ..lang import detect_language

# (hinglish/roman-hindi, english, devanagari-hindi)
PHRASES: list[tuple[str, str, str]] = [
    ("kitne ka hai", "how much is it", "कितने का है"),
    ("kitna lagega", "how much will it cost", "कितना लगेगा"),
    ("kya aapke paas room hai", "do you have a room", "क्या आपके पास कमरा है"),
    ("room khaali hai", "a room is available", "कमरा खाली है"),
    ("kamra khaali hai", "a room is available", "कमरा खाली है"),
    ("theek hai", "okay", "ठीक है"),
    ("thik hai", "okay", "ठीक है"),
    ("dhanyavaad", "thank you", "धन्यवाद"),
    ("shukriya", "thank you", "शुक्रिया"),
    ("namaste", "hello", "नमस्ते"),
    ("kaise ho", "how are you", "कैसे हो"),
    ("kaise hain aap", "how are you", "कैसे हैं आप"),
    ("haan ji", "yes", "हाँ जी"),
    ("haan", "yes", "हाँ"),
    ("nahi", "no", "नहीं"),
    ("kal subah", "tomorrow morning", "कल सुबह"),
    ("kal shaam", "tomorrow evening", "कल शाम"),
    ("aaj shaam", "this evening", "आज शाम"),
    ("kal", "tomorrow", "कल"),
    ("aaj", "today", "आज"),
    ("subah", "morning", "सुबह"),
    ("shaam", "evening", "शाम"),
    ("baje", "o'clock", "बजे"),
    ("nashta shaamil hai", "breakfast is included", "नाश्ता शामिल है"),
    ("nashta", "breakfast", "नाश्ता"),
    ("ek raat", "one night", "एक रात"),
    ("do raat", "two nights", "दो रात"),
    ("per raat", "per night", "प्रति रात"),
    ("check-in kitne baje hai", "what time is check-in", "चेक-इन कितने बजे है"),
    ("booking confirm hai", "the booking is confirmed", "बुकिंग कन्फ़र्म है"),
    ("thoda kam kijiye", "please reduce it a little", "थोड़ा कम कीजिए"),
    ("hold kar sakte hain", "can you hold it", "होल्ड कर सकते हैं"),
    ("rupaye", "rupees", "रुपये"),
    ("kya", "what", "क्या"),
    ("milega", "is available", "मिलेगा"),
    ("chahiye", "is needed", "चाहिए"),
    ("dawai", "medicine", "दवाई"),
]
# Marathi -> Hinglish
MARATHI: list[tuple[str, str]] = [
    ("namaskar", "namaste"), ("kiti", "kitna"), ("kiti paise", "kitne paise"),
    ("aahe", "hai"), ("ahe", "hai"), ("nahi", "nahi"), ("udya", "kal"), ("aaj", "aaj"),
    ("hoy", "haan"), ("dhanyavaad", "shukriya"), ("kay", "kya"), ("pahije", "chahiye"),
    ("sakali", "subah"), ("sandhyakali", "shaam ko"), ("khup", "bahut"), ("thamba", "rukiye"),
    ("room aahe", "room hai"), ("rikama aahe", "khaali hai"), ("tumhi", "aap"), ("amhi", "hum"),
    ("aaplya", "aapke"), ("vajta", "baje"), ("vajata", "baje"),
    ("नमस्कार", "namaste"), ("आहे", "hai"), ("उद्या", "kal"), ("किती", "kitna"),
]
_TOKEN_KEEP = re.compile(r"(\d[\d,:.]*\s*(?:am|pm|₹|rs)?|₹\s*\d[\d,]*|[A-Z][a-z]+)")


def _replace_all(text: str, pairs: list[tuple[str, str]]) -> str:
    out = text
    for src, dst in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
        out = re.sub(rf"(?<![\wऀ-ॿ]){re.escape(src)}(?![\wऀ-ॿ])", dst, out,
                     flags=re.I)
    return out


def translate(text: str, target: Language, source: Language | None = None) -> str:
    src = source or detect_language(text)
    if src == target or not text.strip():
        return text
    if src == Language.MR:
        hinglish = _replace_all(text, MARATHI)
        if target in (Language.HINGLISH, Language.HI):
            return hinglish if target == Language.HINGLISH else _replace_all(
                hinglish, [(h, d) for h, _e, d in PHRASES])
        return _replace_all(hinglish, [(h, e) for h, e, _d in PHRASES])
    if src in (Language.HINGLISH, Language.HI):
        if target == Language.EN:
            pairs = [(h, e) for h, e, _d in PHRASES] + [(d, e) for _h, e, d in PHRASES]
            return _replace_all(text, pairs)
        if target == Language.HI:
            return _replace_all(text, [(h, d) for h, _e, d in PHRASES])
        if target == Language.HINGLISH:
            return _replace_all(text, [(d, h) for h, _e, d in PHRASES])
    if src == Language.EN:
        if target == Language.HINGLISH:
            return _replace_all(text, [(e, h) for h, e, _d in PHRASES])
        if target == Language.HI:
            return _replace_all(text, [(e, d) for _h, e, d in PHRASES])
    return text  # unsupported pair on the fake path: pass through unchanged
