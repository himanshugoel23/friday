"""Turning the salon's words into small, safe values: numbers, times, prices, names.

Whatever a model (or the heuristic) extracts is cleaned HERE before it can reach a spoken
line: a price must be an int in a sane range, a time must be built only from digits and a
fixed vocabulary, a stylist name only letters. So even a hostile or confused extraction
cannot put free text into Friday's mouth.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from friday.core.clock import IST, ensure_utc, to_ist

MAX_PRICE_INR = 50_000
MAX_DURATION_MIN = 600

_DEV_DIGITS = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")}

_UNITS: dict[str, int] = {
    "zero": 0, "shunya": 0, "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3,
    "char": 4, "chaar": 4, "four": 4, "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "chhah": 6,
    "chah": 6, "che": 6, "chhey": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8,
    "nau": 9, "nine": 9, "das": 10, "dus": 10, "ten": 10, "gyarah": 11, "gyaarah": 11,
    "eleven": 11, "barah": 12, "baarah": 12, "twelve": 12, "terah": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19, "bees": 20,
    "pachchis": 25, "paintis": 35, "paintalis": 45, "pachhattar": 75,
    "tees": 30, "tis": 30, "chalis": 40, "pachas": 50, "pachaas": 50, "saath": 60, "sath": 60,
    "sattar": 70, "assi": 80, "nabbe": 90,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "छे": 6,
    "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "बीस": 20, "तीस": 30,
    "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
}  # fmt: skip
_HUNDRED = {"sau", "सौ", "hundred"}
_THOUSAND = {"hazaar", "hazar", "हजार", "हज़ार", "thousand"}
_HALF_PREFIX = {"saadhe": 0.5, "sadhe": 0.5, "साढ़े": 0.5, "साढे": 0.5}
_FRACTION = {"dedh": 1.5, "डेढ़": 1.5, "dhai": 2.5, "ढाई": 2.5}

_TOKEN = re.compile(r"[\wऀ-ॿ]+", re.U)


def normalise(text: str) -> str:
    """Lower-case, NFKC, Devanagari digits -> ASCII, single spaces."""
    t = unicodedata.normalize("NFKC", text or "").lower().translate(_DEV_DIGITS)
    return re.sub(r"\s+", " ", t).strip()


def words_to_numbers(text: str) -> list[tuple[int, int, int]]:
    """Spoken numbers in ``text``: ``[(value, start, end)]`` for digit runs AND Hindi/Hinglish
    number words ("paanch sau" = 500, "dhai sau" = 250, "chhe" = 6)."""
    t = normalise(text)
    out: list[tuple[int, int, int]] = []
    toks = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(t)]
    i = 0
    while i < len(toks):
        w, s, e = toks[i]
        if w.isdigit():
            out.append((int(w), s, e))
            i += 1
            continue
        if w in _UNITS or w in _FRACTION or w in _HALF_PREFIX or w in _HUNDRED or w in _THOUSAND:
            total = 0.0
            cur = 0.0
            j = i
            start = s
            end = e
            used = False
            while j < len(toks):
                x, _xs, xe = toks[j]
                if x in _UNITS:
                    cur += _UNITS[x]
                elif x in _FRACTION:
                    cur += _FRACTION[x]
                elif x in _HALF_PREFIX:  # "saadhe teen sau" = 3.5 * 100
                    if j + 1 < len(toks) and toks[j + 1][0] in _UNITS:
                        j += 1
                        cur += _UNITS[toks[j][0]] + 0.5
                        xe = toks[j][2]
                    else:
                        break
                elif x in _HUNDRED:
                    cur = (cur or 1) * 100
                    total += cur
                    cur = 0
                elif x in _THOUSAND:
                    cur = (cur or 1) * 1000
                    total += cur
                    cur = 0
                else:
                    break
                used = True
                end = xe
                j += 1
            if used:
                out.append((int(round(total + cur)), start, end))
            i = max(j, i + 1)
            continue
        i += 1
    return out


# --------------------------------------------------------------------------- times

_PERIODS = {
    "subah": "subah", "morning": "subah", "सुबह": "subah", "savere": "subah",
    "dopahar": "dopahar", "afternoon": "dopahar", "दोपहर": "dopahar", "noon": "dopahar",
    "shaam": "shaam", "sham": "shaam", "evening": "shaam", "शाम": "shaam",
    "raat": "raat", "night": "raat", "रात": "raat",
}  # fmt: skip
_DAYS = {
    "kal": "kal", "tomorrow": "kal", "कल": "kal", "aaj": "aaj", "today": "aaj", "आज": "aaj",
    "parso": "parso", "parson": "parso", "परसों": "parso", "day after": "parso",
}  # fmt: skip
_DAY_OFFSET = {"aaj": 0, "kal": 1, "parso": 2}
_BAJE = r"(?:baje|bje|bajey|baj|o'?clock|बजे)"
_RE_DIGIT_TIME = re.compile(
    rf"(?<![\d:])(\d{{1,2}})(?::(\d{{2}}))?\s*({_BAJE}|am|pm|a\.m\.|p\.m\.)"
)
_RE_PERIOD_DIGIT = re.compile(
    r"(subah|shaam|sham|dopahar|raat|evening|morning|night|सुबह|शाम|दोपहर|रात)"
    r"\s*(?:ko|mein|me|tak|se)?\s*(\d{1,2})(?::(\d{2}))?(?!\d)"
)
_RE_CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")


@dataclass(frozen=True)
class ParsedTime:
    hour24: int
    minute: int
    day: str | None  # aaj / kal / parso / None
    period: str  # subah / dopahar / shaam / raat
    pos: int = field(default=-1, compare=False)  # where it was heard in the normalised text

    @property
    def text(self) -> str:
        h12 = self.hour24 % 12 or 12
        mm = f":{self.minute:02d}" if self.minute else ""
        head = f"{self.day} " if self.day else ""
        return f"{head}{self.period} {h12}{mm} baje"


def _period_for(hour24: int) -> str:
    if hour24 < 12:
        return "subah"
    if hour24 < 16:
        return "dopahar"
    if hour24 < 20:
        return "shaam"
    return "raat"


def _to_24(hour: int, minute: int, marker: str | None, period_word: str | None) -> int | None:
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None
    m = (marker or "").replace(".", "")
    if m == "pm" or period_word in ("shaam", "raat", "dopahar"):
        if hour < 12 and not (period_word == "dopahar" and hour in (10, 11)):
            hour += 12
        if period_word == "dopahar" and hour == 24:
            hour = 12
        return hour % 24
    if m == "am" or period_word == "subah":
        return 0 if hour == 12 else hour
    if hour == 0 or hour > 12:
        return hour
    # no am/pm and no period: a salon visit at 1-8 means afternoon/evening, 9-11 morning
    if hour <= 8:
        return hour + 12
    if hour == 12:
        return 12
    return hour


def _words_in(t: str, table: dict[str, str]) -> list[tuple[int, int, str]]:
    """(start, end, value) of every table word in ``t`` (already normalised)."""
    out = []
    for word, val in table.items():
        for m in re.finditer(rf"(?<![\w]){re.escape(word)}(?![\w])", t):
            out.append((m.start(), m.end(), val))
    return sorted(out)


def find_day(text: str) -> str | None:
    hits = _words_in(normalise(text), _DAYS)
    return hits[0][2] if hits else None


def find_period(text: str) -> str | None:
    hits = _words_in(normalise(text), _PERIODS)
    return hits[0][2] if hits else None


def _near(hits: list[tuple[int, int, str]], pos: int, before: int, after: int) -> str | None:
    """The table word closest to ``pos``: preferably just before it, else just after it."""
    prior = [h for h in hits if h[1] <= pos and pos - h[1] <= before]
    if prior:
        return prior[-1][2]
    later = [h for h in hits if h[0] >= pos and h[0] - pos <= after]
    return later[0][2] if later else None


def parse_times(text: str, *, limit: int = 3) -> list[ParsedTime]:
    """Times of day mentioned in ``text`` (digits "6 baje", "6:30 pm", "shaam 6", words
    "chhe baje"), de-duplicated in order of appearance. Each time takes the day / period word
    nearest to it ("kal subah 11 baje ya dopahar 2 baje" -> 11 am tomorrow, 2 pm tomorrow)."""
    t = normalise(text)
    days = _words_in(t, _DAYS)
    periods = _words_in(t, _PERIODS)
    found: list[tuple[int, int, str | None, str | None, int, int]] = []
    # hour, minute, marker, period, pos (of the number), end of the time expression

    for m in _RE_DIGIT_TIME.finditer(t):
        marker = m.group(3)
        marker = marker if marker in ("am", "pm", "a.m.", "p.m.") else None
        found.append((int(m.group(1)), int(m.group(2) or 0), marker, None, m.start(), m.end()))
    taken = [(x[4], x[5]) for x in found]
    for m in _RE_PERIOD_DIGIT.finditer(t):
        if any(a <= m.start(2) < b for a, b in taken):
            continue
        found.append(
            (int(m.group(2)), int(m.group(3) or 0), None, _PERIODS[m.group(1)], m.start(2), m.end())
        )
    for m in _RE_CLOCK.finditer(t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        found.append((int(m.group(1)), int(m.group(2)), None, None, m.start(), m.end()))
    for val, s0, e0 in words_to_numbers(t):  # number words directly before "baje"
        if re.match(rf"\s*{_BAJE}", t[e0 : e0 + 12]) and not any(abs(x[4] - s0) < 3 for x in found):
            found.append((val, 0, None, None, s0, e0))
    found.sort(key=lambda x: x[4])
    one_day = {h[2] for h in days}
    one_period = {h[2] for h in periods}
    out: list[ParsedTime] = []
    for h, mi, marker, per, pos, end in found:
        day = _near(days, pos, 14, 0) or (next(iter(one_day)) if len(one_day) == 1 else None)
        per = per or _near(periods, pos, 14, 0) or _near(periods, end, 0, 10) or (
            next(iter(one_period)) if len(one_period) == 1 else None
        )
        h24 = _to_24(h, mi, marker, per)
        if h24 is None:
            continue
        pt = ParsedTime(h24, mi, day, _period_for(h24), pos)
        if all((p.hour24, p.minute) != (pt.hour24, pt.minute) for p in out):
            out.append(pt)
        if len(out) >= limit:
            break
    return out


_TIME_OK = re.compile(
    r"^(?:(?:aaj|kal|parso) )?(?:(?:subah|dopahar|shaam|raat) )?\d{1,2}(?::\d{2})? baje$"
)


def clean_time(value: object) -> str | None:
    """A time as a safe spoken phrase ("kal shaam 6 baje") or None. Accepts what a model
    returned ("6 baje", "6pm", "18:00", "kal shaam 6") and rebuilds it from parts."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or len(s) > 40:
        return None
    parsed = parse_times(s, limit=1)
    if not parsed:
        # a bare hour from a model ("6") is accepted only as digits
        m = re.fullmatch(r"\s*(?:(aaj|kal|parso)\s+)?(\d{1,2})\s*", normalise(s))
        if not m:
            return None
        h24 = _to_24(int(m.group(2)), 0, None, find_period(s))
        if h24 is None:
            return None
        parsed = [ParsedTime(h24, 0, m.group(1), _period_for(h24))]
    text = parsed[0].text
    return text if _TIME_OK.match(text) else None


