"""Deterministic NLU for user messages (EN / HI / Hinglish). Produces the same
``InterpretOut`` wire object the real LLM returns, so one converter serves both.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from friday.core.clock import ensure_utc, to_ist
from friday.core.models import (
    AutonomyCategory,
    CallMode,
    CareRequestKind,
    ConversationContext,
    Direction,
    FactKind,
    FanOutStrategy,
    InboundMessage,
    Intent,
    Language,
    MessageKind,
    QuestionPurpose,
    Recurrence,
    TaskStatus,
    TaskType,
    Tone,
)

from ..copy import first_name, say
from ..schemas import (
    AnswerOut,
    AutonomyOut,
    DelegationOut,
    FactOut,
    IdentifierOut,
    InterpretOut,
    PersonOut,
    PlaceOut,
    ProfileUpdatesOut,
    RecurrenceOut,
    StayOut,
    TaskDraft,
    VendorRatingOut,
)
from ..templates import missing_fields, template_for
from ..textutil import (
    MONTHS,
    WEEKDAYS,
    day_of_month,
    extract_amounts,
    extract_budget,
    extract_phones,
    format_inr,
    has_any,
    is_no,
    is_yes,
    month_only,
    norm,
    parse_dates,
    parse_time_of_day,
    parse_when,
)
from .lexicon import (
    CARE_KIND_WORDS,
    CARE_WORDS,
    CATEGORIES,
    COMPANIES,
    DELEGATION_PHRASES,
    SECRET_WORDS,
    SMALL_TALK,
)
from .references import RELATION_WORDS, location_text_of, relation_word_in, resolve

# =============================================================================== helpers


class _Ctx:
    """Convenience view over the context: language, tone, names."""

    def __init__(self, ctx: ConversationContext) -> None:
        self.ctx = ctx
        self.lang = ctx.profile.language
        self.tone = ctx.profile.tone
        self.name = first_name(ctx.profile.name, "")

    def say(self, *, en: str, hinglish: str | None = None, hi: str | None = None) -> str:
        return say(self.lang, self.tone, en=en, hinglish=hinglish, hi=hi)


_ORDINALS = [
    (("first", "pehla", "pehle", "pehli", "1st", "ek", "option 1", "top one"), 0),
    (("second", "dusra", "doosra", "dusri", "2nd", "option 2"), 1),
    (("third", "teesra", "tisra", "3rd", "option 3"), 2),
]
_NONE_WORDS = ("none", "neither", "koi nahi", "none of these", "dono nahi", "kuch nahi",
               "nothing", "don't book", "dont book", "mat karo")


def match_option(text: str, options: list[str]) -> int | None:
    """Map a free-text reply ("6 wala", "second", "later one", "12:30") to an option."""
    t = norm(text)
    if not t or not options:
        return None
    opts = [norm(o) for o in options]
    m = re.fullmatch(r"\[?(\d)\]?\.?", t)
    if m and 1 <= int(m.group(1)) <= len(options):
        return int(m.group(1)) - 1
    for i, o in enumerate(opts):
        if o and (o == t or (len(o) > 2 and o in t)):
            return i
    if has_any(t, _NONE_WORDS):
        for i, o in enumerate(opts):
            if has_any(o, ("none", "neither", "koi nahi", "don't", "dont", "no")):
                return i
        return None
    for words, idx in _ORDINALS:
        if has_any(t, words) and idx < len(options):
            return idx
    if has_any(t, ("last", "later one", "baad wala", "aakhri", "last one", "the later")):
        real = [i for i, o in enumerate(opts) if not has_any(o, ("none", "neither"))]
        return real[-1] if real else None
    if has_any(t, ("earlier one", "pehle wala", "earliest")):
        return 0
    nums = re.findall(r"\d{1,2}(?::\d{2})?", t)
    for n in nums:
        for i, o in enumerate(opts):
            if re.search(rf"(?<![\d:]){re.escape(n)}(?![\d])", o):
                return i
    for i, o in enumerate(opts):
        words = [w for w in re.findall(r"[a-z]{4,}", o) if w not in {"book", "none", "these"}]
        if words and any(w in t for w in words):
            return i
    return None


def _is_none_option(text: str) -> bool:
    return has_any(norm(text), ("none", "neither", "koi nahi", "don't book", "dont book"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")[:40] or "note"


def _title(word: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in word.split())


# =============================================================================== task drafting


def classify_task(t: str) -> TaskType | None:
    has_company = any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t) for k in COMPANIES)
    if has_any(t, ("check in on", "check-in on", "checkin on", "check on", "haal chaal",
                   "hal chal", "wellbeing call", "check-in call", "checkin call")) or (
        re.search(r"call (my )?(mom|dad|mummy|papa|maa|parents|mom and dad|nani|dadi)"
                  r"( and \w+)? (every|daily|har)", t)
    ):
        return TaskType.WELLBEING_CHECKIN
    if has_company and has_any(t, CARE_WORDS):
        return TaskType.CUSTOMER_CARE
    if has_any(t, ("customer care", "customer service", "helpline")):
        return TaskType.CUSTOMER_CARE
    if has_any(t, ("hotel", "homestay", "home stay", "guesthouse", "guest house", "resort",
                   "stay in", "room for", "rooms in")):
        return TaskType.HOTEL_BOOKING
    if has_any(t, ("1bhk", "2bhk", "3bhk", "1 bhk", "2 bhk", "3 bhk", "flat on rent",
                   "house on rent", "flat for rent", "rental", "broker", "landlord")):
        return TaskType.RENTAL_HUNT
    if re.search(r"(which|kis|kaun ?se?|any) (chemist|pharmacy|shop|store|medical)", t) or (
        has_any(t, ("in stock", "stock hai", "available hai kahin", "kahin milega", "kis ke paas"))
    ):
        return TaskType.STOCK_HUNT
    if re.search(r"\bcancel\b.*\b(booking|appointment|reservation|table|slot|order)\b", t) or (
        re.search(r"\bcancel (my|the) \w+", t) and not has_any(t, ("cancel the call",
                                                                  "cancel this task",
                                                                  "cancel the task",
                                                                  "cancel it", "cancel that"))
    ):
        return TaskType.CANCEL_BOOKING
    if has_any(t, ("reschedule", "postpone", "prepone", "move my", "shift my", "change my "
                   "appointment", "change my booking")) or re.search(
        r"\b(move|shift)\b.*\bto\b.*(sunday|monday|tuesday|wednesday|thursday|friday|saturday|"
        r"tomorrow|\d)", t
    ):
        return TaskType.RESCHEDULE
    if has_any(t, ("still on", "reconfirm", "re-confirm", "pakka hai na", "confirmed hai na")):
        return TaskType.RECONFIRM
    if has_any(t, ("running late", "minutes late", "min late", "mins late", "late ho",
                   "der ho", "late hoon", "i'm late", "i am late", "be late")):
        return TaskType.RUNNING_LATE
    if re.search(r"\b(plumber|electrician|carpenter|technician|mechanic|ac guy|painter)\b", t) and (
        has_any(t, ("didn't come", "didnt come", "not come", "nahi aaya", "chase", "eta",
                    "on the way", "kab aayega", "where is", "kahan hai", "supposed to come"))
    ):
        return TaskType.SERVICE_COORDINATION
    if has_any(t, ("is my", "where's my", "where is my", "kab tak ready", "status of my",
                   "ready hai", "is it ready", "has the tailor", "repair done")) and has_any(
        t, ("ready", "done", "refund", "repair", "delivery", "finished", "status", "tailor")
    ):
        return TaskType.STATUS_CHASE
    if has_any(t, ("complain", "complaint", "ruined", "damaged", "kharab kar", "spoiled")):
        return TaskType.CUSTOMER_CARE if has_company else TaskType.COMPLAINT
    if has_any(t, ("every week", "every month", "weekly", "monthly", "har hafte", "har mahine",
                   "every tuesday", "every friday", "every monday", "every 4 weeks",
                   "every quarter", "quarterly", "every 2 weeks", "every two weeks")) or re.search(
        r"every \d+ (weeks|months)", t
    ):
        return TaskType.RECURRING_BOOKING
    if has_any(t, ("quote", "quotes", "quotation", "estimate", "packers", "movers")):
        return TaskType.QUOTE
    if has_any(t, ("order", "mangwa", "mangva", "deliver", "delivery", "home delivery",
                   "bhej do", "water can", "water cans", "tiffin")) and not has_any(
        t, ("order id", "order no", "order number", "my order is")
    ):
        return TaskType.ORDER
    finding = has_any(t, ("find", "dhundo", "dhundh", "dhoondh", "search", "suggest",
                          "look for", "recommend", "koi achha", "koi acha", "dekho"))
    if finding:
        return TaskType.DISCOVERY
    if has_any(t, ("doctor", "dentist", "clinic", "physio", "lab test", "blood test",
                   "home collection", "nurse", "attendant", "checkup", "check-up",
                   "cardiologist", "consultation", "dr.")) and has_any(
        t, ("book", "appointment", "slot", "booking", "schedule", "fix", "kar do", "karwa",
            "chahiye", "tomorrow", "kal", "next week")
    ):
        return TaskType.HEALTHCARE
    if has_any(t, ("is open", "open hai", "are they open", "check if", "pata karo",
                   "poocho", "pucho", "ask them", "ask if", "do they have", "kitne ka",
                   "price of", "timings", "fees", "enquire", "enquiry", "inquire", "find out",
                   "check whether", "how much")):
        return TaskType.ENQUIRY
    if has_any(t, ("book", "appointment", "reserve", "reservation", "table for", "slot",
                   "booking", "haircut", "book kar", "fix an appointment", "schedule")):
        return TaskType.BOOKING
    if re.search(r"\b(call|phone|ring)\b", t) and not has_any(t, ("call me",)):
        return TaskType.ENQUIRY
    return None


def detect_category(t: str) -> str | None:
    for cat, words in CATEGORIES:
        if has_any(t, [w.strip() for w in words]):
            return cat
    return None


def detect_company(t: str) -> str | None:
    for key in sorted(COMPANIES, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", t):
            return COMPANIES[key]
    return None


def detect_care_kind(t: str) -> CareRequestKind:
    for kind, words in CARE_KIND_WORDS:
        if has_any(t, words):
            return kind
    return CareRequestKind.COMPLAINT


_CAP_NAME = re.compile(
    r"\b((?:Dr\.?\s+)?[A-Z][\w'&-]*(?:[ \t]+(?:[A-Z][\w'&-]*|&|and|of))*"
    r"(?:[ \t]+(?:salon|clinic|pharmacy|chemist|restaurant|hospital|services?|plumbing|"
    r"homestay|hotel|cafe|medicos|stores?|works|repair|lab|labs|dental|parlour)\b)?)"
)
_NAME_STOP = {
    "I", "Book", "Find", "Call", "Can", "Please", "Order", "Check", "Get", "Is", "My", "The",
    "Hi", "Hello", "Ask", "Tell", "Cancel", "Move", "Make", "Any", "Add", "Save", "Remind",
    "Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Saturday", "Sunday", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Tomorrow", "Today", "You", "Budget", "Dad", "Mom",
    "Papa", "Mummy", "AC", "OK", "Ok", "Yes", "No", "Kal", "Aaj", "Need", "Want", "Also", "And",
    "Plumber", "Electrician", "Doctor", "Office", "Home", "Lantus", "Dolo", "Ideally",
    "Urgent", "Please", "Btw", "Hey", "Mera", "Meri", "Mere", "Kal", "Aaj", "Kya", "Main",
}


def detect_business_name(text: str, ctx: ConversationContext) -> tuple[str | None, str | None]:
    """(business name, business id) from known businesses or capitalised names."""
    t = norm(text)
    for b in ctx.known_businesses:
        words = [w for w in norm(b.name).split() if len(w) > 3 and w not in
                 {"salon", "clinic", "services", "service", "restaurant", "pharmacy", "unisex",
                  "family", "repair", "solutions", "works", "store", "stores"}]
        if words and re.search(rf"(?<!\w){re.escape(words[0])}(?!\w)", t):
            return b.name, b.id
    m = re.search(r"\b(?:dr\.?|doctor)\s+([a-z][a-z]+)", t)
    if m and m.group(1) not in {"ke", "ka", "ki", "for", "near", "appointment", "slot"}:
        return f"Dr. {m.group(1).title()}", None
    src = text or ""
    for m in _CAP_NAME.finditer(src):
        words = m.group(1).split()
        while words and (words[0].rstrip(".,").split("-")[0] in _NAME_STOP
                         or words[0].lower() in MONTHS):
            words = words[1:]
        while words and words[-1].lower() in {"and", "of", "&"}:
            words = words[:-1]
        if not words:
            continue
        name = " ".join(words).strip(" ,.")
        low = name.lower()
        if low in WEEKDAYS or low in MONTHS or len(name) < 3 or low in _BIZ_SUFFIXES:
            continue
        if any(part in ws for ws in RELATION_WORDS.values() for part in low.split("-")):
            continue
        if detect_company(low) and len(words) == 1:
            continue
        before = src[max(0, m.start() - 12): m.start()].lower()
        has_suffix = words[-1].lower() in _BIZ_SUFFIXES
        introduced = bool(re.search(r"\b(at|from|with|to|call|ko|se|phone)\s+$", before))
        if not (has_suffix or introduced or len(words) >= 2):
            continue
        return name, None
    return None, None


_BIZ_SUFFIXES = {"salon", "clinic", "pharmacy", "chemist", "restaurant", "hospital", "service",
                 "services", "plumbing", "homestay", "hotel", "cafe", "medicos", "store",
                 "stores", "works", "repair", "lab", "labs", "dental", "parlour"}


def detect_delegation(text: str, now: datetime, when_dates: list, budget_max: int | None
                      ) -> DelegationOut | None:
    """EXPLICIT delegation only ("you decide", "just book it", "any slot 5-7 under 800").
    A budget alone is never delegation."""
    t = norm(text)
    if not has_any(t, DELEGATION_PHRASES):
        return None
    start, end, exact = parse_time_of_day(text)
    w = parse_when(text, now)
    ws, we = w.window() if w.dates else (None, None)
    scope = ["slot"]
    if budget_max:
        scope.append("price")
    window_text = None
    if start is not None:
        window_text = w.describe()
    conditions = []
    for phrase in ("female doctor", "female stylist", "male stylist", "ground floor",
                   "veg only", "pure veg", "no advance", "with lift", "morning only"):
        if phrase in t:
            conditions.append(phrase)
    return DelegationOut(
        granted=True,
        scope=scope,
        max_price_inr=budget_max,
        window_start=ws.isoformat() if ws else None,
        window_end=we.isoformat() if we else None,
        time_window_text=window_text,
        conditions=conditions,
        user_words=text.strip(),
    )


def detect_recurrence(text: str) -> RecurrenceOut | None:
    t = norm(text)
    start, _end, _exact = parse_time_of_day(text)
    time_ist = f"{start // 60:02d}:{start % 60:02d}" if start is not None else "10:00"
    m = re.search(r"every (\d+|two|three|four) (week|weeks|month|months|day|days)", t)
    words_num = {"two": 2, "three": 3, "four": 4}
    if m:
        n = int(words_num.get(m.group(1), m.group(1)))
        unit = m.group(2)
        if unit.startswith("day"):
            return RecurrenceOut(freq=Recurrence.WEEKLY, interval_days=n, time_ist=time_ist)
        return RecurrenceOut(freq=Recurrence.WEEKLY if unit.startswith("week")
                             else Recurrence.MONTHLY, interval=n, time_ist=time_ist)
    if has_any(t, ("every day", "daily", "every morning", "every evening", "roz", "har din",
                   "rozana", "everyday")):
        return RecurrenceOut(freq=Recurrence.WEEKLY, interval_days=1, time_ist=time_ist)
    if has_any(t, ("quarterly", "every quarter", "har 3 mahine")):
        return RecurrenceOut(freq=Recurrence.MONTHLY, interval=3, time_ist=time_ist)
    if has_any(t, ("monthly", "every month", "har mahine")):
        return RecurrenceOut(freq=Recurrence.MONTHLY, day_of_month=day_of_month(text),
                             time_ist=time_ist)
    weekdays = sorted({wd for w, wd in WEEKDAYS.items()
                       if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t)})
    if has_any(t, ("weekly", "every week", "har hafte")) or (
        weekdays and has_any(t, ("every", "har"))
    ):
        return RecurrenceOut(freq=Recurrence.WEEKLY, weekdays=weekdays, time_ist=time_ist)
    return None


def detect_stay(text: str, now: datetime, budget_max: int | None) -> StayOut | None:
    t = norm(text)
    dates = parse_dates(text, now)
    dest = None
    m = re.search(r"\b(?:in|at|to)\s+([a-z][a-z ]{2,25}?)(?=\s*(?:,|\.|$| for | from | on |"
                  r" \d| se | under | near ))", t)
    if m:
        dest = m.group(1).strip()
    if not dest:
        m = re.search(r"([a-z][a-z]{2,20})\s+(?:mein|me)\b", t)
        if m and m.group(1) not in {"ghar", "budget", "room"}:
            dest = m.group(1)
    if not dest:
        return None
    dest = _title(dest)
    if len(dates) >= 2:
        check_in, check_out = dates[0], dates[-1]
    elif len(dates) == 1:
        check_in, check_out = dates[0], dates[0] + timedelta(days=1)
    else:
        return StayOut(destination=dest, check_in="", check_out="",
                       max_rate_per_night_inr=budget_max)
    adults = 2
    m = re.search(r"(\d+)\s*(?:adults?|people|log|persons?|guests?)", t)
    if m:
        adults = int(m.group(1))
    prefs = [p for p in ("breakfast", "ground floor", "lift", "veg", "lake view", "early check-in",
                         "parking", "pool") if p in t]
    if has_any(t, ("stairs nahi", "can't climb", "cannot climb", "no stairs")):
        prefs.append("ground floor or lift")
    types = [p for p in ("hotel", "homestay", "guesthouse", "resort") if p in t.replace(" ", "")]
    return StayOut(destination=dest, check_in=check_in.isoformat(),
                   check_out=check_out.isoformat(), adults=adults,
                   max_rate_per_night_inr=budget_max, property_types=types, preferences=prefs)


_ITEM = re.compile(
    r"(?:order|mangwa\w*|has|have|stock of|available|need|chahiye|for|of)\s+"
    r"((?:[a-z0-9]+[\s-]?){1,5}?)"
    r"(?=\s*(?:from|to|near|ke paas|for|and|aur|\?|,|\.|$| hai| in stock| available| x ?\d))",
    re.I,
)


def detect_item(text: str, task_type: TaskType) -> str | None:
    t = norm(text)
    m = re.search(r"([a-z][\w ]{2,30}?\s*\d{2,4})\s*(?:x|×)\s*(\d+)", t)  # "dolo 650 x2"
    if m:
        return f"{m.group(1).title()} x {m.group(2)}"
    if task_type == TaskType.STOCK_HUNT:
        m = re.search(r"(?:kis|which|kaun ?se?)\s+\w+\s+(?:ke paas|mein|me|has|have)\s+(.+?)"
                      r"(?:\s+(?:hai|milega|in stock|available)|\?|$)", t)
        if not m:
            m = re.search(r"(?:has|have|stock of)\s+(.+?)(?:\s+(?:hai|in stock|available)|\?|$)",
                          t)
        if m:
            item = re.sub(r"^(a|an|the)\s+", "", m.group(1)).strip(" ?.")
            item = re.sub(r"\s*(hai|urgent).*$", "", item)
            return item.title() if item else None
    m = re.search(r"(\d+)\s+(water cans?|cans?|strips?|packets?|tiffins?|bottles?|kg [a-z]+)", t)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    for match in _ITEM.finditer(t):
        item = match.group(1).strip()
        if item and item not in {"me", "my", "papa", "mom", "dad", "it", "a", "the", "him", "her"}:
            if not re.fullmatch(r"\d+", item):
                return item
    return None


def detect_questions(text: str, task_type: TaskType, item: str | None) -> list[str]:
    t = norm(text)
    qs: list[str] = []
    if item and has_any(t, ("has", "have", "stock", "available", "milega", "hai kya")):
        qs.append(f"Do you have {item} in stock?")
    if has_any(t, ("open", "timing", "timings", "until when", "till when", "kab tak khula",
                   "band", "closing time")):
        qs.append("What are your timings today - until when are you open?")
    if has_any(t, ("price", "kitne ka", "how much", "cost", "rate", "charges", "kitna")):
        qs.append(f"What is the price{(' of ' + item) if item else ''}?")
    if has_any(t, ("fee", "fees")):
        qs.append("What is the fee structure?")
    if has_any(t, ("home delivery", "deliver")):
        qs.append("Do you do home delivery, and what is the charge?")
    if has_any(t, ("trial", "demo class")):
        qs.append("Is there a trial class?")
    for q in re.findall(r"(?:ask|poocho|pucho)\s+(?:them\s+|if\s+|ki\s+)?([^.?!]{6,80}\?)", text,
                        re.I):
        if q not in qs:
            qs.append(q.strip())
    return qs[:5]


def detect_reference(text: str) -> str | None:
    m = re.search(r"(?:booking|order|ticket|complaint|receipt|ref(?:erence)?|sr|job)"
                  r"\s*(?:id|no\.?|number|#)?\s*(?:is|:)?\s*([A-Z0-9][A-Z0-9-]{3,})", text or "",
                  re.I)
    return m.group(1) if m and re.search(r"\d", m.group(1)) else None


def detect_service(t: str, category: str | None, item: str | None, party: int | None) -> str:
    for word, label in (("haircut", "a haircut"), ("hair cut", "a haircut"),
                        ("beard", "a beard trim"), ("facial", "a facial"),
                        ("teeth cleaning", "a teeth cleaning"), ("cleaning", "a cleaning"),
                        ("consultation", "a consultation"), ("checkup", "a check-up"),
                        ("check-up", "a check-up"), ("thyroid", "a thyroid test home collection"),
                        ("blood test", "a blood test"), ("home collection", "a lab home collection"),
                        ("gas refill", "an AC gas refill"), ("ac service", "an AC service"),
                        ("ac not cooling", "an AC repair visit"),
                        ("isn't cooling", "an AC repair visit"), ("physio", "a physio session"),
                        ("tap", "a tap repair"), ("leak", "a leak repair")):
        if word in t:
            return label
    if party or "table" in t:
        return f"a table for {party}" if party else "a table"
    if item:
        return item
    if category:
        return f"a {category} appointment" if category in {"clinic", "dentist", "salon"} \
            else category
    return "the request"


def _resolve_window(when, now: datetime) -> tuple[str | None, str | None]:
    if not when.dates:
        return None, None
    ws, we = when.window()
    if ws and ws < ensure_utc(now):
        ws = ensure_utc(now)
    return (ws.isoformat() if ws else None), (we.isoformat() if we else None)


def draft_task(c: _Ctx, text: str, msg: InboundMessage | None = None) -> TaskDraft | None:
    ctx = c.ctx
    t = norm(text)
    ttype = classify_task(t)
    if ttype is None:
        return None
    now = ctx.now
    when = parse_when(text, now)
    phones = extract_phones(text)
    if msg is not None and msg.contact_phone:
        phones.append(msg.contact_phone)
    bmax, btarget = extract_budget(text)
    category = detect_category(t)
    company = detect_company(t)
    biz_name, _biz_id = detect_business_name(text, ctx)
    if company and ttype == TaskType.CUSTOMER_CARE:
        biz_name = None
    if biz_name and company and norm(biz_name) == norm(company):
        biz_name = None
    item = detect_item(text, ttype)
    party = None
    m = re.search(r"(?:table for|for)\s+(\d{1,2})\s*(?:people|log|persons|pax|of us)?", t)
    if m and ("table" in t or "people" in t or "log" in t):
        party = int(m.group(1))
    reference = detect_reference(text)
    rel = relation_word_in(t)
    beneficiary_ref = rel[1] if rel else None
    if beneficiary_ref is None:
        for p in ctx.people:
            first = norm(p.name).split()[0] if p.name else ""
            if first and re.search(rf"(?<!\w){re.escape(first)}(?!\w)", t):
                beneficiary_ref = p.name.split()[0]
                break
    place_ref = None
    pm = re.search(r"((?:near|around|close to)\s+(?:my|our|his|her|their)?\s*[\w' &]+?"
                   r"(?:home|office|place|house|ghar)|[\w']+\s+ke\s+ghar\s+ke\s+paas|"
                   r"ghar\s+ke\s+paas|near my \w+|near home|near office)", t)
    if pm:
        place_ref = pm.group(1)
    location = location_text_of(text) if not place_ref else None

    delegation = detect_delegation(text, now, when.dates, bmax)
    recurrence = detect_recurrence(text) if ttype in (
        TaskType.RECURRING_BOOKING, TaskType.WELLBEING_CHECKIN) else None
    stay = detect_stay(text, now, bmax) if ttype == TaskType.HOTEL_BOOKING else None
    questions = detect_questions(text, ttype, item) if ttype in (
        TaskType.ENQUIRY, TaskType.STOCK_HUNT, TaskType.RENTAL_HUNT) else []

    call_mode = CallMode.AGENT
    if has_any(t, ("patch me in", "connect me", "three-way", "three way", "conference me",
                   "transfer to me", "mujhe jod do", "mujhe connect")):
        call_mode = CallMode.WARM_TRANSFER
    if has_any(t, ("translate", "translator", "interpret for me")):
        call_mode = CallMode.TRANSLATOR
    fan_out = None
    if has_any(t, ("all at once", "sabko ek saath", "simultaneously", "in parallel")):
        fan_out = FanOutStrategy.PARALLEL
    elif has_any(t, ("one by one", "ek ek karke", "one after another")):
        fan_out = FanOutStrategy.SEQUENTIAL

    # discovery when no business named / no number
    discovery_query = None
    if ttype in (TaskType.DISCOVERY, TaskType.STOCK_HUNT, TaskType.RENTAL_HUNT,
                 TaskType.QUOTE) or (not phones and not biz_name and ttype in (
            TaskType.BOOKING, TaskType.HEALTHCARE, TaskType.ORDER, TaskType.ENQUIRY,
            TaskType.SERVICE_COORDINATION)):
        if not biz_name and not phones:
            discovery_query = category or (item if ttype == TaskType.STOCK_HUNT else None)
            if ttype == TaskType.STOCK_HUNT:
                discovery_query = "pharmacy" if category in (None, "pharmacy") else category
    if ttype == TaskType.DISCOVERY and not discovery_query:
        discovery_query = category or item

    care_request = detect_care_kind(t) if ttype == TaskType.CUSTOMER_CARE else None
    service = detect_service(t, category, item, party)
    who = None
    res = resolve(ctx, text) if beneficiary_ref else None
    if res and res.person_id:
        p = next((p for p in ctx.people if p.id == res.person_id), None)
        who = p.name if p else None
    who = who or (beneficiary_ref.title() if beneficiary_ref else (ctx.profile.name or "me"))
    target = biz_name or company or (f"a {discovery_query}" if discovery_query else "the business")
    goal = _goal(ttype, service=service, who=who, when=when.text, target=target, item=item,
                 company=company, care=care_request, text=text, reference=reference)

    if ttype in (TaskType.CUSTOMER_CARE, TaskType.COMPLAINT, TaskType.STATUS_CHASE):
        when = parse_when("", now)  # dates there describe the problem, not a booking
    ws, we = _resolve_window(when, now)
    preferred = [when.text] if when.text else []
    draft = TaskDraft(
        type=ttype,
        goal=goal,
        business_name=biz_name,
        business_phone=phones[0] if phones else None,
        category=category,
        item=item,
        reference=reference,
        company=company,
        care_request=care_request,
        discovery_query=discovery_query,
        location_text=location,
        when_text=when.text or None,
        window_start=ws,
        window_end=we,
        preferred_times=preferred,
        party_size=party,
        budget_max_inr=bmax,
        budget_target_inr=btarget,
        questions=questions,
        constraints=_constraints(t),
        delegation=delegation,
        recurrence=recurrence,
        stay=stay,
        beneficiary_ref=beneficiary_ref,
        place_ref=place_ref,
        call_mode=call_mode,
        fan_out=fan_out,
        notes=None,
    )
    draft.missing = draft_missing(draft)
    return draft


def draft_missing(d: TaskDraft) -> list[str]:
    values: dict[str, object] = {
        "business_phone": d.business_phone, "business_name": d.business_name,
        "discovery_query": d.discovery_query, "when_text": d.when_text,
        "preferred_times": d.preferred_times, "window_start": d.window_start, "item": d.item,
        "company": d.company, "recurrence": d.recurrence, "notes": d.notes, "goal": d.goal,
        "stay": d.stay if (d.stay and d.stay.check_in) else None,
    }
    missing = missing_fields(template_for(d.type), values)
    if d.type == TaskType.WELLBEING_CHECKIN and not d.beneficiary_ref:
        missing.append("beneficiary")
    return missing


def _constraints(t: str) -> list[str]:
    out = []
    for phrase in ("female doctor", "female stylist", "male stylist", "ground floor",
                   "pure veg", "veg only", "home visit", "no advance", "wheelchair",
                   "senior citizen", "pet friendly", "bachelors"):
        if phrase in t:
            out.append(phrase)
    return out


def _goal(ttype: TaskType, *, service: str, who: str, when: str, target: str,
          item: str | None, company: str | None, care: CareRequestKind | None, text: str,
          reference: str | None) -> str:
    when_part = f", {when}" if when else ""
    who_part = f" for {who}"
    if ttype in (TaskType.BOOKING, TaskType.HEALTHCARE, TaskType.RECURRING_BOOKING):
        return f"Book {service}{who_part} at {target}{when_part}"
    if ttype == TaskType.ORDER:
        return f"Order {item or service} from {target} for delivery{who_part}"
    if ttype == TaskType.STOCK_HUNT:
        return f"Find a shop that has {item or 'the item'} in stock{when_part}"
    if ttype == TaskType.ENQUIRY:
        return f"Ask {target} about {item or service}"
    if ttype == TaskType.RESCHEDULE:
        return f"Reschedule{who_part.replace(' for', '')}'s booking at {target} to {when or 'a new time'}"
    if ttype == TaskType.CANCEL_BOOKING:
        return f"Cancel the booking at {target}{when_part}"
    if ttype == TaskType.RECONFIRM:
        return f"Reconfirm the booking at {target}{when_part}"
    if ttype == TaskType.RUNNING_LATE:
        m = re.search(r"(\d+)\s*(?:min|minutes|mins)", text.lower())
        late = f" by about {m.group(1)} minutes" if m else ""
        return f"Tell {target} that {who} is running late{late}"
    if ttype == TaskType.SERVICE_COORDINATION:
        return f"Get an ETA from {target} and make sure they come{when_part}"
    if ttype == TaskType.STATUS_CHASE:
        ref = f" (ref {reference})" if reference else ""
        return f"Get the status of {item or 'the job'}{ref} from {target}"
    if ttype == TaskType.COMPLAINT:
        return f"Complain to {target} and get a remedy: {text.strip()[:120]}"
    if ttype == TaskType.RENTAL_HUNT:
        return f"Find rentals: {text.strip()[:120]}"
    if ttype == TaskType.QUOTE:
        return f"Get quotes for {service}{when_part}"
    if ttype == TaskType.WELLBEING_CHECKIN:
        return f"Wellbeing check-in call with {who}"
    if ttype == TaskType.CUSTOMER_CARE:
        kind = (care or CareRequestKind.COMPLAINT).value.replace("_", " ")
        return f"{kind.capitalize()} with {company or target}: {text.strip()[:140]}"
    if ttype == TaskType.HOTEL_BOOKING:
        return f"Find and hold a stay{who_part}{when_part}"
    if ttype == TaskType.DISCOVERY:
        return f"Find a good {target.removeprefix('a ')} and get quotes{when_part}"
    return text.strip()[:140]


# =============================================================================== facts

_FACT_DUE = re.compile(
    r"(?:my\s+)?(?P<thing>rent|emi|maintenance|electricity bill|phone bill|credit card bill|"
    r"card bill|bill|salary|sip|school fees?|fees|loan)\s+(?:is\s+)?(?:due|aata hai|deni hai|"
    r"jaata hai|bharna hai|dena hai|on)",
    re.I,
)
_FACT_EXPIRY = re.compile(
    r"(?P<thing>(?:car |bike |health |term |two wheeler )?insurance|passport|licen[cs]e|"
    r"driving licen[cs]e|puc|pollution|subscription|warranty|policy|membership)\s+.*?"
    r"(?:expire|expires|expiry|renew|khatam|due)",
    re.I,
)
_FACT_BDAY = re.compile(r"(?P<who>[\w' ]+?)(?:'s|\s+ka|\s+ki)?\s+(?P<thing>birthday|bday|"
                        r"anniversary|janamdin)", re.I)
_FACT_PREF = re.compile(r"\b(?:i am|i'm|im|main)\s+(?P<pref>vegetarian|vegan|jain|"
                        r"allergic to [\w ]+|diabetic|lactose intolerant)", re.I)
_FACT_USUAL = re.compile(r"my (?:usual|regular|favourite|favorite) (?P<cat>\w+) is (?P<val>.+)",
                         re.I)
_FACT_REMEMBER = re.compile(r"^(?:please\s+)?(?:remember|note|yaad rakhna|yaad rakho|note kar lo|"
                            r"note karo)(?:\s+that)?[:,]?\s+(?P<val>.+)$", re.I)


def extract_facts(text: str, now: datetime, ctx: ConversationContext) -> list[FactOut]:
    facts: list[FactOut] = []
    t = norm(text)
    today = to_ist(now).date()
    m = _FACT_DUE.search(t)
    if m:
        thing = m.group("thing").lower()
        dom = day_of_month(text)
        due = None
        if dom:
            month, year = today.month, today.year
            if dom < today.day:
                month += 1
                if month > 12:
                    month, year = 1, year + 1
            try:
                due = today.replace(year=year, month=month, day=dom)
            except ValueError:
                due = None
        value = f"{thing} due on the {dom}{_ord(dom)} of every month" if dom else f"{thing} due"
        facts.append(FactOut(kind=FactKind.DATE, key=f"{_slug(thing)}_due", value=value,
                             due_on=due.isoformat() if due else None,
                             recurrence=Recurrence.MONTHLY, confidence=0.95 if dom else 0.6))
    m = _FACT_EXPIRY.search(t)
    if m:
        thing = m.group("thing").lower().strip()
        dates = parse_dates(text, now)
        due = dates[0] if dates else month_only(text, now)
        exact = bool(dates)
        rec = Recurrence.YEARLY if "insurance" in thing or "puc" in thing else Recurrence.NONE
        facts.append(FactOut(
            kind=FactKind.DATE, key=f"{_slug(thing)}_expiry",
            value=f"{thing} expires {due.strftime('%d %b %Y') if exact and due else (due.strftime('%B %Y') if due else '')}".strip(),
            due_on=due.isoformat() if due else None, recurrence=rec,
            confidence=0.95 if exact else 0.7))
    m = _FACT_BDAY.search(t)
    if m:
        dates = parse_dates(text, now)
        if dates:
            who = m.group("who").strip().split()[-1] if m.group("who") else "my"
            person_ref = None if who in {"my", "mera", "meri"} else who
            facts.append(FactOut(kind=FactKind.DATE, key=f"{_slug(who)}_{m.group('thing')}",
                                 value=f"{who}'s {m.group('thing')} on {dates[0]:%d %b}",
                                 due_on=dates[0].isoformat(), recurrence=Recurrence.YEARLY,
                                 about_person_ref=person_ref))
    m = _FACT_PREF.search(t)
    if m:
        facts.append(FactOut(kind=FactKind.PREFERENCE, key="diet" if m.group("pref") in
                             ("vegetarian", "vegan", "jain") else _slug(m.group("pref")),
                             value=m.group("pref")))
    m = _FACT_USUAL.search(text or "")
    if m:
        facts.append(FactOut(kind=FactKind.PREFERENCE, key=f"usual_{_slug(m.group('cat'))}",
                             value=m.group("val").strip(" .")))
    if not facts:
        m = _FACT_REMEMBER.search((text or "").strip())
        if m:
            val = m.group("val").strip(" .")
            dates = parse_dates(val, now)
            facts.append(FactOut(kind=FactKind.DATE if dates else FactKind.GENERAL,
                                 key=_slug(val)[:30], value=val,
                                 due_on=dates[0].isoformat() if dates else None))
    for f in facts:
        if f.about_person_ref is None:
            rel = relation_word_in(t)
            if rel and f.kind == FactKind.DATE and "my" not in t.split()[:1]:
                f.about_person_ref = rel[1]
    return facts


def _ord(n: int | None) -> str:
    if not n:
        return ""
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# =============================================================================== intents


def _open(ctx: ConversationContext, *statuses: TaskStatus):
    return [t for t in ctx.open_tasks if t.status in statuses]


def _newest(tasks):
    return sorted(tasks, key=lambda t: t.updated_at, reverse=True)[0] if tasks else None


def _button(c: _Ctx, msg: InboundMessage) -> InterpretOut | None:
    bid = msg.button_id or ""
    parts = bid.split(":", 2)
    if len(parts) != 3:
        return None
    kind, ref, val = parts
    ctx = c.ctx
    if kind == "q":
        q = ctx.pending_question
        idx = int(val) if val.isdigit() else None
        text = msg.text or ""
        approves = False
        if q is not None and idx is not None and idx < len(q.options):
            text = q.options[idx]
            approves = q.purpose == QuestionPurpose.APPROVE_BOOKING and not _is_none_option(text)
        return InterpretOut(intent=Intent.ANSWER_QUESTION, task_id=q.task_id if q else None,
                            answer=AnswerOut(text=text, option_index=idx, approves=approves))
    if kind == "a":
        yes = val.lower() in ("yes", "y", "1", "true")
        reply = c.say(en="Great, confirming it now.", hinglish="Done, abhi confirm karti hoon.",
                      hi="ठीक है, अभी कन्फ़र्म करती हूँ।") if yes else c.say(
            en="Okay, I won't book it.", hinglish="Theek hai, book nahi karungi.",
            hi="ठीक है, बुक नहीं करूँगी।")
        return InterpretOut(intent=Intent.APPROVE if yes else Intent.REJECT, task_id=ref,
                            reply=reply)
    if kind == "c":
        idx = int(val) if val.isdigit() else None
        if idx is None:  # "c:<task>:none"
            return InterpretOut(intent=Intent.REJECT, task_id=ref,
                                reply=c.say(en="Okay, none of these.",
                                            hinglish="Theek hai, inme se koi nahi."))
        return InterpretOut(intent=Intent.CHOOSE, task_id=ref, choice_index=idx,
                            reply=c.say(en="On it, calling them to confirm.",
                                        hinglish="Theek hai, confirm karne ke liye call karti hoon."))
    if kind == "n":
        positive = val.lower() in ("yes", "book", "call", "order", "ok", "done", "acted", "go")
        return InterpretOut(intent=Intent.APPROVE if positive else Intent.REJECT,
                            reply=c.say(en="On it." if positive else "Okay, noted.",
                                        hinglish="Theek hai." if not positive else "On it!"))
    if kind == "r":
        # reference disambiguation tap: re-interpret the original request with it
        target_kind, _, target_id = (ref, None, val)
        for turn in reversed(ctx.recent):
            if turn.direction != Direction.INBOUND or not turn.text:
                continue
            draft = draft_task(c, turn.text)
            if draft is None:
                continue
            out = InterpretOut(intent=Intent.NEW_TASK, task=draft, reply=_task_reply(c, draft))
            out.task.beneficiary_ref = f"#{target_id}" if target_kind == "person" \
                else draft.beneficiary_ref
            if target_kind == "place":
                out.task.place_ref = f"#{target_id}"
            return out
        return InterpretOut(intent=Intent.UNKNOWN, reply=c.say(en="Got it.",
                                                               hinglish="Samajh gayi."))
    return None


def _answer_pending(c: _Ctx, text: str) -> InterpretOut | None:
    q = c.ctx.pending_question
    if q is None:
        return None
    t = norm(text)
    idx = match_option(text, q.options)
    if idx is None and q.options and not (is_yes(t) or is_no(t)) and len(t.split()) > 6:
        return None  # looks like a new instruction, not an answer
    opt_text = q.options[idx] if idx is not None else text.strip()
    approves = False
    if q.purpose == QuestionPurpose.APPROVE_BOOKING:
        approves = (idx is not None and not _is_none_option(opt_text)) or (
            not q.options and is_yes(t))
        if is_no(t) and idx is None:
            approves = False
    return InterpretOut(intent=Intent.ANSWER_QUESTION, task_id=q.task_id,
                        answer=AnswerOut(text=opt_text, option_index=idx, approves=approves))


def _approval(c: _Ctx, text: str) -> InterpretOut | None:
    ctx = c.ctx
    t = norm(text)
    choice = _open(ctx, TaskStatus.AWAITING_CHOICE)
    if choice:
        task = _newest(choice)
        options: list[str] = []
        if task.result and task.result.comparison:
            options = [q.business_name for q in task.result.comparison.ranked_quotes]
        elif task.shortlist:
            options = [s.candidate.name for s in task.shortlist]
        idx = match_option(text, options) if options else None
        if idx is not None and not is_no(t):
            return InterpretOut(intent=Intent.CHOOSE, task_id=task.id, choice_index=idx,
                                reply=c.say(en=f"Calling {options[idx]} to confirm…",
                                            hinglish=f"{options[idx]} ko confirm karne ke liye "
                                                     f"call karti hoon…"))
        if is_no(t):
            return InterpretOut(intent=Intent.REJECT, task_id=task.id,
                                reply=c.say(en="Okay, I won't book any of them.",
                                            hinglish="Theek hai, kisi ko book nahi karungi."))
    awaiting = _open(ctx, TaskStatus.AWAITING_APPROVAL)
    if not awaiting:
        return None
    task = _newest(awaiting)
    q = task.result.needs_approval if task.result else None
    options = q.options if q else []
    idx = match_option(text, options) if options else None
    if idx is not None:
        opt = options[idx]
        if _is_none_option(opt):
            return InterpretOut(intent=Intent.REJECT, task_id=task.id, reply=c.say(
                en="Okay, I won't book it. Want me to ask for something else?",
                hinglish="Theek hai, book nahi karungi. Kuch aur poochun?"))
        return InterpretOut(intent=Intent.APPROVE, task_id=task.id, choice_index=idx,
                            answer=AnswerOut(text=opt, option_index=idx, approves=True)
                            if q else None,
                            reply=c.say(en=f"{opt} it is. Calling back to confirm…",
                                        hinglish=f"{opt} final. Confirm karne ke liye call back "
                                                 f"kar rahi hoon…"))
    if is_yes(t) and len(t.split()) <= 6:
        return InterpretOut(intent=Intent.APPROVE, task_id=task.id,
                            reply=c.say(en="Great, calling back to confirm…",
                                        hinglish="Badhiya, confirm karne ke liye call back kar "
                                                 "rahi hoon…"))
    if is_no(t) and len(t.split()) <= 6:
        return InterpretOut(intent=Intent.REJECT, task_id=task.id,
                            reply=c.say(en="Okay, I won't book it.",
                                        hinglish="Theek hai, book nahi karungi."))
    if has_any(t, ("ask for", "instead", "uske bajaye", "badle", "poocho", "try for")):
        when = parse_when(text, ctx.now)
        return InterpretOut(intent=Intent.TASK_UPDATE, task_id=task.id,
                            answer=AnswerOut(text=text.strip(), approves=False),
                            reply=c.say(en=f"Okay, I'll ask them for {when.text or 'that'}.",
                                        hinglish=f"Theek hai, unse {when.text or 'yeh'} "
                                                 f"poochti hoon."))
    return None


def _settings(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    prof = ProfileUpdatesOut()
    autonomy: list[AutonomyOut] = []
    requires_pin = False
    reply = None
    if has_any(t, ("be formal", "formal raho", "formal tone", "formal please", "more formal",
                   "speak formally")):
        prof.tone, reply = Tone.FORMAL, "Understood. I will keep it formal."
    elif has_any(t, ("be playful", "playful", "be casual", "casual raho", "more fun", "be funny")):
        prof.tone, reply = Tone.PLAYFUL, "Done! Playful mode on 😄"
    elif has_any(t, ("be friendly", "normal tone")):
        prof.tone, reply = Tone.FRIENDLY, "Back to my usual self 🙂"
    lang_map = (("hinglish", Language.HINGLISH), ("hindi", Language.HI),
                ("english", Language.EN))
    if has_any(t, ("talk in", "speak in", "reply in", "mein baat", "me baat", "mein bolo",
                   "language", "please", "mein likho", "only")) or len(t.split()) <= 3:
        for word, lang in lang_map:
            if re.search(rf"\b{word}\b", t) and has_any(t, ("talk", "speak", "reply", "baat",
                                                             "bolo", "language", "please",
                                                             "likho", "only", "mein", "in")):
                prof.language = lang
                reply = {Language.EN: "Sure, English from now on.",
                         Language.HI: "ठीक है, अब से हिंदी में बात करूँगी।",
                         Language.HINGLISH: "Done, ab se Hinglish mein baat karungi."}[lang]
                break
    if has_any(t, ("morning briefing", "daily briefing", "briefing")):
        off = has_any(t, ("stop", "off", "band", "disable", "no more", "don't"))
        prof.morning_briefing = not off
        start, _e, _x = parse_time_of_day(text)
        if start is not None and not off:
            prof.briefing_hour_ist = start // 60
        reply = "Morning briefing off." if off else (
            f"Morning briefing on, every day at {prof.briefing_hour_ist or 8}:00.")
    m = re.search(r"\bcall me ([a-z][a-z ]{1,30})$", t)
    if m and not has_any(t, ("call me back", "call me at", "call me when")):
        prof.name = _title(m.group(1).strip())
        reply = f"Sure, {prof.name} it is."
    if has_any(t, ("stop reminders", "no reminders", "stop nudges", "no more nudges",
                   "stop these", "stop suggestions", "don't remind", "dont remind")):
        cats = [AutonomyCategory.ROUTINES] if has_any(t, ("suggestion", "these")) else [
            AutonomyCategory.ROUTINES, AutonomyCategory.REMINDERS]
        autonomy = [AutonomyOut(category=cat, level=1, enabled=False) for cat in cats]
        reply = "Okay, I'll stop those. Task results will still come."
    if has_any(t, ("pause for", "pause nudges", "pause everything", "pause karo")):
        autonomy = [AutonomyOut(category=cat, level=1, enabled=False) for cat in (
            AutonomyCategory.ROUTINES, AutonomyCategory.BRIEFING, AutonomyCategory.FOLLOW_UPS)]
        reply = ("Paused. No nudges or briefings until you say 'resume'. Results and "
                 "appointment reminders will still come.")
    if has_any(t, ("resume", "unpause")) and len(t.split()) <= 4:
        autonomy = [AutonomyOut(category=cat, level=2, enabled=True) for cat in (
            AutonomyCategory.ROUTINES, AutonomyCategory.BRIEFING, AutonomyCategory.FOLLOW_UPS)]
        reply = "Welcome back, nudges resumed."
    if has_any(t, ("book automatically", "auto book", "auto-book", "act automatically",
                   "don't ask before calling", "dont ask before calling", "no need to ask before")):
        autonomy = [AutonomyOut(category=AutonomyCategory.BOOKINGS, level=4, enabled=True)]
        requires_pin = True
        reply = ("I can place booking calls without asking first (I'll still never confirm or "
                 "pay without your OK). Send your Friday PIN to turn this on.")
    if has_any(t, ("just suggest", "only suggest", "only inform", "just tell me")):
        autonomy = [AutonomyOut(category=AutonomyCategory.ROUTINES, level=2, enabled=True)]
        reply = "Got it, I'll only suggest."
    if reply is None:
        return None
    return InterpretOut(intent=Intent.SETTINGS, reply=c.say(en=reply), profile=prof,
                        autonomy=autonomy, requires_pin=requires_pin)


def _identifier(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    secret = has_any(t, SECRET_WORDS) and bool(re.search(r"\d{3,}", t))
    if secret or (has_any(t, ("save", "remember", "note")) and has_any(
            t, ("otp", "cvv", "password", "pin", "card number"))):
        return InterpretOut(intent=Intent.SAVE_IDENTIFIER, reply=c.say(
            en="I can't save OTPs, PINs, CVVs, passwords or card numbers - and I'll never ask "
               "for them. Please delete that message. Account or consumer numbers are fine.",
            hinglish="OTP, PIN, CVV, password ya card number main save nahi karti - aur kabhi "
                     "maangungi bhi nahi. Woh message delete kar dijiye. Account ya consumer "
                     "number chalega."))
    m = re.search(
        r"(?:my\s+)?(?P<company>[a-z][a-z ]{1,20}?\s+)?(?P<label>(?:broadband |postpaid |prepaid |"
        r"electricity |gas |dth |insurance |bank )?(?:account|acct|consumer|customer|policy|"
        r"order|registered mobile|mobile|subscriber|crn|ca|service)\s*(?:no\.?|number|id|num)?)"
        r"\s*(?:is|hai|:|=|-)\s*(?P<value>[a-z0-9][a-z0-9-]{3,})",
        t,
    )
    if not m or not re.search(r"\d", m.group("value")):
        return None
    company = detect_company(t)
    label_core = m.group("label").strip()
    label = f"{company + ' ' if company else ''}{label_core}".strip()
    raw_value = (text or "")[m.start("value"): m.end("value")] or m.group("value")
    return InterpretOut(
        intent=Intent.SAVE_IDENTIFIER,
        identifier=IdentifierOut(company=company, label=label, value=raw_value.upper()
                                 if re.search(r"[a-z]", raw_value) else raw_value),
        reply=c.say(en=f"Saved your {label}. I'll share it only on calls you approve.",
                    hinglish=f"Aapka {label} save kar liya. Sirf aapki approval wali calls pe "
                             f"share karungi."),
    )


def _rate(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    rating = None
    m = re.search(r"([1-5])\s*(?:/\s*5|stars?|★)", t)
    if m:
        rating = int(m.group(1))
    positive = has_any(t, ("was great", "was good", "very good", "excellent", "achha tha",
                           "accha tha", "badhiya", "on time", "loved", "fantastic"))
    negative = has_any(t, ("overcharged", "rude", "bekaar", "bakwas", "terrible", "worst",
                           "didn't come", "didnt come", "nahi aaya", "no show", "no-show",
                           "late aaya", "came late", "cheated"))
    if rating is None and not positive and not negative:
        return None
    if not (has_any(t, ("plumber", "electrician", "salon", "clinic", "doctor", "guy", "he ",
                        "she ", "they", "service", "technician", "was", "tha", "thi"))
            or rating is not None):
        return None
    biz_ref, _bid = detect_business_name(text, c.ctx)
    if rating is None:
        rating = 5 if positive and not negative else 2
    outcome = None
    if has_any(t, ("didn't come", "didnt come", "nahi aaya", "no show", "no-show")):
        outcome = "no-show"
    elif "overcharg" in t:
        outcome = "overcharged"
    elif has_any(t, ("on time",)):
        outcome = "on time"
    return InterpretOut(intent=Intent.RATE_VENDOR,
                        vendor_rating=VendorRatingOut(business_ref=biz_ref, rating=rating,
                                                      outcome=outcome, note=text.strip()[:200]),
                        reply=c.say(en="Noted - I'll remember that for next time.",
                                    hinglish="Note kar liya, agli baar dhyan rakhungi."))


_LANG_WORDS = {"marathi": Language.MR, "hindi": Language.HI, "english": Language.EN,
               "tamil": Language.TA, "telugu": Language.TE, "kannada": Language.KN,
               "bengali": Language.BN, "bangla": Language.BN, "gujarati": Language.GU,
               "malayalam": Language.ML, "punjabi": Language.PA, "odia": Language.OR}


def _add_person(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    if not re.search(r"\b(add|save)\b", t) and not re.search(
            r"\bmy (dad|father|mom|mother|wife|husband|son|daughter|brother|sister|"
            r"friend)('s name)? is\b", t):
        return None
    rel = relation_word_in(t)
    phones = extract_phones(text)
    if rel is None and not phones:
        return None
    name = None
    m = re.search(r"(?:add|save)\s+(?:my\s+)?(?:\w+\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if m and m.group(1).lower() not in {w for ws in RELATION_WORDS.values() for w in ws}:
        name = m.group(1)
    if not name:
        m = re.search(r"(?:name is|naam)\s+([A-Z]?[a-z]+(?:\s+[A-Z][a-z]+)?)", text)
        if m:
            name = _title(m.group(1))
    if not name:
        m = re.search(r"\b(?:dad|father|mom|mother|wife|husband|son|daughter|brother|sister|"
                      r"friend|papa|mummy)\s+([A-Z][a-z]+)", text)
        if m:
            name = m.group(1)
    relation = rel[0] if rel else None
    if not name:
        name = _title(rel[1]) if rel else "New contact"
    language = None
    for word, lang in _LANG_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            language = lang
            break
    city = None
    m = re.search(r"(?:lives in|stays in|rehte hain|rehti hain|based in|from)\s+"
                  r"([a-z][a-z ]{2,25}?)(?=$|[,.]| and | aur )", t)
    if m:
        city = _title(m.group(1).strip())
    person = PersonOut(name=name, relation=relation, phone=phones[0] if phones else None,
                       language=language, aliases=[rel[1]] if rel else [], city=city)
    place = PlaceOut(label=f"{first_name(name)}'s home", address_text=city, city=city,
                     person_ref=name) if city else None
    bits = [name]
    if phones:
        bits.append(phones[0])
    if language:
        bits.append(language.value)
    if city:
        bits.append(city)
    who = _title(rel[1]) if rel else name
    reply = c.say(en=f"Added {who}: {' · '.join(bits)}. What's the address? Type it, paste a Maps "
                     f"link or share a location pin.",
                  hinglish=f"{who} add kar liya: {' · '.join(bits)}. Address kya hai? Type kariye, "
                           f"Maps link bhejiye ya location pin share kariye.")
    return InterpretOut(intent=Intent.ADD_PERSON, person=person, place=place, reply=reply)


_MAPS = re.compile(r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.[a-z.]+/maps)"
                   r"\S*", re.I)


def _add_place(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    link = _MAPS.search(text or "")
    m = re.search(r"(?:save|set)\s+(?:this|it|my)?\s*(?:as|address as)?\s*['\"]?([\w' &]+?)['\"]?"
                  r"\s*(?:address)?\s*(?:as|is|:|-)\s+(.+)$", t)
    m2 = re.search(r"\bmy\s+(home|office|work|ghar|pg|flat)(?:\s+address)?\s+(?:is|hai)\s+"
                   r"(?:at|in)?\s*(.+)$", t)
    if not (link or m or m2 or (has_any(t, ("save this as", "save it as")))):
        return None
    label, addr = None, None
    if m2:
        label, addr = _title(m2.group(1)), m2.group(2).strip(" .")
    elif m:
        label, addr = _title(m.group(1).strip()), m.group(2).strip(" .")
    sm = re.search(r"save (?:this|it) as ['\"]?(.+?)['\"]?$", t)
    if sm:
        label, addr = _title(sm.group(1)), None
    if label and label.lower() in {"office", "work"}:
        label = "Office"
    if label and label.lower() in {"home", "ghar"}:
        label = "Home"
    rel = relation_word_in(t)
    person_ref = rel[1] if rel and ("'s" in t or "ke" in t) else None
    place = PlaceOut(label=label or "Saved place", address_text=addr if not link else None,
                     person_ref=person_ref, maps_link=link.group(0) if link else None)
    return InterpretOut(intent=Intent.ADD_PLACE, place=place,
                        reply=c.say(en=f"Saved \"{place.label}\". I'll use it for nearby searches "
                                       f"and home visits.",
                                    hinglish=f"\"{place.label}\" save kar liya. Paas ki searches aur "
                                             f"home visits ke liye use karungi."))


def _query_memory(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    if not (has_any(t, ("what's my", "what is my", "whats my", "do you remember",
                        "what do you know about me", "kya yaad hai", "mera kya", "number of my",
                        "what was the", "who is my")) or re.search(r"mer[aie] .* kya (hai|tha)",
                                                                    t)):
        return None
    ctx = c.ctx
    if "know about me" in t:
        lines = [f"Name: {ctx.profile.name or '-'}", f"City: {ctx.profile.city or '-'}",
                 f"Language: {ctx.profile.language.value}", f"Tone: {ctx.profile.tone.value}"]
        lines += [f"{p.relation or 'person'}: {p.name}" for p in ctx.people]
        lines += [f"Place: {p.label}" for p in ctx.places if not p.ephemeral]
        lines += [f"{f.key.replace('_', ' ')}: {f.value}" for f in ctx.facts[:10]]
        return InterpretOut(intent=Intent.QUERY_MEMORY, reply="\n".join(lines) +
                            "\nSay 'forget …' to remove anything.")
    words = [w for w in re.findall(r"[a-z]{3,}", t) if w not in
             {"what", "whats", "my", "the", "number", "remember", "you", "was", "who", "kya",
              "mera", "meri", "hai", "tha", "of", "is"}]
    hits = [f"{f.key.replace('_', ' ')}: {f.value}" for f in ctx.facts
            if any(w in norm(f.key + ' ' + f.value) for w in words)]
    hits += [f"{b.name}: {b.phone}" for b in ctx.known_businesses
             if any(w in norm(f"{b.name} {b.category or ''}") for w in words)]
    reply = "\n".join(hits[:5]) if hits else c.say(
        en="I don't have that saved yet. Tell me and I'll remember it.",
        hinglish="Yeh abhi mere paas save nahi hai. Bata dijiye, yaad rakhungi.")
    return InterpretOut(intent=Intent.QUERY_MEMORY, reply=reply)


def _status(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    if not (has_any(t, ("status", "any update", "update?", "kya hua", "what happened",
                        "kaha tak", "kahan tak", "progress")) or t in ("update", "updates")):
        return None
    tasks = c.ctx.open_tasks
    if not tasks:
        return InterpretOut(intent=Intent.STATUS, reply=c.say(
            en="Nothing pending right now. What should I do next?",
            hinglish="Abhi kuch pending nahi hai. Aage kya karun?"))
    lines = [f"• {task.spec.goal} - {task.status.value.replace('_', ' ')}" for task in tasks[:5]]
    return InterpretOut(intent=Intent.STATUS, task_id=tasks[0].id, reply="\n".join(lines))


def _cancel(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    if not (has_any(t, ("cancel the call", "cancel this task", "cancel the task", "cancel it",
                        "cancel that", "stop the call", "rehne do", "mat karo", "don't call",
                        "dont call", "cancel request", "call mat karo")) or t in ("cancel",
                                                                                  "stop")):
        return None
    task = _newest(c.ctx.open_tasks)
    return InterpretOut(intent=Intent.CANCEL_TASK, task_id=task.id if task else None,
                        reply=c.say(en="Cancelled. I won't make that call.",
                                    hinglish="Cancel kar diya. Woh call nahi karungi."))


def _forget(c: _Ctx, text: str) -> InterpretOut | None:
    t = norm(text)
    m = re.match(r"^(?:please\s+)?(?:forget|bhool jao|delete)\s+(?:my\s+|about\s+)?(.+)$", t)
    if not m or has_any(t, ("everything", "all my data", "sab")):
        return None
    what = m.group(1)
    words = [w for w in re.findall(r"[a-z]{3,}", what) if w not in {"the", "date", "my"}]
    matched = [f for f in c.ctx.facts if any(w in norm(f.key + " " + f.value) for w in words)]
    facts = [FactOut(kind=f.kind, key=f.key, value=f.value) for f in matched]
    shown = matched[0].value if matched else what
    return InterpretOut(intent=Intent.SETTINGS, facts=facts, confidence=0.7,
                        reply=c.say(en=f"Forget \"{shown}\"? I'll also stop related reminders.",
                                    hinglish=f"\"{shown}\" bhool jaun? Uske reminders bhi band "
                                             f"ho jayenge."))


def _task_reply(c: _Ctx, d: TaskDraft) -> str:
    asks: list[str] = []
    for f in d.missing[:2]:
        asks.append({
            "business_phone": c.say(en="Which place should I call? Share the name or number "
                                       "(or say 'find one').",
                                    hinglish="Kahan call karun? Naam ya number bhejiye "
                                             "(ya bolo 'dhundo')."),
            "when_text": c.say(en="For when? Any time preference?",
                               hinglish="Kab ke liye? Koi time preference?"),
            "item": c.say(en="What exactly should I order or ask for?",
                          hinglish="Exactly kya mangwana/poochna hai?"),
            "company": c.say(en="Which company is this with?",
                             hinglish="Kaunsi company ka hai?"),
            "stay": c.say(en="Which city and dates (check-in to check-out)?",
                          hinglish="Kaunsa sheher aur kaunsi dates (check-in se check-out)?"),
            "recurrence": c.say(en="How often - which days and time?",
                                hinglish="Kitni baar - kaunse din aur time?"),
            "beneficiary": c.say(en="Who should I call?", hinglish="Kisko call karun?"),
            "discovery_query": c.say(en="What kind of place should I look for?",
                                     hinglish="Kis type ki jagah dhundun?"),
        }.get(f, c.say(en=f"I need the {f.replace('_', ' ')}.")))
    if asks:
        return " ".join(asks)
    target = d.business_name or d.company or (d.discovery_query and f"good {d.discovery_query} "
                                              f"options") or "them"
    when = f", {d.when_text}" if d.when_text else ""
    if d.type == TaskType.WELLBEING_CHECKIN:
        who = (d.beneficiary_ref or "them").title()
        return c.say(en=f"I'll first ask {who} once for permission, then do a short friendly "
                        f"check-in call and send you a summary.",
                     hinglish=f"Pehle {who} se ek baar permission lungi, phir chhoti si "
                              f"check-in call karke aapko summary bhejungi.")
    if d.type == TaskType.CUSTOMER_CARE:
        return c.say(en=f"I'll call {target}'s official number, get through the IVR and update "
                        f"you. I'll only share details you approve.",
                     hinglish=f"{target} ke official number pe call karti hoon, IVR se agent tak "
                              f"pahunch ke batati hoon. Sirf aapke approve kiye details share "
                              f"karungi.")
    if d.type == TaskType.HOTEL_BOOKING:
        dest = d.stay.destination if d.stay else "your destination"
        return c.say(en=f"Looking for stays in {dest}{when}. I'll compare online rates with "
                        f"direct rates and check with you before booking anything.",
                     hinglish=f"{dest} mein stays dhundh rahi hoon{when}. Online aur direct rates "
                              f"compare karke, book karne se pehle aapse poochungi.")
    if d.type == TaskType.STOCK_HUNT:
        return c.say(en=f"Calling nearby chemists/shops for {d.item or 'it'}, a few at a time. "
                        f"I'll stop at the first one that has it.",
                     hinglish=f"{d.item or 'Yeh'} ke liye paas ki dukaanon ko 3-3 karke call kar "
                              f"rahi hoon. Mil gaya toh wahin ruk jaungi.")
    if d.discovery_query and not d.business_phone and not d.business_name:
        near = f" near {d.location_text or d.place_ref}" if (d.location_text or d.place_ref) \
            else ""
        return c.say(en=f"Looking for good {d.discovery_query} options{near}…",
                     hinglish=f"{d.discovery_query}{near} ke achhe options dhundh rahi hoon…")
    if d.delegation and d.delegation.granted:
        limits = []
        if d.delegation.time_window_text:
            limits.append(f"any slot {d.delegation.time_window_text}")
        if d.delegation.max_price_inr:
            limits.append(f"under {format_inr(d.delegation.max_price_inr)}")
        lim = " ".join(limits) or "within what you said"
        return c.say(en=f"Got it. I'll book {lim} without checking back. Calling {target} now.",
                     hinglish=f"Samajh gayi. {lim} mein bina poochhe book kar dungi. {target} ko "
                              f"abhi call kar rahi hoon.")
    if d.type in (TaskType.ENQUIRY, TaskType.STATUS_CHASE, TaskType.RECONFIRM,
                  TaskType.RUNNING_LATE, TaskType.CANCEL_BOOKING):
        return c.say(en=f"Calling {target} now.", hinglish=f"{target} ko abhi call kar rahi hoon.")
    return c.say(en=f"Calling {target} now{when}. I'll come back with their options before "
                    f"confirming anything.",
                 hinglish=f"{target} ko abhi call kar rahi hoon{when}. Options lekar aapse "
                          f"confirm karungi, phir book.")


# =============================================================================== entry point


def interpret(ctx: ConversationContext, msg: InboundMessage) -> InterpretOut:
    c = _Ctx(ctx)
    text = (msg.text or "").strip()
    t = norm(text)
    if msg.kind == MessageKind.BUTTON_REPLY or msg.button_id:
        out = _button(c, msg)
        if out is not None:
            return out
    if msg.kind == MessageKind.LOCATION and msg.location is not None:
        return _location(c, msg)
    if msg.kind == MessageKind.CONTACT and msg.contact_phone:
        waiting = _open(ctx, TaskStatus.NEEDS_INFO)
        if waiting:
            return InterpretOut(intent=Intent.TASK_UPDATE, task_id=_newest(waiting).id,
                                task=TaskDraft(type=_newest(waiting).type,
                                               goal=_newest(waiting).spec.goal,
                                               business_phone=msg.contact_phone),
                                reply=c.say(en="Got the number, calling now.",
                                            hinglish="Number mil gaya, call kar rahi hoon."))
        return InterpretOut(intent=Intent.ADD_PERSON,
                            person=PersonOut(name=text or "New contact",
                                             phone=msg.contact_phone),
                            reply=c.say(en="Got the contact. Who is this - should I save them "
                                           "to your circle?",
                                        hinglish="Contact mil gaya. Yeh kaun hain - circle mein "
                                                 "save karun?"))
    if msg.kind in (MessageKind.IMAGE, MessageKind.DOCUMENT) and not t:
        task = _newest(ctx.open_tasks)
        if task:
            return InterpretOut(intent=Intent.TASK_UPDATE, task_id=task.id,
                                reply=c.say(en="Got it, reading it now.",
                                            hinglish="Mil gaya, padh rahi hoon."))
        return InterpretOut(intent=Intent.UNKNOWN, reply=c.say(
            en="Got the file. What should I do with it?", hinglish="File mil gayi. Iska kya karun?"))
    if not t:
        return InterpretOut(intent=Intent.UNKNOWN, reply=c.say(
            en="Sorry, I didn't catch that. Could you say it again?",
            hinglish="Sorry, samajh nahi aaya. Ek baar phir bolenge?"))

    # sensitive first
    if has_any(t, ("delete everything", "delete all my data", "delete my data", "erase my data",
                   "sab data delete", "mera data delete", "mera sab data", "delete my account",
                   "forget everything", "sab kuch delete")):
        n = len(ctx.open_tasks)
        pending = (f" {n} pending task{'s' if n != 1 else ''} will be cancelled too." if n else "")
        return InterpretOut(intent=Intent.DELETE_DATA, requires_pin=True, reply=c.say(
            en=f"This permanently deletes your profile, memory, call recordings, transcripts "
               f"and history.{pending} Send your Friday PIN to confirm.",
            hinglish=f"Yeh sab permanently delete hoga: profile, memory, call recordings, "
                     f"transcripts, history.{pending} Confirm karne ke liye apna Friday PIN "
                     f"bhejiye."))
    ident = _identifier(c, text)
    if ident is not None and ident.identifier is None:
        return ident  # refusal of OTP/PIN/CVV
    answered = _answer_pending(c, text)
    if answered is not None:
        return answered
    if has_any(t, ("invite code", "invite codes", "invite", "refer a friend", "my invites")) \
            and len(t.split()) <= 8:
        return InterpretOut(intent=Intent.INVITE, reply=c.say(
            en="Here are your invite codes - each works once.",
            hinglish="Yeh rahe aapke invite codes - har code ek baar chalega."))
    if t in ("help", "menu", "?") or has_any(t, ("what can you do", "kya kar sakti",
                                                 "how does this work", "help me understand")):
        return InterpretOut(intent=Intent.HELP, reply=c.say(
            en="I make calls for you: bookings, enquiries, orders, quotes, complaints, "
               "customer care, hotel stays, family check-ins. Try: \"Book a haircut at Looks "
               "tomorrow 6pm\" or \"any slot 5-7pm under ₹800, you decide\". Say 'status' for "
               "updates.",
            hinglish="Main aapke liye calls karti hoon: bookings, enquiries, orders, quotes, "
                     "complaints, customer care, hotel, family check-ins. Try: \"Looks mein kal "
                     "6 baje haircut book karo\" ya \"5-7 ke beech koi bhi slot, ₹800 tak, aap "
                     "decide karo\". Updates ke liye 'status' bolo."))
    for handler in (_settings, _forget, _approval, _cancel, _status):
        out = handler(c, text)
        if out is not None:
            return out
    if ident is not None:
        return ident
    for handler in (_add_person, _add_place, _rate, _query_memory):
        out = handler(c, text)
        if out is not None:
            return out

    draft = draft_task(c, text, msg)
    facts = extract_facts(text, ctx.now, ctx)
    if draft is not None:
        return InterpretOut(intent=Intent.NEW_TASK, task=draft, facts=facts,
                            reply=_task_reply(c, draft), confidence=0.85)
    if facts:
        f = facts[0]
        when = ""
        if f.due_on and f.confidence >= 0.8 and len(f.due_on) == 10 and \
                f.kind == FactKind.DATE and f.due_on[5:7] not in f.value:
            when = f" ({datetime.fromisoformat(f.due_on).strftime('%d %b')})"
        ask = ""
        if f.confidence < 0.8:
            ask = c.say(en=" Do you know the exact date?", hinglish=" Exact date pata hai?")
        return InterpretOut(intent=Intent.REMEMBER, facts=facts, reply=c.say(
            en=f"Noted: {f.value}{when}. I'll remind you ahead of time.{ask}",
            hinglish=f"Noted: {f.value}{when}. Time se pehle yaad dila dungi.{ask}"))
    if has_any(t, SMALL_TALK) and len(t.split()) <= 5:
        greet = c.name or ""
        return InterpretOut(intent=Intent.SMALL_TALK, reply=c.say(
            en=f"Hey{' ' + greet if greet else ''}! What can I take off your plate today?",
            hinglish=f"Hi{' ' + greet if greet else ''}! Aaj kya kaam karun aapke liye?"))
    task = _newest(_open(ctx, TaskStatus.NEEDS_INFO))
    if task is not None:
        return InterpretOut(intent=Intent.TASK_UPDATE, task_id=task.id,
                            task=_update_from_text(c, task.type, task.spec.goal, text),
                            reply=c.say(en="Thanks, got it.", hinglish="Theek hai, samajh gayi."))
    return InterpretOut(intent=Intent.UNKNOWN, confidence=0.3, reply=c.say(
        en="I'm not sure I got that. Want me to make a call, check something or remember it?",
        hinglish="Main theek se samajh nahi payi. Call karun, kuch check karun ya yaad rakhun?"))


def _update_from_text(c: _Ctx, ttype: TaskType, goal: str, text: str) -> TaskDraft:
    when = parse_when(text, c.ctx.now)
    phones = extract_phones(text)
    bmax, btarget = extract_budget(text)
    name, _ = detect_business_name(text, c.ctx)
    ws, we = _resolve_window(when, c.ctx.now)
    amounts = extract_amounts(text)
    return TaskDraft(type=ttype, goal=goal, business_phone=phones[0] if phones else None,
                     business_name=name, when_text=when.text or None, window_start=ws,
                     window_end=we, preferred_times=[when.text] if when.text else [],
                     budget_max_inr=bmax or (amounts[0] if amounts and not phones else None),
                     budget_target_inr=btarget, notes=text.strip()[:200])


def _location(c: _Ctx, msg: InboundMessage) -> InterpretOut:
    pin = msg.location
    assert pin is not None
    ctx = c.ctx
    label = pin.name or "Pinned location"
    person_ref = None
    ephemeral = True
    for turn in reversed(ctx.recent[-4:]):
        if turn.direction == Direction.OUTBOUND and has_any(norm(turn.text), (
                "address", "location pin", "share your home", "save your home")):
            ephemeral = False
            rel = relation_word_in(norm(turn.text))
            hits = [p for p in ctx.people if p.name and p.name.split()[0].lower()
                    in norm(turn.text)]
            if hits:
                person_ref = hits[0].name
                label = f"{first_name(hits[0].name)}'s home"
            elif rel:
                person_ref = rel[1]
                label = f"{_title(rel[1])}'s home"
            elif "office" in norm(turn.text):
                label = "Office"
            else:
                label = "Home"
            break
    place = PlaceOut(label=label, address_text=pin.address, person_ref=person_ref)
    reply = c.say(en=f"Saved as \"{label}\"." if not ephemeral else
                  "Got your location. I'll search around here.",
                  hinglish=f"\"{label}\" ke naam se save kar liya." if not ephemeral else
                  "Location mil gayi. Yahin aas-paas dhundhungi.")
    out = InterpretOut(intent=Intent.ADD_PLACE, place=place, reply=reply)
    if ephemeral:
        out.place.aliases = ["__ephemeral__"]
    return out
