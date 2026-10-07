"""Language detection & mirroring helpers (founder rule #1: mirror the callee)."""

from __future__ import annotations

import re

from friday.core.models import CORE_LANGUAGES, Language

from .textutil import norm

_SCRIPTS: list[tuple[str, Language]] = [
    (r"[஀-௿]", Language.TA),
    (r"[ఀ-౿]", Language.TE),
    (r"[ಀ-೿]", Language.KN),
    (r"[ঀ-৿]", Language.BN),
    (r"[઀-૿]", Language.GU),
    (r"[਀-੿]", Language.PA),
    (r"[ഀ-ൿ]", Language.ML),
    (r"[଀-୿]", Language.OR),
]
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[a-zA-Z]")

HINDI_MARKERS = {
    "hai", "hain", "ho", "hoon", "hu", "kar", "karo", "karna", "karke", "kardo", "kariye",
    "karein", "karti", "karta", "karenge", "ke", "ki", "ka", "ko", "se", "mein", "me", "nahi",
    "nahin", "kya", "kyu", "kyun", "aap", "aapka", "aapko", "mujhe", "mera", "meri", "mere",
    "chahiye", "kal", "aaj", "ji", "haan", "theek", "thik", "bhi", "wala", "wali", "dena",
    "do", "dijiye", "bolo", "boliye", "bataiye", "batao", "kitna", "kitne", "kab", "kaun",
    "kaise", "accha", "achha", "acha", "lagega", "milega", "abhi", "baje", "subah", "shaam",
    "raha", "rahi", "rahe", "gaya", "gayi", "tha", "thi", "hoga", "hogi", "sakte", "sakti",
    "liye", "unka", "unki", "papa", "mummy", "ghar", "paas", "dhundo", "bhai", "yaar",
    "shukriya", "dhanyavaad", "namaste", "matlab", "kuch", "sab", "agar", "toh", "phir",
}
MARATHI_MARKERS = {
    "aahe", "ahe", "nahi", "kay", "kaay", "pahije", "tumhi", "amhi", "kiti", "udya", "hoy",
    "naka", "sanga", "namaskar", "aai", "baba", "kasa", "kashi", "aahet", "mhanje",
    "आहे", "काय", "पाहिजे", "तुम्ही", "उद्या",
}
KANNADA_MARKERS = {"gottilla", "illa", "ide", "beku", "swalpa", "aadre", "sari", "yaaru",
                   "banni", "namaskara", "gantege", "hege", "enu", "houdu", "beda"}
TAMIL_MARKERS = {"illai", "vanakkam", "enna", "irukku", "seri", "romba", "sollunga", "venum",
                 "aama", "theriyum"}
TELUGU_MARKERS = {"ledu", "undi", "cheppandi", "emi", "namaskaram", "kavali", "avunu",
                  "baagunnara", "entha"}
BENGALI_MARKERS = {"ache", "nei", "kemon", "bolun", "korbo", "hobe", "acchha", "dada"}
_ROMAN_REGIONAL = [
    (KANNADA_MARKERS, Language.KN),
    (TAMIL_MARKERS, Language.TA),
    (TELUGU_MARKERS, Language.TE),
    (MARATHI_MARKERS, Language.MR),
]


def detect_language(text: str | None, default: Language = Language.HINGLISH) -> Language:
    """Cheap script + marker-word detector. Good enough for Hinglish vs English vs
    Hindi; regional scripts by Unicode block; Roman regional by marker words."""
    if not text or not text.strip():
        return default
    for rx, lang in _SCRIPTS:
        if re.search(rx, text):
            return lang
    words = set(re.findall(r"[\wऀ-ॿ]+", norm(text)))
    if _DEVANAGARI.search(text):
        if words & MARATHI_MARKERS and not words & {"है", "हैं", "नहीं"}:
            return Language.MR
        return Language.HINGLISH if _LATIN.search(text) else Language.HI
    for markers, lang in _ROMAN_REGIONAL:
        hits = words & markers
        if len(hits) >= 1 and (lang != Language.MR or len(hits) >= 2):
            return lang
    hindi_hits = len(words & HINDI_MARKERS)
    if hindi_hits >= 2 or (hindi_hits == 1 and len(words) <= 3):
        return Language.HINGLISH
    return Language.EN


def text_language(lang: Language) -> Language:
    """Languages the deterministic phrasebook can *write* (en / hi / hinglish).
    Regional languages map to the closest one the callee most likely understands:
    Hindi-belt-adjacent (mr, gu, pa) -> Hinglish; southern/eastern -> English."""
    if lang in CORE_LANGUAGES:
        return lang
    if lang in (Language.MR, Language.GU, Language.PA):
        return Language.HINGLISH
    return Language.EN


def mirror(callee: Language | None, opening: Language, speakable: frozenset[Language] | None
           ) -> Language:
    """Language Friday should answer in: the callee's, if TTS can speak it."""
    if callee is None:
        return opening
    if speakable is None or callee in speakable:
        return callee
    return text_language(callee)