def requested_time(text: str | None) -> str | None:
    """The ONE specific time a task names ("aaj shaam 5 baje" -> "aaj shaam 5 baje"), else None.
    A range ("shaam 5 se 8 baje ke beech"), two options ("5 ya 6 baje") or just a part of the
    day ("kal shaam") is not a specific time."""
    t = normalise(text or "")
    if not t or re.search(r"\bbeech\b|\btak\b|\bya\b|\bor\b", t):
        return None
    if re.search(r"\d\s*(?:baje\s*)?(?:se|to|-)\s*\d", t):
        return None
    pts = parse_times(t, limit=3)
    if len(pts) != 1:
        return None
    return clean_time(pts[0].text)


def with_day(phrase: str, day: str | None) -> str:
    """Add a day word ("kal") to a clean time phrase that has none."""
    if not day or re.match(r"(aaj|kal|parso) ", phrase):
        return phrase
    return f"{day} {phrase}"


def slot_label(phrase: str, *, asked_day: str | None = None) -> str:
    """User-facing label of a slot ("4 PM"; "Parso 5:30 PM" if not the day that was asked)."""
    pt = parsed_from_clean(phrase)
    if pt is None:
        return phrase
    h12 = pt.hour24 % 12 or 12
    mm = f":{pt.minute:02d}" if pt.minute else ""
    label = f"{h12}{mm} {'AM' if pt.hour24 < 12 else 'PM'}"
    if pt.day and pt.day != asked_day:
        label = f"{pt.day.title()} {label}"
    return label


