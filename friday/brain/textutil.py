"""Deterministic, Hinglish-aware text helpers used by the heuristic (fake-LLM) path,
the guards and the converters: normalisation, phones, money, dates/times.

Pure functions, no I/O. All datetimes returned are aware UTC; IST is used only
to interpret the user's wall-clock words ("kal shaam 6 baje").
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from friday.core.clock import at_ist, ensure_utc, to_ist
from friday.core.models import normalize_phone

# --------------------------------------------------------------------------- basics

_WS = re.compile(r"\s+")


def norm(text: str | None) -> str:
    """Lower-case, collapse whitespace, normalise curly quotes."""
    if not text:
        return ""
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", t).strip().lower()


def has_any(text: str, words: list[str] | tuple[str, ...] | set[str]) -> bool:
    """True if any of ``words`` occurs in ``text`` as a whole word/phrase."""
    return any(_word_re(w).search(text) for w in words)


def first_match(text: str, words: list[str] | tuple[str, ...]) -> str | None:
    for w in words:
        if _word_re(w).search(text):
            return w
    return None


_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _word_re(phrase: str) -> re.Pattern[str]:
    pat = _RE_CACHE.get(phrase)
    if pat is None:
        esc = re.escape(phrase.lower()).replace(r"\ ", r"\s+")
        # word boundaries that also work for Devanagari / symbols
        pat = re.compile(rf"(?<![\w]){esc}(?![\w])", re.I)
        _RE_CACHE[phrase] = pat
    return pat


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+", text.strip()) if s.strip()]


def truncate_title(title: str, limit: int = 20) -> str:
    """WhatsApp button titles are <= 20 chars."""
    title = title.strip()
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


YES_WORDS = (
    "yes",
    "yeah",
    "yep",
    "yup",
    "ok",
    "okay",
    "okk",
    "sure",
    "done",
    "confirmed",
    "confirm",
    "haan",
    "han",
    "haa",
    "ha",
    "haanji",
    "haan ji",
    "ji haan",
    "ji",
    "theek hai",
    "thik hai",
    "theek",
    "thik",
    "bilkul",
    "pakka",
    "ho gaya",
    "hogaya",
    "kar diya",
    "kar dete hain",
    "chalega",
    "go ahead",
    "go",
    "book it",
    "booked",
    "fine",
    "correct",
    "sahi hai",
    "right",
    "absolutely",
    "of course",
    "हाँ",
    "हां",
    "जी",
    "ठीक है",
    "ho",
    "hoy",
    "sari",
    "aamaa",
)
NO_WORDS = (
    "no",
    "nope",
    "nah",
    "not",
    "nahi",
    "nahin",
    "na",
    "mat",
    "rehne do",
    "rehne de",
    "cancel",
    "don't",
    "dont",
    "never",
    "neither",
    "none",
    "koi nahi",
    "नहीं",
    "nako",
    "illa",
    "sorry",
    "can't",
    "cannot",
    "unable",
)


def is_yes(text: str) -> bool:
    t = norm(text)
    if not t:
        return False
    if is_no(t):
        return False
    return has_any(t, YES_WORDS)


def is_no(text: str) -> bool:
    t = norm(text)
    return has_any(
        t,
        (
            "no",
            "nope",
            "nah",
            "nahi",
            "nahin",
            "na",
            "नहीं",
            "nako",
            "illa",
            "neither",
            "none",
            "koi nahi",
            "rehne do",
            "mat karo",
            "not now",
            "don't",
            "dont",
            "cannot",
            "can't",
            "full hai",
            "not available",
        ),
    )


# --------------------------------------------------------------------------- phones

_PHONE_CANDIDATE = re.compile(r"(?<![\w₹])(\+?\d[\d\s\-().]{6,18}\d)(?![\w])")


def extract_phones(text: str, default_cc: str = "+91") -> list[str]:
    """Phone-number-looking runs (10+ digits, or 1800 toll-free) -> E.164."""
    out: list[str] = []
    for m in _PHONE_CANDIDATE.finditer(text or ""):
        raw = m.group(1)
        before = text[max(0, m.start() - 4) : m.start()].lower()
        if "₹" in before or "rs" in before:
            continue
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 10 or len(digits) > 13:
            continue
        try:
            phone = normalize_phone(raw, default_cc)
        except ValueError:
            continue
        if phone not in out:
            out.append(phone)
    return out


# --------------------------------------------------------------------------- money

_MONEY = re.compile(
    r"(?:(?P<pre>₹|rs\.?|inr|rupees?)\s*(?P<a>\d[\d,]*(?:\.\d+)?)\s*(?P<ka>k)?)"
    r"|(?:(?P<b>\d[\d,]*(?:\.\d+)?)\s*(?P<kb>k\b)?\s*(?P<post>₹|rs\b\.?|rupees?|rupaye|rupay|/-|inr)?)",
    re.I,
)


def _to_int(num: str, k: bool) -> int | None:
    try:
        value = float(num.replace(",", ""))
    except ValueError:
        return None
    if k:
        value *= 1000
    return int(round(value))


def _looks_money(text: str, m: re.Match[str]) -> bool:
    digits = re.sub(r"\D", "", m.group(1))
    before = text[max(0, m.start() - 4) : m.start()].lower()
    return len(digits) < 10 or "₹" in before or "rs" in before


def extract_amounts(text: str, *, require_marker: bool = False) -> list[int]:
    """Rupee amounts in order of appearance. Without a currency marker, bare numbers
    count only if they look like prices (>= 50, not a time / phone / quantity)."""
    out: list[int] = []
    t = _PHONE_CANDIDATE.sub(
        lambda m: m.group(0) if _looks_money(text, m) else " " * len(m.group(0)), text or ""
    )
    for m in _MONEY.finditer(t):
        if m.group("a"):
            v = _to_int(m.group("a"), bool(m.group("ka")))
            if v is not None:
                out.append(v)
            continue
        num = m.group("b")
        if not num:
            continue
        has_marker = bool(m.group("post")) or bool(m.group("kb"))
        tail = t[m.end() : m.end() + 12].lower()
        head = t[max(0, m.start() - 12) : m.start()].lower()
        if re.match(
            r"\s*(am|pm|baje|o'?clock|:|\.\d|bje|min|minute|hour|ghante|days?|din|"
            r"weeks?|hafte|months?|mahine|years?|saal|strips?|tablets?|pcs|pieces|"
            r"bhk|people|log|adults?|kids?|nights?|raat|km|kg|ltr|litre|%|percent|"
            r"th|st|nd|rd|ton)\b",
            tail,
        ):
            continue
        if re.search(r"(\d[:.]|[+]|\bno\.?|number|#|sr|ticket|id)\s*$", head):
            continue
        digits = re.sub(r"\D", "", num)
        if len(digits) >= 9:  # phone / account number
            continue
        v = _to_int(num, bool(m.group("kb")))
        if v is None:
            continue
        if require_marker and not has_marker:
            continue
        if not has_marker and v < 50:
            continue
        out.append(v)
    return out


_BUDGET_MAX = re.compile(
    r"(?:under|below|upto|up to|within|max(?:imum)?|less than|not more than|budget(?: is| of)?|"
    r"ceiling|<=?|tak ka|andar)\s*(?:of\s*)?(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?",
    re.I,
)
_BUDGET_TAK = re.compile(
    r"(?:₹|rs\.?)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?\s*(?:/\s*night\s*|per night\s*|/-\s*)?"
    r"(?:tak|se kam|ke andar|max|or less)\b",
    re.I,
)
_BUDGET_TARGET = re.compile(
    r"(?:target|ideally|around|approx|lagbhag|preferably)\s*(?:₹|rs\.?)?\s*(\d[\d,]*)\s*(k\b)?",
    re.I,
)


def extract_budget(text: str) -> tuple[int | None, int | None]:
    """(max_inr, target_inr) from 'under ₹800', '1500 tak', '4k/night tak', 'ideally 500'."""
    t = text or ""
    mx: int | None = None
    for rx in (_BUDGET_MAX, _BUDGET_TAK):
        m = rx.search(t)
        if m:
            mx = _to_int(m.group(1), bool(m.group(2)))
            if mx is not None and mx < 50:
                mx = None
            if mx is not None:
                break
    tg: int | None = None
    m = _BUDGET_TARGET.search(t)
    if m:
        tg = _to_int(m.group(1), bool(m.group(2)))
        if tg is not None and tg < 50:
            tg = None
    return mx, tg


def format_inr(amount: int | None) -> str:
    if amount is None:
        return "?"
    s = str(abs(int(amount)))
    # Indian grouping: 1,23,456
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"₹{s}"


# --------------------------------------------------------------------------- dates & times

WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "somvar": 0,
    "somwar": 0,
    "सोमवार": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "mangalvar": 1,
    "mangalwar": 1,
    "मंगलवार": 1,
    "wednesday": 2,
    "wed": 2,
    "budhvar": 2,
    "budhwar": 2,
    "बुधवार": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "guruvar": 3,
    "guruwar": 3,
    "brihaspativar": 3,
    "गुरुवार": 3,
    "friday": 4,
    "fri": 4,
    "shukravar": 4,
    "shukrawar": 4,
    "शुक्रवार": 4,
    "saturday": 5,
    "sat": 5,
    "shanivar": 5,
    "shaniwar": 5,
    "शनिवार": 5,
    "sunday": 6,
    "sun": 6,
    "ravivar": 6,
    "raviwar": 6,
    "itvaar": 6,
    "itwar": 6,
    "रविवार": 6,
}
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))

# (start_min, end_min) for vague parts of the day (IST)
DAYPARTS: dict[str, tuple[int, int]] = {
    "morning": (9 * 60, 12 * 60),
    "subah": (9 * 60, 12 * 60),
    "savere": (9 * 60, 12 * 60),
    "सुबह": (9 * 60, 12 * 60),
    "afternoon": (12 * 60, 16 * 60),
    "dopahar": (12 * 60, 16 * 60),
    "dopehar": (12 * 60, 16 * 60),
    "evening": (17 * 60, 20 * 60),
    "shaam": (17 * 60, 20 * 60),
    "sham": (17 * 60, 20 * 60),
    "शाम": (17 * 60, 20 * 60),
    "night": (20 * 60, 22 * 60),
    "raat": (20 * 60, 22 * 60),
    "tonight": (19 * 60, 22 * 60),
}
_PM_PARTS = {
    "afternoon",
    "dopahar",
    "dopehar",
    "evening",
    "shaam",
    "sham",
    "शाम",
    "night",
    "raat",
    "tonight",
}


@dataclass
class When:
    """Result of parsing a user's time words."""

    dates: list[date] = field(default_factory=list)  # IST calendar dates mentioned
    start_min: int | None = None  # IST minutes after midnight
    end_min: int | None = None
    exact: bool = False  # a single precise time ("6pm"), not a range
    text: str = ""  # matched human text, e.g. "Sat 11 Oct, 10:00–12:00"

    @property
    def found(self) -> bool:
        return bool(self.dates) or self.start_min is not None

    def window(
        self, default_start: int = 9 * 60, default_end: int = 21 * 60
    ) -> tuple[datetime | None, datetime | None]:
        if not self.dates:
            return None, None
        s = self.start_min if self.start_min is not None else default_start
        e = self.end_min if self.end_min is not None else default_end
        if self.exact and self.start_min is not None:
            e = self.start_min + 60
        first, last = min(self.dates), max(self.dates)
        return at_ist(first, *divmod(s, 60)), at_ist(last, *divmod(min(e, 23 * 60 + 59), 60))

    def describe(self) -> str:
        parts: list[str] = []
        if self.dates:
            parts.append(
                "/".join(
                    f"{WEEKDAY_NAMES[d.weekday()]} {d.day} {d:%b}" for d in sorted(self.dates)[:3]
                )
            )
        if self.start_min is not None:
            if self.exact or self.end_min is None:
                parts.append(fmt_minutes(self.start_min))
            else:
                parts.append(f"{fmt_minutes(self.start_min)}–{fmt_minutes(self.end_min)}")
        return ", ".join(parts)


