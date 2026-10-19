"""Turn what the user says into life events and commitments. Deterministic first.

    "kal 2 baje interview hai"        -> interview, tomorrow 14:00
    "parso shaam 6 baje dentist"      -> appointment, day after tomorrow 18:00
    "bijli ka bill 20 ko"             -> bill due on the next 20th
    "mummy ki dawai 8 baje roz"       -> daily commitment 08:00 about "mummy"

``parse_message`` is pure (text + clock -> ``Parsed``). ``capture_message`` stores the result,
warns about clashes and returns the confirmation text. Unclear input gives exactly ONE clarifying
question; the caller keeps ``result.pending`` and passes the user's next message as ``pending=``
(the two texts are parsed together, so there is no hidden state).

Conventions (documented in docs/LIFE_STATE.md, all shown back in the confirmation so the user can
correct them):
  * no am/pm word: 1-6 -> afternoon/evening, 7-11 -> morning (evening for dinner/party/movie),
    12 alone is ambiguous and is asked;
  * "raat 12 baje" is midnight at the END of the named day; "raat 1..5 baje" is after midnight of
    the day that follows the named day;
  * a weekday name means its next occurrence; "agle <weekday>" is strictly after today;
  * a day-of-month ("20 ko") is the next such day, clamped to short months;
  * a time with no date is today if still ahead, else tomorrow.
The model hook (``CaptureLLM``) is only consulted when the rules found nothing; its proposal is
re-validated by code and confirmed back like any other capture.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from friday.core.clock import at_ist, to_ist
from friday.lifestate import copy
from friday.lifestate.kinds import default_protected, guess_kind
from friday.lifestate.models import (
    EventKind,
    EventSource,
    LifeCommitment,
    LifeEvent,
    PersonRef,
    Repeat,
    aware,
    clean_text,
    default_duration,
)
from friday.lifestate.ports import CaptureLLM
from friday.lifestate.recur import next_occurrence
from friday.lifestate.store import LifeStore
from friday.lifestate.sync import find_clashes

_I = re.IGNORECASE

# --------------------------------------------------------------------------- vocabulary
NUMW = {
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "chaar": 4,
    "paanch": 5,
    "panch": 5,
    "chhe": 6,
    "chhah": 6,
    "cheh": 6,
    "saat": 7,
    "aath": 8,
    "nau": 9,
    "das": 10,
    "gyarah": 11,
    "barah": 12,
}
NUM = r"(?:\d{1,2}|" + "|".join(sorted(NUMW, key=len, reverse=True)) + r")"

MONTHS = {
    "jan": 1,
    "january": 1,
    "janwari": 1,
    "feb": 2,
    "february": 2,
    "farwari": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "joon": 6,
    "jul": 7,
    "july": 7,
    "julai": 7,
    "aug": 8,
    "august": 8,
    "agast": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "sitambar": 9,
    "oct": 10,
    "october": 10,
    "aktubar": 10,
    "aktoobar": 10,
    "nov": 11,
    "november": 11,
    "navambar": 11,
    "dec": 12,
    "december": 12,
    "disambar": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

WEEKDAYS = {
    "somvar": 0,
    "somwar": 0,
    "monday": 0,
    "mangalvar": 1,
    "mangalwar": 1,
    "mangal": 1,
    "tuesday": 1,
    "budhvar": 2,
    "budhwar": 2,
    "budh": 2,
    "wednesday": 2,
    "guruvar": 3,
    "guruwar": 3,
    "brihaspativar": 3,
    "veervar": 3,
    "virvar": 3,
    "thursday": 3,
    "shukravar": 4,
    "shukrawar": 4,
    "shukar": 4,
    "friday": 4,
    "shanivar": 5,
    "shaniwar": 5,
    "shani": 5,
    "saturday": 5,
    "ravivar": 6,
    "raviwar": 6,
    "itwar": 6,
    "itwaar": 6,
    "sunday": 6,
}
_WD_RE = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

PERIOD_RE = re.compile(
    r"\b(subah|savere|sabah|morning|dopahar|dophar|dupahar|afternoon|shaam|sham|evening|"
    r"raat|rat|night|tonight|midnight)\b",
    _I,
)
PERIOD_NORM = {
    "subah": "morning",
    "savere": "morning",
    "sabah": "morning",
    "morning": "morning",
    "dopahar": "noon",
    "dophar": "noon",
    "dupahar": "noon",
    "afternoon": "noon",
    "shaam": "evening",
    "sham": "evening",
    "evening": "evening",
    "raat": "night",
    "rat": "night",
    "night": "night",
    "tonight": "night",
    "midnight": "night",
}
PERIOD_DEFAULT_HOUR = {"morning": 9, "noon": 13, "evening": 18, "night": 21}
EVENING_BIAS = re.compile(
    r"\b(dinner|party|movie|shaadi|wedding|function|puja|pooja|aarti|show)\b", _I
)

RELATIONS = {
    "mummy": "mother",
    "mom": "mother",
    "maa": "mother",
    "mother": "mother",
    "mama": "uncle",
    "papa": "father",
    "dad": "father",
    "pitaji": "father",
    "father": "father",
    "dadi": "grandmother",
    "nani": "grandmother",
    "dada": "grandfather",
    "nana": "grandfather",
    "bhai": "brother",
    "behen": "sister",
    "didi": "sister",
    "bhabhi": "sister-in-law",
    "wife": "spouse",
    "biwi": "spouse",
    "husband": "spouse",
    "pati": "spouse",
    "beta": "child",
    "beti": "child",
    "bachhe": "child",
}

TASK_REQUEST = re.compile(
    r"\b(book|karwa|karva|order|dhundh|dhoond|find|search|quote|cancel|bhej do|bhejo|"
    r"kar do|kardo|kar dijiye|kijiye|kariye|karo|karwa do)\b",
    _I,
)
REMIND_CUE = re.compile(r"\b(yaad\s*dila\w*|yaad\s*rakh\w*|remind\w*|yaad\s*dil\w*)\b", _I)
OBLIGATION = re.compile(
    r"\b(karna|karni|karne|lena|lene|dena|dene|bharna|bharni|jaana|jana|bhejna|lana|lani|"
    r"pick\s*up|call|phone)\s+(hai|hoga|padega|h|chahiye)\b",
    _I,
)
CALL_PERSON = re.compile(r"\b(call|phone|fon)\s+(karna|karni|karne)\b", _I)
STATEMENT = re.compile(
    r"\b(hai|hain|hoga|hogi|ho|h|tha|rakha|fix|scheduled|schedule|booked|set|aana|aani|jaana|plan)\b",
    _I,
)
MEDICINE = re.compile(r"\b(dawai|dawa|medicine|goli|tablet|insulin|injection|dose)\b", _I)
QUESTION = re.compile(r"\?|^\s*(kya|kab|kaun|kitne|kitna|kaise|kyun|when|what|who|how)\b", _I)
PAST_MARKER = re.compile(r"\b(tha|thi|the|hua|huyi|gaya|gayi|gaye)\b", _I)

EDGE_FILLER = {
    "hai",
    "hain",
    "hoga",
    "hogi",
    "tha",
    "thi",
    "he",
    "ho",
    "ko",
    "ka",
    "ki",
    "ke",
    "se",
    "tak",
    "par",
    "pe",
    "mein",
    "me",
    "toh",
    "to",
    "yaad",
    "rakhna",
    "rakho",
    "dilana",
    "dilao",
    "dena",
    "mujhe",
    "mera",
    "meri",
    "mere",
    "aur",
    "ek",
    "the",
    "a",
    "an",
    "at",
    "on",
    "in",
    "by",
    "my",
    "i",
    "have",
    "has",
    "is",
    "bata",
    "karna",
    "karni",
    "karne",
    "h",
    "bhi",
    "ya",
    "hi",
    "aaj",
    "kal",
    "ab",
    "wala",
    "wali",
    "wale",
    "hai.",
    "-",
    ",",
    ".",
    "reminder",
    "remind",
    "friday",
    "set",
    "rakh",
    "lo",
    "le",
    "lena",
}


# --------------------------------------------------------------------------- when-parsing
def _num(tok: str) -> int:
    t = tok.lower()
    return int(t) if t.isdigit() else NUMW[t]


@dataclass
class _Clock:
    hour: int  # as typed (1-12) or 0-23
    minute: int = 0
    ampm: str | None = None  # "am" | "pm" | None
    span: tuple[int, int] = (0, 0)


@dataclass
class When:
    day: date | None = None
    clock: _Clock | None = None
    end_clock: _Clock | None = None
    period: str | None = None
    relative: datetime | None = None  # "2 ghante baad"
    repeat: Repeat | None = None
    month_end: bool = False
    issues: list[str] = field(default_factory=list)
    rest: str = ""  # text left after removing every time/date phrase
    day_word: str | None = None  # kal, aaj, parso ...


def normalise(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = s.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def _cut(s: str, m: re.Match[str]) -> str:
    return s[: m.start()] + " " + s[m.end() :]


def _extract_clocks(w: str, out: When) -> str:
    # fractions of the hour: saade 3, dhai, dedh, sawa 4, paune 5
    def sub_frac(pattern: str, fn) -> None:  # noqa: ANN001
        nonlocal w
        m = re.search(pattern, w, _I)
        if m and out.clock is None:
            h, mi = fn(m)
            out.clock = _Clock(h, mi, None, m.span())
            w = _cut(w, m)

    sub_frac(
        rf"\b(?:saade|saadhe|sade|sadhe)\s+({NUM})(?:\s*(?:baje|bje|bajey))?\b",
        lambda m: (_num(m.group(1)), 30),
    )
    sub_frac(r"\b(?:dhai|dhaai|dhayi)\s*(?:baje|bje)\b", lambda m: (2, 30))
    sub_frac(r"\b(?:dedh|derh)\s*(?:baje|bje)\b", lambda m: (1, 30))
    sub_frac(
        rf"\b(?:sawa|savaa|sava|savva)\s+({NUM})(?:\s*(?:baje|bje|bajey))?\b",
        lambda m: (_num(m.group(1)), 15),
    )
    sub_frac(
        rf"\b(?:paune|pauney|pone)\s+({NUM})(?:\s*(?:baje|bje|bajey))?\b",
        lambda m: ((_num(m.group(1)) - 2) % 12 + 1, 45),
    )
    if out.clock is not None:
        return w

    # range: "2 se 3 baje", "2 baje se 3 baje tak", "2-3pm", "2:30 to 4 pm"
    rng = re.search(
        rf"\b(?P<h1>{NUM})(?:[:.](?P<m1>\d{{2}}))?\s*(?P<s1>am|pm|baje|bje)?\s*"
        rf"(?:se|to|-|till|until)\s*(?P<h2>{NUM})(?:[:.](?P<m2>\d{{2}}))?\s*"
        r"(?P<s2>am|pm|baje|bje|bajey)\b(?:\s*tak)?",
        w,
        _I,
    )
    if rng:
        s1 = (rng.group("s1") or "").lower()
        s2 = (rng.group("s2") or "").lower()
        a1 = s1 if s1 in ("am", "pm") else (s2 if s2 in ("am", "pm") else None)
        a2 = s2 if s2 in ("am", "pm") else None
        out.clock = _Clock(_num(rng.group("h1")), int(rng.group("m1") or 0), a1, rng.span())
        out.end_clock = _Clock(_num(rng.group("h2")), int(rng.group("m2") or 0), a2, rng.span())
        return _cut(w, rng)

    # single: "2 baje", "2:30 baje", "2pm", "2.30 pm", "14:00", "do baje"
    m = re.search(
        rf"\b(?P<h>{NUM})(?:[:.](?P<m>\d{{2}}))?\s*(?P<s>am|pm|baje|bje|bajey|a\.m\.|p\.m\.)"
        r"(?![a-z])",
        w,
        _I,
    )
    if not m:
        m = re.search(r"\b(?P<h>\d{1,2}):(?P<m>\d{2})\b(?:\s*(?P<s>am|pm))?", w, _I)
    if m:
        suffix = (m.groupdict().get("s") or "").lower().replace(".", "")
        ampm = suffix if suffix in ("am", "pm") else None
        h = _num(m.group("h"))
        if h <= 24:
            out.clock = _Clock(h, int(m.group("m") or 0), ampm, m.span())
            w = _cut(w, m)
    return w


def _resolve_hour(
    clk: _Clock, period: str | None, evening_bias: bool
) -> tuple[int, bool, str | None]:
    """-> (hour 0..24, after_midnight_day_shift, issue). hour 24 == midnight ending the day."""
    h, ampm = clk.hour, clk.ampm
    if h > 24 or (h == 24 and clk.minute):
        return 0, False, "bad_hour"
    if ampm == "am":
        return (0 if h == 12 else h), False, None
    if ampm == "pm":
        return (12 if h == 12 else (h % 12) + 12), False, None
    if h >= 13:
        return (0 if h == 24 else h), (h == 24), None
    if h == 0:
        return 0, False, None
    if period == "morning":
        return h % 12 if h != 12 else 0, False, None
    if period == "noon":
        if h == 12:
            return 12, False, None
        return (h + 12 if h <= 6 else h), False, None
    if period == "evening":
        return (h + 12 if h < 12 else 12), False, None
    if period == "night":
        if h == 12:
            return 24, False, None  # midnight at the end of the named day
        if h <= 5:
            return h, True, None  # after midnight, the day after the named day
        return h + 12, False, None
    # no period word
    if h == 12:
        return 12, False, "ask_12"
    if h <= 6:
        return h + 12, False, None
    if 7 <= h <= 11 and evening_bias:
        return h + 12, False, None
    return h, False, None


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 + n
    y, m = divmod(idx, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _dom_in(y: int, m: int, dom: int) -> date:
    return date(y, m, min(dom, calendar.monthrange(y, m)[1]))


def _next_valid_date(today: date, month: int, day: int) -> date | None:
    """First real date with this month/day on or after ``today`` (29 Feb waits for a leap year)."""
    for year in range(today.year, today.year + 9):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if cand >= today:
            return cand
    return None


def _next_dom(today: date, dom: int, *, next_month: bool = False) -> date:
    base = date(today.year, today.month, 1)
    if next_month:
        base = _add_months(base, 1)
        return _dom_in(base.year, base.month, dom)
    cand = _dom_in(base.year, base.month, dom)
    if cand < today:
        nb = _add_months(base, 1)
        cand = _dom_in(nb.year, nb.month, dom)
    return cand


def parse_when(text: str, now: datetime) -> When:
    """Find every date/time/repeat phrase in ``text`` (see module docstring for conventions)."""
    out = When()
    now = aware(now)
    today = to_ist(now).date()
    w = " " + normalise(text) + " "

    # --- repeats
    if m := re.search(r"\b(roz|rozana|daily|har din|har roz|everyday|every day|rozaana)\b", w, _I):
        out.repeat = Repeat(freq="daily")
        w = _cut(w, m)
    elif m := re.search(rf"\b(?:har|every)\s+({_WD_RE})\b", w, _I):
        out.repeat = Repeat(freq="weekly", weekdays=[WEEKDAYS[m.group(1).lower()]])
        w = _cut(w, m)
    elif m := re.search(r"\b(har hafte|har week|weekly|every week)\b", w, _I):
        out.repeat = Repeat(freq="weekly")
        w = _cut(w, m)
    elif m := re.search(r"\b(har mahine|har mahina|monthly|every month)\b", w, _I):
        out.repeat = Repeat(freq="monthly")
        w = _cut(w, m)

    # --- relative durations: "2 ghante baad", "aadha ghanta baad", "30 minute mein"
    if m := re.search(
        rf"\b(?P<n>{NUM}|dedh|aadha|adha|half)\s*(?P<u>ghante|ghanta|ghanta|hour|hours|hr|hrs|"
        r"minute|minutes|min|mins|mint)\s*(?:baad|mein|me|later)\b",
        w,
        _I,
    ):
        n = m.group("n").lower()
        mult = {"dedh": 1.5, "aadha": 0.5, "adha": 0.5, "half": 0.5}.get(n)
        qty = mult if mult is not None else _num(n)
        unit = m.group("u").lower()
        delta = (
            timedelta(minutes=qty)
            if unit.startswith("min") or unit == "mint"
            else timedelta(hours=qty)
        )
        out.relative = now + delta
        w = _cut(w, m)

    # --- clock times
    w = _extract_clocks(w, out)

    # --- period of day
    if pm := PERIOD_RE.search(w):
        out.period = PERIOD_NORM[pm.group(1).lower()]
        if pm.group(1).lower() == "midnight" and out.clock is None:
            out.clock = _Clock(12, 0, None, (0, 0))
        w = _cut(w, pm)
    if m := re.search(r"\baadhi raat\b", w, _I):
        out.period = "night"
        if out.clock is None:
            out.clock = _Clock(12, 0)
        w = _cut(w, m)

    # --- dates
    next_month = bool(re.search(r"\b(agle mahine|next month|agla mahina|agle month)\b", w, _I))
    if next_month:
        # "agle mahine ke end" -> "month end" (+ the next-month flag)
        w = re.sub(
            r"\b(?:agle mahine|next month|agla mahina|agle month)\s+(?:ke|ka)\s+"
            r"(?:end|ant|aakhir|akhir|last|aakhri)\b",
            " month end ",
            w,
            flags=_I,
        )
        w = re.sub(r"\b(agle mahine|next month|agla mahina|agle month)\b", " ", w, flags=_I)
    next_week = False
    if m := re.search(r"\b(agle hafte|next week|agla hafta|agle week|aane wale hafte)\b", w, _I):
        next_week = True
        w = _cut(w, m)

    if m := re.search(
        r"\b(month[- ]?end|mahine ke (?:end|ant|aakhir|akhir|last|aakhri)(?: din)?|"
        r"mahine ka (?:end|aakhir|akhir|ant)|end of (?:the )?month|mahine ke aakhri din)\b",
        w,
        _I,
    ):
        out.month_end = True
        base = date(today.year, today.month, 1)
        if next_month:
            base = _add_months(base, 1)
        out.day = _dom_in(base.year, base.month, 31)
        w = _cut(w, m)
    elif m := re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", w):
        d_, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        yr = (int(y) + 2000 if y and len(y) == 2 else int(y)) if y else today.year
        try:
            cand = date(yr, mo, d_)
            if not y and cand < today:
                cand = date(yr + 1, mo, d_)
            out.day = cand
            w = _cut(w, m)
        except ValueError:
            out.issues.append("bad_date")
    elif m := re.search(
        rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(?:ko|ki|ke)?\s*({_MONTH_RE})\b", w, _I
    ) or re.search(rf"\b({_MONTH_RE})\s*(\d{{1,2}})(?:st|nd|rd|th)?\b", w, _I):
        g1, g2 = m.group(1), m.group(2)
        day_s, mon_s = (g1, g2) if g1.isdigit() else (g2, g1)
        mo, d_ = MONTHS[mon_s.lower()], int(day_s)
        cand = _next_valid_date(today, mo, d_)
        if cand is None:
            out.issues.append("bad_date")
        else:
            out.day = cand
            w = _cut(w, m)
    elif m := (
        re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\b", w, _I)
        or re.search(r"\b(\d{1,2})\s*(?:tarikh|tareekh|taarikh|tarik|date)\b", w, _I)
        or re.search(r"\b(\d{1,2})\s*(?:ko|tak)\b", w, _I)
    ):
        dom = int(m.group(1))
        if 1 <= dom <= 31:
            out.day = _next_dom(today, dom, next_month=next_month)
            if out.repeat is not None and out.repeat.freq == "monthly":
                out.repeat.day_of_month = dom
            w = _cut(w, m)
        else:
            out.issues.append("bad_date")

    if out.day is None:
        if m := re.search(r"\b(parso|parson|day after tomorrow|parsoon)\b", w, _I):
            out.day, out.day_word = today + timedelta(days=2), "parso"
            w = _cut(w, m)
        elif m := re.search(r"\b(narso|tarso|narson)\b", w, _I):
            out.day, out.day_word = today + timedelta(days=3), "narso"
            w = _cut(w, m)
        elif m := re.search(r"\b(kal|tomorrow|tmrw|tomorow)\b", w, _I):
            out.day, out.day_word = today + timedelta(days=1), "kal"
            w = _cut(w, m)
        elif m := re.search(r"\b(aaj|aj|today|tonight)\b", w, _I):
            out.day, out.day_word = today, "aaj"
            w = _cut(w, m)
        elif m := re.search(
            rf"\b({NUM})\s*(din|days?|hafte|hafta|weeks?|mahine|mahina|months?)\s*(?:baad|mein|me|later)\b",
            w,
            _I,
        ):
            n, unit = _num(m.group(1)), m.group(2).lower()
            if unit.startswith(("din", "day")):
                out.day = today + timedelta(days=n)
            elif unit.startswith(("hafta", "hafte", "week")):
                out.day = today + timedelta(weeks=n)
            else:
                out.day = _add_months(today, n)
            w = _cut(w, m)

    if out.day is None:
        qual = r"(?:(?P<q>agle|agla|aglay|next|aane wale|aane wala|is|this|pichle|pichla|last)\s+)?"
        if m := re.search(rf"\b{qual}(?P<wd>{_WD_RE})\b", w, _I):
            wd = WEEKDAYS[m.group("wd").lower()]
            q = (m.group("q") or "").lower()
            if q in ("pichle", "pichla", "last"):
                out.issues.append("past_weekday")
            if next_week:
                monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
                out.day = monday + timedelta(days=wd)
            else:
                delta = (wd - today.weekday()) % 7
                if q in ("agle", "agla", "aglay", "next", "aane wale", "aane wala") and delta == 0:
                    delta = 7
                out.day = today + timedelta(days=delta)
                out.day_word = "weekday:" + q
            w = _cut(w, m)
        elif next_week:
            out.issues.append("week_only")

    if out.day_word == "kal" and PAST_MARKER.search(w):
        out.issues.append("kal_past")
    out.rest = re.sub(r"\s+", " ", w).strip()
    return out


# --------------------------------------------------------------------------- parsing a message
@dataclass
class Parsed:
    status: Literal["event", "commitment", "bill", "none", "clarify"]
    title: str = ""
    kind: EventKind = EventKind.OTHER
    start: datetime | None = None
    end: datetime | None = None
    repeat: Repeat | None = None
    person: PersonRef | None = None
    question: str | None = None
    reason: str = ""
    inferred_day: bool = False


def _tidy_title(rest: str) -> str:
    toks = [t for t in re.split(r"\s+", rest.strip()) if t]
    while toks and toks[0].lower().strip(".,") in EDGE_FILLER:
        toks.pop(0)
    while toks and toks[-1].lower().strip(".,") in EDGE_FILLER:
        toks.pop()
    return clean_text(" ".join(toks).strip(" ,.-"), 120)


def _person(title: str) -> PersonRef | None:
    for tok in re.findall(r"[A-Za-z]+", title):
        rel = RELATIONS.get(tok.lower())
        if rel:
            return PersonRef(name=tok.lower(), relationship=rel)
    return None


def _combine(day: date, hour: int, minute: int, shift_days: int = 0) -> datetime:
    d = day + timedelta(days=shift_days)
    if hour == 24:
        return at_ist(d + timedelta(days=1), 0, minute)
    return at_ist(d, hour, minute)


def parse_message(text: str, now: datetime) -> Parsed:
    now = aware(now)
    raw = normalise(text)
    if not raw or len(raw) > 600:
        return Parsed("none", reason="empty_or_long")
    remind = bool(REMIND_CUE.search(raw))
    if QUESTION.search(raw) and not remind:
        return Parsed("none", reason="question")
    if TASK_REQUEST.search(raw) and not remind:
        return Parsed("none", reason="task_request")

    when = parse_when(raw, now)
    title = _tidy_title(when.rest)
    kind = guess_kind(title or raw)
    has_time = when.clock is not None or when.relative is not None
    has_when = (
        has_time or when.day is not None or when.period is not None or "week_only" in when.issues
    )
    is_bill = kind == EventKind.BILL_DUE
    wants_commit = (
        remind
        or bool(CALL_PERSON.search(raw))
        or (bool(OBLIGATION.search(raw)) and kind in (EventKind.OTHER, EventKind.PERSONAL))
        or (
            when.repeat is not None
            and not is_bill
            and kind not in (EventKind.INTERVIEW, EventKind.MEETING)
        )
        or (bool(MEDICINE.search(raw)) and kind == EventKind.OTHER)
    )
    if is_bill:
        wants_commit = False

    kind_known = kind != EventKind.OTHER
    if not (kind_known or wants_commit or (has_when and STATEMENT.search(raw))):
        return Parsed("none", reason="no_life_statement")
    if not has_when and not when.repeat:
        if kind_known or wants_commit:
            what = copy.noun(kind) if kind_known else (title or "ye")
            q = (
                copy.ask_date(what.capitalize())
                if is_bill
                else copy.ask_time(what.capitalize()).replace("kitne baje", "kab")
            )
            return Parsed("clarify", title=title, kind=kind, question=q, reason="no_when")
        return Parsed("none", reason="no_when")

    if "kal_past" in when.issues:
        return Parsed(
            "clarify", title=title, kind=kind, question=copy.ask_past_kal(), reason="kal_past"
        )
    if "week_only" in when.issues or "past_weekday" in when.issues or "bad_date" in when.issues:
        what = copy.noun(kind).capitalize() if kind_known else "Ye"
        return Parsed(
            "clarify", title=title, kind=kind, question=copy.ask_date(what), reason=when.issues[0]
        )

    # ---- resolve the clock
    evening_bias = bool(EVENING_BIAS.search(raw))
    hour = minute = None
    shift = 0
    if when.relative is not None:
        rel = to_ist(when.relative)
        base_day, hour, minute = rel.date(), rel.hour, rel.minute
        when.day = when.day or base_day
    elif when.clock is not None:
        hour, shift, issue = _resolve_hour(when.clock, when.period, evening_bias)
        shift, hour = (1 if shift else 0), hour
        if issue == "ask_12":
            return Parsed(
                "clarify", title=title, kind=kind, question=copy.ask_am_pm(12), reason="ask_12"
            )
        if issue:
            return Parsed(
                "clarify", title=title, kind=kind, question=copy.ask_unclear(), reason=issue
            )
        minute = when.clock.minute
    elif when.period is not None:
        hour, minute = PERIOD_DEFAULT_HOUR[when.period], 0
    elif is_bill:
        hour, minute = 9, 0

    end_hour = end_minute = None
    if when.end_clock is not None and hour is not None:
        eh, _, issue = _resolve_hour(when.end_clock, when.period, evening_bias)
        if (
            when.end_clock.ampm is None
            and when.clock
            and when.clock.ampm is None
            and eh <= hour
            and eh < 12
        ):
            eh += 12 if eh + 12 <= 24 and (eh + 12) > hour else 0
        end_hour, end_minute = eh, when.end_clock.minute

    # ---- recurring commitment: "mummy ki dawai 8 baje roz"
    if wants_commit:
        if hour is None and when.repeat is not None:
            return Parsed(
                "clarify",
                title=title,
                kind=kind,
                repeat=when.repeat,
                question=copy.ask_time(title or "Ye"),
                reason="no_time",
            )
        if hour is None:
            hour, minute = 9, 0
        person = _person(title or raw)
        text_ = re.sub(
            r"\s+(?:hai|hoga|padega|chahiye|h)$", "", title or clean_text(raw, 120), flags=_I
        )
        if when.repeat is not None:
            rep = when.repeat.model_copy(update={"time": f"{hour % 24:02d}:{minute:02d}"})
            due = next_occurrence(rep, now)
            if due is None:
                return Parsed("none", reason="no_occurrence")
            return Parsed(
                "commitment", title=text_, kind=kind, start=due, repeat=rep, person=person
            )
        day, inferred = _day_or_default(when, now, hour, minute or 0, shift)
        return Parsed(
            "commitment",
            title=text_,
            kind=kind,
            start=_combine(day, hour, minute or 0, shift),
            person=person,
            inferred_day=inferred,
        )

    # ---- bills: date-only
    if is_bill:
        if when.day is None:
            return Parsed(
                "clarify", title=title, kind=kind, question=copy.ask_date("Bill"), reason="no_date"
            )
        start = _combine(when.day, hour if hour is not None else 9, minute or 0, shift)
        rep = None
        if when.repeat is not None and when.repeat.freq == "monthly":
            rep = when.repeat.model_copy(
                update={
                    "time": f"{to_ist(start).hour:02d}:{to_ist(start).minute:02d}",
                    "day_of_month": when.repeat.day_of_month or to_ist(start).day,
                }
            )
        return Parsed("bill", title=title or "bill", kind=kind, start=start, end=start, repeat=rep)

    # ---- events need a time
    if hour is None:
        return Parsed(
            "clarify",
            title=title,
            kind=kind,
            repeat=when.repeat,
            question=copy.ask_time((copy.noun(kind) if kind_known else title or "Ye").capitalize()),
            reason="no_time",
        )
    day, inferred = _day_or_default(when, now, hour, minute or 0, shift)
    start = _combine(day, hour, minute or 0, shift)
    if (
        when.day is not None
        and start < now - timedelta(minutes=5)
        and when.day_word != "aaj"
        and not when.relative
    ):
        return Parsed(
            "clarify",
            title=title,
            kind=kind,
            question=copy.ask_date(copy.noun(kind).capitalize()),
            reason="past",
        )
    if start < now - timedelta(minutes=5):
        return Parsed(
            "clarify",
            title=title,
            kind=kind,
            question=copy.ask_date(copy.noun(kind).capitalize()),
            reason="past",
        )
    if end_hour is not None:
        end = _combine(day, end_hour, end_minute or 0, shift)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + default_duration(kind)
    if when.repeat is not None:
        rep = when.repeat.model_copy(
            update={"time": f"{to_ist(start).hour:02d}:{to_ist(start).minute:02d}"}
        )
    else:
        rep = None
    return Parsed(
        "event",
        title=title or copy.noun(kind),
        kind=kind,
        start=start,
        end=end,
        repeat=rep,
        inferred_day=inferred,
    )


def _day_or_default(
    when: When, now: datetime, hour: int, minute: int, shift: int
) -> tuple[date, bool]:
    if when.day is not None:
        same_weekday_today = (
            bool(when.day_word and when.day_word.startswith("weekday:"))
            and when.day == to_ist(now).date()
        )
        # the named weekday is today but that time is already over -> next week
        if same_weekday_today and _combine(when.day, hour, minute, shift) < now:
            return when.day + timedelta(days=7), False
        return when.day, False
    today = to_ist(now).date()
    if _combine(today, hour, minute, shift) > now:
        return today, True
    return today + timedelta(days=1), True


# --------------------------------------------------------------------------- storing a capture
@dataclass
class PendingCapture:
    """Keep this and pass it as ``pending=`` with the user's next message."""

    text: str