def join_slots(times: list[str]) -> str:
    """"kal subah 11 baje ya kal dopahar 2 baje" -> "kal subah 11 baje ya dopahar 2 baje"."""
    out: list[str] = []
    first_day = None
    for i, t in enumerate(times[:2]):
        m = re.match(r"(aaj|kal|parso) (.*)", t)
        if i == 0:
            first_day = m.group(1) if m else None
            out.append(t)
        elif m and m.group(1) == first_day:
            out.append(m.group(2))
        else:
            out.append(t)
    return " ya ".join(out)


def parsed_from_clean(text: str) -> ParsedTime | None:
    """Inverse of ``ParsedTime.text`` for an already-clean phrase."""
    m = re.fullmatch(
        r"(?:(aaj|kal|parso) )?(subah|dopahar|shaam|raat) (\d{1,2})(?::(\d{2}))? baje", text or ""
    )
    if not m:
        return None
    h12 = int(m.group(3))
    per = m.group(2)
    h24 = h12 % 12 + (12 if per in ("shaam", "raat") or (per == "dopahar" and h12 != 12) else 0)
    if per == "dopahar" and h12 == 12:
        h24 = 12
    return ParsedTime(h24 % 24, int(m.group(4) or 0), m.group(1), per)


def resolve_slot_at(
    text: str, *, now: datetime, window_start: datetime | None = None
) -> datetime | None:
    """Aware-UTC start of the slot named by a clean time phrase, or None if unsure.

    The date is the spoken day word ("kal") relative to ``now``; with no day word it is the
    day the user asked for (the IST date of ``window_start``), else today."""
    pt = parsed_from_clean(text)
    if pt is None:
        return None
    base = to_ist(now).date()
    if pt.day is not None:
        base = base + timedelta(days=_DAY_OFFSET[pt.day])
    elif window_start is not None:
        base = to_ist(window_start).date()
    local = datetime(base.year, base.month, base.day, pt.hour24, pt.minute, tzinfo=IST)
    return ensure_utc(local)