def fmt_minutes(m: int) -> str:
    h, mm = divmod(int(m), 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {suffix}" if mm else f"{h12} {suffix}"


def _ampm(hour: int, ampm: str | None, part: str | None) -> int:
    ampm = (ampm or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    if ampm:
        return hour
    if part in _PM_PARTS and hour < 12:
        return hour + 12
    if part and part not in _PM_PARTS:
        return hour
    # bare hour: business-hours guess
    if 1 <= hour <= 7:
        return hour + 12
    return hour


_TIME = re.compile(
    r"(?<![\d:₹])(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?:\s*(?:baje|bje|o'?clock))?"
    r"(?![\d,])",
    re.I,
)
_RANGE = re.compile(
    r"(?:between\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(?:-|–|to|and|se|aur)\s*"
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?(?:\s*(?:baje|bje))?(?:\s*(?:ke\s+)?(?:beech|tak))?",
    re.I,
)


def parse_time_of_day(text: str) -> tuple[int | None, int | None, bool]:
    """(start_min, end_min, exact) from '5-7pm', 'subah 11 ke aaspaas', '6 baje', 'after 6pm'."""
    t = re.sub(r"(/|per|a|ek|each)\s*night", " ", norm(text))
    part = next((p for p in DAYPARTS if _word_re(p).search(t)), None)
    m = _RANGE.search(t)
    if m and (m.group(3) or m.group(6) or part or re.search(r"between|beech|baje|bje", t)):
        h1, h2 = int(m.group(1)), int(m.group(4))
        if h1 <= 12 and h2 <= 12 and h1 != h2:
            ap2 = m.group(6) or m.group(3)
            ap1 = m.group(3) or (m.group(6) if h1 < h2 else None)
            end = _ampm(h2, ap2, part) * 60 + int(m.group(5) or 0)
            start = _ampm(h1, ap1, part) * 60 + int(m.group(2) or 0)
            if start > end and not m.group(3):
                start -= 12 * 60 if start >= 12 * 60 else 0
            if start < end:
                return start, end, False
    for tm in _TIME.finditer(t):
        hour = int(tm.group(1))
        minute = int(tm.group(2) or 0)
        ampm = tm.group(3)
        tail = t[tm.end() : tm.end() + 14]
        head = t[max(0, tm.start() - 10) : tm.start()]
        explicit = (
            bool(ampm)
            or bool(re.match(r"\s*(baje|bje|o'?clock)", tail))
            or bool(tm.group(2))
            or bool(part)
            or bool(re.search(r"(at|@|around|by|after|before|ke baad)\s*$", head))
        )
        if not explicit or hour > 23 or minute > 59:
            continue
        if re.match(r"\s*(?:st|nd|rd|th)?\s*(?:" + _MONTH_RX + r")\b", tail):
            continue  # "12 march" is a date
        if re.match(r"\s*(min|minute|hour|ghante|din|days?|weeks?|%|people|log|k\b|rs|₹)", tail):
            continue
        h24 = _ampm(hour, ampm, part) if hour <= 12 else hour
        start = h24 * 60 + minute
        if re.search(r"after|ke baad|baad", t[tm.end() : tm.end() + 12]) or re.search(
            r"after\s*$", head
        ):
            return start, min(start + 3 * 60, 22 * 60), False
        if re.search(r"before\s*$", head) or re.match(r"\s*(se pehle|ke pehle|before)", tail):
            return max(start - 3 * 60, 8 * 60), start, False
        if re.search(r"aas ?paas|around|approx|ke aaspaas|lagbhag", t):
            return start - 60, start + 60, False
        return start, None, True
    if part:
        s, e = DAYPARTS[part]
        return s, e, False
    return None, None, False


def _next_weekday(today: date, wd: int, *, next_week: bool = False) -> date:
    delta = (wd - today.weekday()) % 7
    if next_week and delta < 7:
        delta += 7 if delta == 0 or next_week else 0
    return today + timedelta(days=delta)


def parse_dates(text: str, now: datetime) -> list[date]:
    """IST calendar dates mentioned: aaj/kal/parso, weekdays, '12 march', '14-16 Nov',
    'next week', ISO dates."""
    t = norm(text)
    today = to_ist(now).date()
    out: list[date] = []

    def add(d: date) -> None:
        if d not in out:
            out.append(d)

    # date ranges "14 se 16 nov", "14-16 nov", "from 14 to 16 november"
    for m in re.finditer(
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|to|se|till|until)\s*(\d{{1,2}})(?:st|nd|rd|th)?"
        rf"\s*({_MONTH_RX})\b",
        t,
    ):
        mon = MONTHS[m.group(3)]
        for day in (int(m.group(1)), int(m.group(2))):
            d = _mk_date(today, mon, day)
            if d:
                add(d)
    for m in re.finditer(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?({_MONTH_RX})\b", t):
        d = _mk_date(today, MONTHS[m.group(2)], int(m.group(1)))
        if d:
            add(d)
    for m in re.finditer(rf"\b({_MONTH_RX})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*(?:am|pm|:))", t):
        d = _mk_date(today, MONTHS[m.group(1)], int(m.group(2)))
        if d:
            add(d)
    for m in re.finditer(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t):
        with contextlib.suppress(ValueError):
            add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if has_any(t, ("day after tomorrow", "parso", "parson", "परसों")):
        add(today + timedelta(days=2))
    elif has_any(t, ("tomorrow", "tmrw", "tmr", "tomorow", "kal", "कल")):
        add(today + timedelta(days=1))
    if has_any(t, ("today", "aaj", "tonight", "abhi", "आज")):
        add(today)
    next_week = has_any(t, ("next week", "agle hafte", "agle week", "next wk"))
    found_wd = False
    for word, wd in WEEKDAYS.items():
        if _word_re(word).search(t):
            found_wd = True
            d = today + timedelta(days=(wd - today.weekday()) % 7)
            if next_week and d < today + timedelta(days=7 - today.weekday()):
                d += timedelta(days=7)
            add(d)
    if has_any(t, ("this weekend", "weekend", "is weekend")) and not found_wd:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        add(sat)
        add(sat + timedelta(days=1))
    if next_week and not found_wd:
        monday = today + timedelta(days=7 - today.weekday())
        for i in range(7):
            add(monday + timedelta(days=i))
    return sorted(out)


def _mk_date(today: date, month: int, day: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today - timedelta(days=1):
            return d
    return None


def parse_when(text: str, now: datetime) -> When:
    start, end, exact = parse_time_of_day(text)
    dates = parse_dates(text, now)
    w = When(dates=dates, start_min=start, end_min=end, exact=exact)
    w.text = w.describe()
    return w


def day_of_month(text: str) -> int | None:
    """'on 5th', '5 tarikh', 'on the 5th of every month' -> 5."""
    m = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th|tarikh|tareekh)\b", norm(text))
    if m and 1 <= int(m.group(1)) <= 31:
        return int(m.group(1))
    return None


def month_only(text: str, now: datetime) -> date | None:
    """'expires in March' -> 1st of the next March (IST)."""
    t = norm(text)
    m = re.search(rf"\b(?:in|by|of|mein|me)?\s*({_MONTH_RX})\b", t)
    if not m:
        return None
    today = to_ist(now).date()
    mon = MONTHS[m.group(1)]
    year = today.year if mon >= today.month else today.year + 1
    return date(year, mon, 1)


def slot_to_datetime(slot: str, ref: datetime) -> datetime | None:
    """Best-effort UTC instant for an offered slot ('Sat 11am', 'today 5pm', '6pm')
    relative to ``ref`` (call time). Bare times are the next occurrence."""
    start, _end, _exact = parse_time_of_day(slot)
    if start is None:
        return None
    dates = parse_dates(slot, ref)
    local = to_ist(ref)
    if dates:
        d = dates[0]
    else:
        d = local.date()
        if start < local.hour * 60 + local.minute:
            d = d + timedelta(days=1)
    return at_ist(d, *divmod(start, 60))


def minutes_of(dt: datetime) -> int:
    local = to_ist(ensure_utc(dt))
    return local.hour * 60 + local.minute