@dataclass
class CaptureResult:
    status: Literal["captured", "clarify", "none"]
    reply: str | None = None
    events: list[LifeEvent] = field(default_factory=list)
    commitments: list[LifeCommitment] = field(default_factory=list)
    pending: PendingCapture | None = None
    clashes: list[LifeEvent] = field(default_factory=list)
    via_llm: bool = False


async def capture_message(
    store: LifeStore,
    user_id: str,
    text: str,
    now: datetime,
    *,
    pending: PendingCapture | None = None,
    llm: CaptureLLM | None = None,
) -> CaptureResult:
    """Parse, store and confirm. ``status == "none"`` means: not a life statement, let the other
    handlers have the message."""
    now = aware(now)
    full = f"{pending.text} {text}" if pending else text
    parsed = parse_message(full, now)
    via_llm = False
    if (
        parsed.status in ("none", "clarify")
        and llm is not None
        and parsed.reason
        not in (
            "question",
            "task_request",
            "empty_or_long",
        )
        and parsed.status == "none"
    ):
        parsed2 = await _from_llm(llm, text, now)
        if parsed2 is not None:
            parsed, via_llm = parsed2, True

    if parsed.status == "none":
        return CaptureResult("none")
    if parsed.status == "clarify":
        return CaptureResult(
            "clarify", reply=parsed.question or copy.ask_unclear(), pending=PendingCapture(full)
        )
    assert parsed.start is not None
    now_ = now
    if parsed.status == "commitment":
        c = await _store_commitment(store, user_id, parsed, now_)
        when = copy.fmt_when(c.due, now_)
        note = None
        if c.repeat is not None:
            note = {"daily": "roz", "weekly": "har hafte", "monthly": "har mahine"}[c.repeat.freq]
        return CaptureResult(
            "captured",
            reply=copy.confirm_commitment(c.text, when, note),
            commitments=[c],
            via_llm=via_llm,
        )
    ev, clashes = await _store_event(store, user_id, parsed, now_)
    when = copy.fmt_when(ev.start, now_)
    if parsed.status == "bill":
        reply = copy.confirm_bill(
            copy.fmt_day(ev.start, now_), parsed.title if parsed.title != "bill" else None
        )
    else:
        reply = copy.confirm_event(ev.kind, when, title=ev.title)
    for c in clashes[:1]:
        reply += " " + copy.clash_note(c.kind, copy.fmt_when(c.start, now_))
    return CaptureResult("captured", reply=reply, events=[ev], clashes=clashes, via_llm=via_llm)


