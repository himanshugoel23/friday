# ruff: noqa: E501
"""Numbers, prices, times and phone numbers read the way people say them in Hinglish.

``speak_numbers("Teen baje 450 rupaye", "hinglish")`` -> "Teen baje chaar sau pachaas rupaye".
Roman Hinglish only; English and Devanagari text is returned unchanged (English TTS reads digits
well; Devanagari numbers are not covered yet). The spellings are phonetic guesses for the TTS and
are UNVERIFIED until the founder hears ``friday voice human-preview``.
"""

from __future__ import annotations

import re

_U = ["zero", "ek", "do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau", "das", "gyarah", "barah", "terah", "chaudah", "pandrah", "solah", "satrah", "atharah", "unnis", "bees", "ikkis", "baais", "teis", "chaubis", "pachchis", "chhabbis", "sattais", "atthais", "unnatis", "tees", "ikatis", "battis", "taintis", "chauntis", "paintis", "chhattis", "saintis", "adtis", "unchalis", "chalis", "iktalis", "bayalis", "taintalis", "chauvalis", "paintalis", "chhiyalis", "saintalis", "adtalis", "unchas", "pachaas", "ikyavan", "bavan", "trepan", "chauvan", "pachpan", "chhappan", "sattavan", "atthavan", "unsath", "saath", "iksath", "baasath", "tirsath", "chausath", "painsath", "chhiyasath", "adsath", "athsath", "unhattar", "sattar", "ikhattar", "bahattar", "tihattar", "chauhattar", "pachhattar", "chhihattar", "satattar", "athattar", "unyasi", "assi", "ikyasi", "bayasi", "tirasi", "chaurasi", "pachasi", "chhiyasi", "sataasi", "athasi", "nauasi", "nabbe", "ikyanve", "bayanve", "tiranve", "chauranve", "pachanve", "chhiyanve", "sattanve", "atthanve", "ninyanve"]
assert len(_U) == 100
DIGIT = ["zero", "ek", "do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau"]


def number_words(n: int) -> str:
    """0..99,99,999 in spoken Hinglish ('dedh sau', 'dhai hazaar', 'chaar sau pachaas')."""
    if n < 0:
        return "minus " + number_words(-n)
    if n < 100:
        return _U[n]
    if n == 150:
        return "dedh sau"
    if n == 250:
        return "dhai sau"
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{_U[h]} sau" + (f" {_U[r]}" if r else "")
    if n == 1500:
        return "dedh hazaar"
    if n == 2500:
        return "dhai hazaar"
    if n < 100000:
        t, r = divmod(n, 1000)
        return f"{_U[t]} hazaar" + (f" {number_words(r)}" if r else "")
    if n < 10000000:
        lk, r = divmod(n, 100000)
        return f"{_U[lk] if lk < 100 else number_words(lk)} lakh" + (f" {number_words(r)}" if r else "")
    cr, r = divmod(n, 10000000)
    return f"{number_words(cr)} crore" + (f" {number_words(r)}" if r else "")


def digits_words(s: str) -> str:
    return " ".join(DIGIT[int(c)] for c in s if c.isdigit())


def phone_words(digits: str) -> str:
    """10 digits -> groups 3-4-3 with commas (the voice pauses at commas)."""
    d = re.sub(r"\D", "", digits)
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 10:
        return ", ".join(digits_words(g) for g in (d[:3], d[3:7], d[7:]))
    return digits_words(d)


def _period(h24: int, explicit: bool) -> str:
    if not explicit:
        return ""
    if h24 < 4:
        return "raat"
    if h24 < 12:
        return "subah"
    if h24 < 16:
        return "dopahar"
    if h24 < 19:
        return "shaam"
    return "raat"


def time_words(hour: int, minute: int, mer: str | None = None) -> str:
    """5:30 pm -> 'shaam saade paanch baje'; 5:15 -> 'sawa paanch baje'; 5:45 -> 'paune chhe baje'."""
    m = (mer or "").lower().replace(".", "")
    h24 = hour % 24
    if m == "pm" and hour < 12:
        h24 = hour + 12
    elif m == "am" and hour == 12:
        h24 = 0
    h12 = h24 % 12 or 12
    explicit = bool(m) or hour >= 13 or hour == 0
    per = _period(h24, explicit)
    pre = f"{per} " if per else ""
    nxt = (h12 % 12) + 1
    if minute == 0:
        return f"{pre}{_U[h12]} baje"
    if minute == 15:
        return f"{pre}sawa {_U[h12]} baje"
    if minute == 30:
        return f"{pre}{'derh' if h12 == 1 else 'dhai' if h12 == 2 else 'saade ' + _U[h12]} baje"
    if minute == 45:
        return f"{pre}paune {_U[nxt]} baje"
    return f"{pre}{_U[h12]} bajkar {_U[minute]} minute"


_RUPEE = r"(?:₹|rs\.?|inr)\s*"
_NUMTXT = r"\d{1,3}(?:,\d{2,3})+|\d+"
_RE_PRICE_PRE = re.compile(rf"{_RUPEE}({_NUMTXT})", re.I)
_RE_PRICE_POST = re.compile(rf"\b({_NUMTXT})\s*(?:rs\.?|rupees?|rupaye|rupaiye|₹)(?=\W|$)", re.I)
_RE_TIME = re.compile(r"\b(\d{1,2})[:.](\d{2})(?:\s*(a\.?m\.?|p\.?m\.?))?(?!\d)", re.I)
_RE_TIME_MER = re.compile(r"\b(\d{1,2})\s*(a\.?m\.?|p\.?m\.?)(?=\W|$)", re.I)
_RE_PHONE = re.compile(r"(?<![\d])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\d])")
_RE_NUM = re.compile(rf"(?<![\w.])({_NUMTXT})(?![\w])")
_SECRET = re.compile(r"\b(otp|pin|cvv|password)\b", re.I)


def speak_numbers(text: str, language: str = "hinglish") -> str:
    """Rewrite digits as spoken words. Other languages / empty text / secrets: unchanged."""
    if not text or language != "hinglish" or _SECRET.search(text):
        return text

    def price(m: re.Match[str]) -> str:
        n = int(m.group(1).replace(",", ""))
        return f"{number_words(n)} rupaye"

    out = _RE_PHONE.sub(lambda m: phone_words(m.group(0)), text)
    out = _RE_PRICE_PRE.sub(price, out)
    out = _RE_PRICE_POST.sub(price, out)
    out = _RE_TIME.sub(
        lambda m: time_words(int(m.group(1)), int(m.group(2)), m.group(3))
        if int(m.group(1)) <= 24 and int(m.group(2)) < 60 else m.group(0), out)
    out = _RE_TIME_MER.sub(lambda m: time_words(int(m.group(1)), 0, m.group(2)) if int(m.group(1)) <= 12 else m.group(0), out)
    out = _RE_NUM.sub(lambda m: number_words(int(m.group(1).replace(",", ""))) if len(m.group(1)) <= 9 else digits_words(m.group(1)), out)
    out = re.sub(r"\b(subah|dopahar|shaam|raat) (?=(?:subah|dopahar|shaam|raat) )", "", out)
    return re.sub(r"\bbaje(?: baje)+\b", "baje", out)
