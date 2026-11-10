# ruff: noqa: E501
"""Reading a parent's short spoken answers (already transcribed) with plain rules: yes/no, 'stop', 'I am
fine', a number, a mood word. No model, no guessing: anything unclear stays ``None`` and is treated as
'no answer', never as consent and never as 'all is well'.
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[\wऀ-ॿ']+", re.UNICODE)

YES = frozenset({
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "haan", "han", "haa", "ha", "hanji", "haanji", "ji", "jee", "bilkul", "zaroor", "theek",
    "thik", "sahi", "hnji", "hn", "hnn", "haanjee", "lee", "li", "liya", "khaya", "khayi", "soya", "hmm",
    "हाँ", "हां", "हा", "जी", "ठीक", "बिल्कुल", "ज़रूर", "जरूर", "ली", "ले", "लिया", "खाया", "सोया",
})  # fmt: skip
NO = frozenset({
    "no", "nope", "nah", "na", "naa", "nahi", "nahin", "nai", "nhi", "mat", "never", "nahee", "nhin", "nahiin", "nahn", "nahinji", "nahijee",
    "नहीं", "नही", "ना", "मत", "नहिं",
})  # fmt: skip
STOP = (
    "stop", "ruk jao", "ruk jaao", "ruko", "band karo", "band kar do", "mat karo", "phone mat", "dobara mat", "call mat",
    "रुक जाओ", "रुको", "बंद करो", "बंद कर दो", "मत करो", "फोन मत", "फ़ोन मत",
)  # fmt: skip
START = ("shuru karo", "shuru kar do", "start", "resume", "शुरू करो", "शुरू कर दो")
THREAT = ("being threatened", "threatening me", "i am in danger", "dhamki", "dhamka", "mujhe khatra", "koi mujhe maar", "धमकी", "धमका", "ख़तरा", "खतरा")
# HELP words are matched as WHOLE words after squashing repeated letters (see ``_squash``): "helppp", "madadd", "bachaooo" still count, "helpful" and
# "madadgar" do not. A phrase is several words in a row. Never shorten this list: a missed help word is worse than a false alarm.
HELP = (
    "help", "helpme", "madad", "bachao", "bachaao", "bachaiye", "bacha lo", "bachalo", "ambulance", "emergency",
    "मदद", "बचाओ", "बचाइए", "बचा लो", "एम्बुलेंस", "हेल्प",
)  # fmt: skip
# Fall / chest-pain / breathing wording is SOS-grade help too. Each pattern is a run of words; "a|b" = either word, "~" = up to 4 other words
# in between. NEVER a bare "gir" or "dard" ("paani gir gaya", "sar dard" must not fire): a fall needs the person ("gir gayi hoon", "main gir
# gaya", "uth nahi pa raha"), pain needs the chest ("seene mein ... dard"). Patterns marked GUARDED are skipped when a "no/nahi" sits right
# before or within two words after ("chest pain nahi hai"). Engineering draft: needs native-speaker and clinical review (docs/ROBIN_EVAL.md).
_AA = "gaya|gayi|gai|gayee|gaye|gayeen|pada|padi|pade"
_HOON = "hoon|hun|hu|hoo"
_JAUNGA = "jaunga|jaungi|jaaunga|jaaungi|jaonga|jaoonga"
EMERGENCY_BODY: tuple[tuple[str, bool], ...] = (  # (pattern, guarded)
    # --- fall ---
    (f"gir {_AA} {_HOON}", False), (f"main|mai|mujhe gir {_AA}", False),
    ("uth|utha nahi|nahin|nhi|nai pa|paa|pata|pati|paaya|paya|sak|sakta|sakti|sakte|ja|jaa|jata|jati", False),
    (f"chakkar|chakkr|chakar ~ gir {_JAUNGA}", False), ("behosh|behoshi ho|hone|hojaunga|hojaungi", True),
    ("i have|had|am fallen", False), ("ive|i've fallen", False), ("i fell down|over|on|from|and", False),
    ("cant|can't|cannot|couldnt|couldn't|unable ~ get|stand up from|off", False),
    ("गिर गया|गई|गयी|गये|गए|पड़ा|पड़ी हूँ|हूं|हु", False), ("मैं|मै|मुझे गिर गया|गई|गयी|पड़ा|पड़ी", False), ("उठ|उठा नहीं|नही|नहिं पा|सक|जा", False),
    ("चक्कर ~ गिर जाऊँगा|जाऊंगा|जाऊँगी|जाऊंगी|जाउंगा|जाउंगी", False), ("बेहोश हो|होने", True),
    # --- chest pain, heart, breathing ---
    ("seene|seena|sine|sina|chhati|chhaati|chaati|chest ~ dard|pain|dukh|hurt|hurts|hurting|tight|jakad|bhaari|bhari", True), ("pain|hurts|hurt ~ chest|seene|seena", True),
    ("dil ~ dard ho", True), ("dil ka|ki daura|dora", False), ("heart attack", False), ("heartattack", False),
    ("saans|sans|saas nahi|nahin|nhi aa|aati|le|ruk|ban", False), ("saans|sans|saas lene mein|me takleef|dikkat|taklif|mushkil", False),
    ("cant|can't|cannot|couldnt|couldn't|unable ~ breathe|breathing", False), ("can not breathe", False), ("difficulty|trouble breathing|breathe", False),
    ("short of breath", False), ("shortness of breath", False),
    ("सीने|छाती ~ दर्द", True), ("दिल का दौरा", False), ("हार्ट अटैक", False),
    ("सांस|साँस नहीं|नही आ|ले|रुक", False), ("सांस|साँस लेने ~ तकलीफ|दिक्कत|मुश्किल", False),
)  # fmt: skip
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


_REPEAT = re.compile(r"(.)\1+")
_NEG = frozenset({"no", "not", "never", "nahi", "nahin", "nhi", "nai", "नहीं", "नही"})
_FILLER_MAX = 4


def _squash(token: str) -> str:
    """Repeated letters count once ("helppp" == "help", "bachaooo" == "bachao"); applied to the pattern words and to the heard words alike (NFC first)."""
    return _REPEAT.sub(r"\1", unicodedata.normalize("NFC", token))


def _tokens(text: str) -> list[str]:
    return [_squash(w) for w in words((text or "").replace("\u2019", "'"))]


def _compile(pattern: str) -> tuple[frozenset[str] | None, ...]:
    return tuple(None if p == "~" else frozenset(_squash(a) for a in p.split("|")) for p in pattern.split())


def _match_from(toks: list[str], pat: tuple[frozenset[str] | None, ...], i: int, j: int) -> int | None:
    """End index when ``pat[j:]`` matches ``toks`` starting at ``i`` (whole words only), else None."""
    if j == len(pat):
        return i
    p = pat[j]
    if p is None:
        for gap in range(_FILLER_MAX + 1):
            end = _match_from(toks, pat, i + gap, j + 1)
            if end is not None:
                return end
        return None
    if i < len(toks) and toks[i] in p:
        return _match_from(toks, pat, i + 1, j + 1)
    return None


def _has_words(text: str, patterns: tuple[tuple[str, bool], ...]) -> bool:
    toks = _tokens(text)
    for raw, guarded in patterns:
        pat = _COMPILED.setdefault(raw, _compile(raw))
        for i in range(len(toks)):
            end = _match_from(toks, pat, i, 0)
            if end is None:
                continue
            if guarded and ((i > 0 and toks[i - 1] in _NEG) or any(t in _NEG for t in toks[end : end + 2])):
                continue
            return True
    return False


_COMPILED: dict[str, tuple[frozenset[str] | None, ...]] = {}


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
    """A help word (whole word; stretched spellings count) or a fall / chest-pain / breathing phrase: SOS-grade."""
    return _has_words(text, tuple((h, False) for h in HELP)) or _has_words(text, EMERGENCY_BODY)


def is_fine(text: str) -> bool:
    """'I am fine' / 'I have it' said by the parent: the nudge ladder may stop."""
    return _has_phrase(text, FINE) and not any(w in NO for w in words(text))


LOW_CONFIDENCE = 0.30  # below this an ordinary yes/no is not trusted (help / stop / threat words still count)


def classify(text: str, confidence: float | None = None) -> str:
    """One word for a short spoken answer: silence | help | stop | no | fine | yes | unclear.

    Safety words first (help, threat, stop), then 'no' (a 'no' word wins), 'I am fine', 'yes'. Empty text is
    silence. A low-confidence transcript is 'unclear' unless it carries a help / threat / stop phrase: Robin
    never reads 'all is well' or consent into noise.
    """
    if not (text or "").strip():
        return "silence"
    if is_help(text) or is_threat(text):
        return "help"
    if is_stop(text):
        return "stop"
    if confidence is not None and confidence < LOW_CONFIDENCE:
        return "unclear"
    yn = yesno(text)
    if yn is False:
        return "no"
    if is_fine(text):
        return "fine"
    return "yes" if yn else "unclear"


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