async def _store_event(
    store: LifeStore, user_id: str, p: Parsed, now: datetime
) -> tuple[LifeEvent, list[LifeEvent]]:
    assert p.start is not None
    end = p.end or p.start
    # saying the same thing twice must not create two events
    for e in await store.events_between(
        user_id, p.start - timedelta(minutes=1), p.start + timedelta(minutes=1)
    ):
        if (
            e.source == EventSource.USER
            and e.kind == p.kind
            and e.title.lower() == p.title.lower()
            and e.start == p.start
        ):
            return e, []
    ev = LifeEvent(
        user_id=user_id,
        title=p.title,
        start=p.start,
        end=end,
        kind=p.kind,
        source=EventSource.USER,
        protected=default_protected(p.kind) and p.status != "bill",
        repeat=p.repeat,
    )
    clashes: list[LifeEvent] = []
    if p.status != "bill":
        clashes = await find_clashes(store, user_id, ev.start, ev.end)
    await store.save_event(ev)
    return ev, clashes


async def _store_commitment(
    store: LifeStore, user_id: str, p: Parsed, now: datetime
) -> LifeCommitment:
    assert p.start is not None
    for c in await store.list_commitments(user_id, status="open"):
        if c.text.lower() == p.title.lower() and c.due == p.start:
            return c
    c = LifeCommitment(user_id=user_id, text=p.title, due=p.start, repeat=p.repeat, person=p.person)
    await store.save_commitment(c)
    return c


