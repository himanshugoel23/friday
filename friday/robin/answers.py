# ruff: noqa: E501
"""Reading a parent's short spoken answers (already transcribed) with plain rules: yes/no, 'stop', 'I am
fine', a number, a mood word. No model, no guessing: anything unclear stays ``None`` and is treated as
'no answer', never as consent and never as 'all is well'.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[\wऀ-ॿ']+", re.UNICODE)

YES = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "haan", "han", "haa", "ha", "hanji", "haanji", "ji", "jee", "bilkul", "zaroor", "theek",
    "thik", "sahi", "lee", "li", "liya", "khaya", "khayi", "soya", "hmm",
    "हाँ", "हां", "हा", "जी", "ठीक", "बिल्कुल", "ज़रूर", "जरूर", "ली", "ले", "लिया", "खाया", "सोया",
})  # fmt: skip
NO = frozenset({
    "no", "nope", "nah", "na", "naa", "nahi", "nahin", "nai", "nhi", "mat", "never", "nahee",
    "नहीं", "नही", "ना", "मत", "नहिं",
})  # fmt: skip
STOP = (
    "stop", "ruk jao", "ruk jaao", "ruko", "band karo", "band kar do", "mat karo", "phone mat", "dobara mat", "call mat",
    "रुक जाओ", "रुको", "बंद करो", "बंद कर दो", "मत करो", "फोन मत", "फ़ोन मत",
)  # fmt: skip
START = ("shuru karo", "shuru kar do", "start", "resume", "शुरू करो", "शुरू कर दो")
THREAT = ("being threatened", "threatening me", "i am in danger", "dhamki", "dhamka", "mujhe khatra", "koi mujhe maar", "धमकी", "धमका", "ख़तरा", "खतरा")
HELP = ("help", "madad", "bachao", "bachaao", "ambulance", "emergency", "मदद", "बचाओ", "एम्बुलेंस")
FINE = (
    "i am fine", "i'm fine", "im fine", "all fine", "i have it", "main theek", "mai theek", "sab theek", "theek hoon", "theek hun", "theek hai",
    "ठीक हूँ", "ठीक हूं", "सब ठीक", "मैं ठीक", "मै ठीक",
)  # fmt: skip
BAD_MOOD = frozenset({
    "sad", "low", "down", "upset", "worried", "anxious", "lonely", "tired", "bad", "depressed",
    "udaas", "udas", "dukhi", "pareshan", "pareshaan", "akela", "akeli", "bura", "thaka", "thaki", "tension", "ghabrahat", "dar",
    "उदास", "दुखी", "परेशान", "अकेला", "अकेली", "बुरा", "थका", "थकी", "टेंशन", "घबराहट",
})  # fmt: skip
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20, "tees": 30,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
}  # fmt: skip


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    t = " ".join(words(text))
    return any(p in t for p in phrases)


def yesno(text: str) -> bool | None:
    """True / False / None (unclear). A 'no' word wins ('nahi chahiye' is no even with 'ji')."""
    ws = words(text)
    if any(w in NO for w in ws):
        return False
    if any(w in YES for w in ws):
        return True
    return None


def is_stop(text: str) -> bool:
    return _has_phrase(text, STOP)


def is_start(text: str) -> bool:
    return _has_phrase(text, START)


def is_threat(text: str) -> bool:
    return _has_phrase(text, THREAT)


def is_help(text: str) -> bool:
    return _has_phrase(text, HELP)


def is_fine(text: str) -> bool:
    """'I am fine' / 'I have it' said by the parent: the nudge ladder may stop."""
    return _has_phrase(text, FINE) and not any(w in NO for w in words(text))


def count(text: str) -> int | None:
    t = (text or "").translate(_DEVA_DIGITS)
    m = re.search(r"\d{1,4}", t)
    if m:
        return int(m.group())
    for w in words(t):
        if w in _NUM_WORDS:
            return _NUM_WORDS[w]
    return None


def mood(text: str) -> tuple[str, bool]:
    """(the word to show, whether it is a low mood word). Empty text -> ('', False)."""
    ws = words(text)
    if not ws:
        return "", False
    low = next((w for w in ws if w in BAD_MOOD), None)
    return (low or ws[0])[:20], low is not None