# --------------------------------------------------------------------------- price / misc

_RUPEE_WORDS = r"(?:rupees?|rupaye|rupaya|rupay|rs\.?|inr|₹|रुपये|रुपए|रू|रु|/-)"
_PRICE_CUE = re.compile(
    r"lagega|lagegi|lagenge|charge|rate|price|cost|paise|paisa|rupa|rs\b|₹|पड़ेगा|लगेगा|"
    r"रुपये|रुपए|चार्ज|रेट|कीमत|total|hoga|hogi|ka hai|ke hain|only|bas",
    re.I,
)
_DUR_WORDS = r"(?:minutes?|mins?|min\b|minute|मिनट|ghanta|ghante|ghanta|hours?|hr|घंटा|घंटे)"


def clean_price(value: object) -> int | None:
    try:
        n = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= MAX_PRICE_INR else None


def clean_duration(value: object) -> int | None:
    try:
        n = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= MAX_DURATION_MIN else None


_NAME_OK = re.compile(r"^[A-Za-zऀ-ॿ][A-Za-zऀ-ॿ' .-]{1,23}$")


def clean_name(value: object) -> str | None:
    """A person's name: letters only, short. Devanagari names are not spoken (Hinglish only),
    so they are dropped."""
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    if not _NAME_OK.match(s) or re.search(r"[ऀ-ॿ]", s):
        return None
    if re.search(r"\b(otp|pin|cvv|card|password)\b", s, re.I):
        return None
    return s.title()


def price_and_duration(text: str) -> tuple[list[int], int | None]:
    """(prices, duration_min) found in ``text``. Prices are numbers tied to a rupee word or,
    with a price cue in the sentence, any number >= 50 that is not a time or a duration."""
    prices, duration, _spans = price_details(text)
    return prices, duration


def price_details(text: str) -> tuple[list[int], int | None, list[int]]:
    """Like ``price_and_duration`` plus the position of each price in the normalised text."""
    t = normalise(text)
    nums = words_to_numbers(t)
    time_spans: list[tuple[int, int]] = []
    for m in _RE_DIGIT_TIME.finditer(t):
        time_spans.append((m.start(), m.end()))
    for _val, s, e in nums:
        if re.match(rf"\s*{_BAJE}", t[e : e + 12]):
            time_spans.append((s, e))
    for m in _RE_PERIOD_DIGIT.finditer(t):
        time_spans.append((m.start(2), m.end(2)))
    duration: int | None = None
    used_dur: set[int] = set()
    for val, s, e in nums:
        if re.match(rf"\s*{_DUR_WORDS}", t[e : e + 14]):
            hours = bool(re.match(r"\s*(ghanta|ghante|hours?|hr|घंटा|घंटे)", t[e : e + 14]))
            duration = clean_duration(val * 60 if hours else val)
            used_dur.add(s)
    half_hour = re.search(r"aadha ghanta|half an hour|आधा घंटा", t)
    if duration is None and half_hour:
        duration = 30
    cue = bool(_PRICE_CUE.search(t))
    prices: list[int] = []
    spans: list[int] = []
    for val, s, e in nums:
        if s in used_dur or any(a <= s < b for a, b in time_spans):
            continue
        before = t[max(0, s - 8) : s]
        after = t[e : e + 10]
        tied = re.search(rf"{_RUPEE_WORDS}\s*$", before) or re.match(rf"\s*{_RUPEE_WORDS}", after)
        if tied or (cue and val >= 50):
            p = clean_price(val)
            if p is not None:
                prices.append(p)
                spans.append(s)
    return prices, duration, spans