async def undo_last(
    store: LifeStore, user_id: str, now: datetime, *, window: timedelta = timedelta(minutes=15)
) -> bool:
    """'galat': remove the most recently captured user item, if it is fresh."""
    now = aware(now)
    best: tuple[datetime, str, str] | None = None
    for e in await store.list_events(user_id):
        if e.source == EventSource.USER and now - e.created_at <= window:
            best = max(best or (e.created_at, "e", e.id), (e.created_at, "e", e.id))
    for c in await store.list_commitments(user_id):
        if c.source == EventSource.USER and now - c.created_at <= window:
            best = max(best or (c.created_at, "c", c.id), (c.created_at, "c", c.id))
    if best is None:
        return False
    _, which, item_id = best
    return await (
        store.delete_event(user_id, item_id)
        if which == "e"
        else store.delete_commitment(user_id, item_id)
    )


# --------------------------------------------------------------------------- optional model hook
async def _from_llm(llm: CaptureLLM, text: str, now: datetime) -> Parsed | None:
    """Validate a model proposal with code. Anything odd is dropped."""
    try:
        got = await llm.extract(text, now)
    except Exception:  # noqa: BLE001
        return None
    if got is None:
        return None
    try:
        start = aware(got.start)
        end = aware(got.end) if got.end else None
        title = clean_text(got.title, 120)
        if not title or start < now - timedelta(minutes=5) or start > now + timedelta(days=400):
            return None
        if end is not None and not (start <= end <= start + timedelta(days=2)):
            return None
        try:
            kind = EventKind(got.kind) if got.kind else guess_kind(title)
        except ValueError:
            kind = guess_kind(title)
    except Exception:  # noqa: BLE001
        return None
    if got.is_commitment:
        return Parsed("commitment", title=title, kind=kind, start=start, person=_person(title))
    return Parsed(
        "event", title=title, kind=kind, start=start, end=end or start + default_duration(kind)
    )
