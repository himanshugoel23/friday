# ruff: noqa: E501
"""Bills: intake from forwarded text, a confirmed record, and reminders through the proactive engine.

Friday NEVER pays a bill. It remembers the due date, reminds (3 days before, 1 day before, on the
day) and offers a pay link only when the user supplied it or it is a known biller deep link from
``KNOWN_BILLER_LINKS`` (empty until a person adds verified links). A link is never invented.

    parse_bill_text("BSES bill Rs 1,240 due on 25 Oct 2026", today)  -> BillParse (user confirms)
    bill_reminders(user_id, bills, now, config)                       -> [NudgeCandidate]

Raw forwarded text is NOT stored: only the extracted fields, after the user confirms them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import at_ist, ist_date, utcnow
from friday.core.models import (
    AutonomyCategory,
    NudgeCandidate,
    NudgeKind,
    Urgency,
    new_id,
)
from friday.savings import copy
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.money import find_amounts
from friday.savings.wallet import BANKS, looks_sensitive


class BillSource(StrEnum):
    FORWARDED = "forwarded"
    GMAIL = "gmail"
    MANUAL = "manual"


class BillStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"


class BillKind(StrEnum):
    ELECTRICITY = "electricity"
    GAS = "gas"
    WATER = "water"
    BROADBAND = "broadband"
    MOBILE = "mobile"
    DTH = "dth"
    CREDIT_CARD = "credit_card"
    OTHER = "other"


class Bill(BaseModel):
    """A bill the user asked Friday to track. ``confirmed`` is False until they say "sahi hai"."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    user_id: str = ""
    biller: str
    kind: BillKind = BillKind.OTHER
    amount_paise: int | None = Field(default=None, ge=0)
    min_due_paise: int | None = Field(default=None, ge=0)  # credit card: minimum amount due
    due_date: date
    source: BillSource = BillSource.MANUAL
    status: BillStatus = BillStatus.PENDING
    pay_link: str | None = None
    pay_link_source: str | None = None  # "user" | "forwarded" | "biller_known"
    confirmed: bool = False
    snoozed_until: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    paid_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.confirmed and self.status in {BillStatus.PENDING, BillStatus.SNOOZED}


# ------------------------------------------------------------------ pay links

# Verified deep links of billers, key = lowercase biller name. EMPTY on purpose: a person adds a
# row only from the biller's own public page. Nothing here is invented.
KNOWN_BILLER_LINKS: dict[str, str] = {}


def valid_pay_link(url: str) -> bool:
    """https only, a real host, no credentials, no IP literal, sane length."""
    url = url.strip()
    if len(url) > 500 or any(c.isspace() for c in url):
        return False
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or "." not in host or parts.username or parts.password:
        return False
    return not re.fullmatch(r"[\d.]+|[0-9a-f:]+", host)


def known_pay_link(biller: str) -> str | None:
    link = KNOWN_BILLER_LINKS.get(biller.strip().lower())
    return link if link and valid_pay_link(link) else None


def choose_pay_link(
    biller: str, *, user_supplied: str | None = None, forwarded: str | None = None
) -> tuple[str | None, str | None]:
    """(link, source). The user's own link wins, then a known biller link, then a link found in
    the forwarded text. Anything else is None: Friday does not make links up."""
    if user_supplied and valid_pay_link(user_supplied):
        return user_supplied.strip(), "user"
    known = known_pay_link(biller)
    if known:
        return known, "biller_known"
    if forwarded and valid_pay_link(forwarded):
        return forwarded.strip(), "forwarded"
    return None, None


# ------------------------------------------------------------------ intake parser

_KIND_WORDS: list[tuple[BillKind, re.Pattern[str]]] = [
    (BillKind.CREDIT_CARD, re.compile(
        r"credit\s*card|card\s+statement|total\s+amount\s+due|minimum\s+(?:amount\s+)?due|"
        r"card\s+ending|statement\s+date", re.I)),
    (BillKind.ELECTRICITY, re.compile(
        r"electricity|bijli|\bbses\b|\bbypl\b|tata\s*power|adani\s*electricity|\bmseb\b|"
        r"\bdiscom\b|kwh|units\s+consumed|power\s+bill|torrent\s*power|\bpspcl\b|\bbescom\b", re.I)),
    (BillKind.GAS, re.compile(
        r"piped\s+gas|\bpng\b|\bigl\b|indraprastha|mahanagar\s+gas|\bmgl\b|gas\s+bill|"
        r"gas\s+cylinder|\blpg\b", re.I)),
    (BillKind.WATER, re.compile(r"water\s+(?:bill|board|supply|tax)|jal\s+board|\bdjb\b", re.I)),
    (BillKind.BROADBAND, re.compile(
        r"broadband|fibre|fiber|wifi|wi-fi|jiofiber|airtel\s*xstream|\bact\s+fibernet\b|"
        r"internet\s+bill", re.I)),
    (BillKind.DTH, re.compile(
        r"\bdth\b|tata\s*play|dish\s*tv|\bd2h\b|sun\s*direct|airtel\s+digital\s*tv|set[- ]top", re.I)),
    (BillKind.MOBILE, re.compile(
        r"recharge|prepaid|postpaid|plan\s+(?:expires|expiry|validity)|validity\s+(?:ends|expires)|"
        r"mobile\s+bill|data\s+pack", re.I)),
]
_BILLER_NAMES = (
    "BSES", "Tata Power", "Adani Electricity", "Torrent Power", "BESCOM", "MSEB", "PSPCL",
    "Indraprastha Gas", "IGL", "Mahanagar Gas", "MGL", "Delhi Jal Board", "JioFiber",
    "Airtel Xstream", "ACT Fibernet", "Tata Play", "Dish TV", "d2h", "Sun Direct", "Jio",
    "Airtel", "Vi", "BSNL",
)
_KIND_LABEL = {
    BillKind.ELECTRICITY: "Bijli",
    BillKind.GAS: "Gas",
    BillKind.WATER: "Paani",
    BillKind.BROADBAND: "Broadband",
    BillKind.MOBILE: "Mobile recharge",
    BillKind.DTH: "DTH",
    BillKind.CREDIT_CARD: "Credit card",
    BillKind.OTHER: "Bill",
}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE_PATTERNS = [
    # 25/10/2026, 25-10-26, 25.10.2026 (day first, as in India)
    re.compile(r"(?<!\d)(?P<d>\d{1,2})\s*[/\-.]\s*(?P<m>\d{1,2})\s*[/\-.]\s*(?P<y>\d{4}|\d{2})(?!\d)"),
    # 25 Oct 2026, 25th October, 25-Oct-2026
    re.compile(
        rf"(?<!\d)(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s\-/,.]*(?P<mon>{_MON})\b[\s\-/,.]*(?P<y>\d{{4}}|\d{{2}})?(?!\d)",
        re.I,
    ),
    # "27 tarikh tak" / "27 date ko": only the day, next time that day comes round
    re.compile(r"(?<!\d)(?P<d>\d{1,2})\s*(?:tarikh|tareekh|tarikhh)\b", re.I),
    # October 25, 2026 / Oct 25
    re.compile(
        rf"\b(?P<mon>{_MON})\b[\s\-/.]*(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<y>\d{{4}}))?(?!\d)",
        re.I,
    ),
]
_DUE_LABEL = re.compile(
    r"(?:due\s*(?:date|on|by)?|pay(?:able)?\s*(?:by|before|on)|last\s*date|payment\s*date|"
    r"expires?\s*on|valid(?:ity)?\s*(?:till|until|ends?)|bhugtan|antim\s*tithi|tak\s*bharein)"
    r"[^0-9a-z]{0,6}",
    re.I,
)
_TOTAL_LABEL = re.compile(
    r"(?P<strong>total\s+amount\s+due|amount\s+(?:due|payable)|net\s+payable|bill\s+amount|"
    r"total\s+(?:due|bill|payable)|bill\s+of|balance\s+due)|(?P<weak>payable|pay\s+now|amount|total)",
    re.I,
)
_MIN_LABEL = re.compile(r"min(?:imum)?\.?\s*(?:amount\s*)?(?:due|payable|payment)", re.I)
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


@dataclass
class BillParse:
    kind: BillKind
    biller: str
    amount_paise: int | None = None
    min_due_paise: int | None = None
    due_date: date | None = None
    pay_link: str | None = None  # a link found in the forwarded text (not yet trusted)
    missing: list[str] = field(default_factory=list)
    sensitive: str | None = None

    @property
    def usable(self) -> bool:
        return self.sensitive is None and self.due_date is not None and self.kind is not None


def _to_date(d: int, m: int, y: int | None, today: date) -> date | None:
    try:
        if y is None:
            for yr in (today.year, today.year + 1):
                cand = date(yr, m, d)
                if cand >= today - timedelta(days=7):
                    return cand
            return None
        if y < 100:
            y += 2000
        return date(y, m, d)
    except ValueError:
        return None


def _next_day_of_month(day: int, today: date) -> date | None:
    """The next date (today included) whose day-of-month is ``day``."""
    y, m = today.year, today.month
    for _ in range(14):
        try:
            cand = date(y, m, day)
            if cand >= today:
                return cand
        except ValueError:
            pass
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _dates_in(text: str, today: date) -> list[tuple[int, date, int]]:
    found: list[tuple[int, date, int]] = []
    taken: list[tuple[int, int]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            g = m.groupdict()
            if "m" not in g and "mon" not in g:
                dt = _next_day_of_month(int(g["d"]), today)
            else:
                mon = g.get("mon")
                month = _MONTHS[mon.lower()] if mon else int(g["m"])
                year = int(g["y"]) if g.get("y") else None
                if not 1 <= month <= 12:
                    continue
                dt = _to_date(int(g["d"]), month, year, today)
            if dt is not None:
                found.append((m.start(), dt, m.end()))
                taken.append((m.start(), m.end()))
    return sorted(found, key=lambda t: t[0])


def _plausible(dt: date, today: date) -> bool:
    return today - timedelta(days=45) <= dt <= today + timedelta(days=400)


def _detect_kind(text: str) -> BillKind:
    for kind, rx in _KIND_WORDS:
        if rx.search(text):
            return kind
    return BillKind.OTHER


def _detect_biller(text: str, kind: BillKind) -> str:
    if kind == BillKind.CREDIT_CARD:
        low = text.lower()
        for canon, aliases in BANKS.items():
            if any(re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", low) for a in aliases):
                return f"{canon} credit card"
    for name in _BILLER_NAMES:
        if re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, re.I if len(name) > 3 else 0):
            return name
    return _KIND_LABEL[kind]


def parse_bill_text(text: str, today: date) -> BillParse:
    """Extract kind, biller, amount and due date from a forwarded bill/SMS with regexes only.
    The caller must show the result and get the user's confirmation."""
    reason = looks_sensitive(text)
    kind = _detect_kind(text)
    out = BillParse(kind=kind, biller=_detect_biller(text, kind))
    if reason == "card_number":
        # a bill may carry a long account number; that is fine, we never read or keep it. A card
        # number in a forward is dropped from view and the user is reminded not to send them.
        out.sensitive = None
    elif reason:
        out.sensitive = reason
        return out

    # --- dates first, so day and year numbers are not mistaken for money
    dates_all = _dates_in(text, today)
    masked = list(text)
    for pos, _dt, end in dates_all:
        masked[pos:end] = " " * (end - pos)
    work = "".join(masked)

    # --- amounts: minimum due first (so it is not mistaken for the total)
    for m in _MIN_LABEL.finditer(work):
        tail = work[m.end() : m.end() + 40]
        hit = next(iter(find_amounts(tail)), None)
        if hit:
            out.min_due_paise = hit.paise
            work = work[: m.start()] + " " * (m.end() + hit.end - m.start()) + work[m.end() + hit.end :]
    amounts = find_amounts(work)
    chosen = None
    for m in _TOTAL_LABEL.finditer(work):
        tail = work[m.end() : m.end() + 40]
        hit = next(iter(find_amounts(tail)), None)
        if hit and hit.paise > 0 and (hit.marked or m.group("strong")):
            chosen = hit.paise
            break
    if chosen is None:
        marked = [h for h in amounts if h.marked and h.paise > 0]
        if len(marked) == 1:
            chosen = marked[0].paise
        elif len(amounts) == 1 and amounts[0].paise > 0:
            chosen = amounts[0].paise
    out.amount_paise = chosen
    if chosen is None:
        out.missing.append("amount")

    # --- due date: the date right after a due-label, else the only date in the text
    dates = [(pos, d) for pos, d, _e in dates_all if _plausible(d, today)]
    due: date | None = None
    for m in _DUE_LABEL.finditer(text):
        after = [(p, d) for p, d in dates if m.end() - 2 <= p <= m.end() + 12]
        if after:
            due = after[0][1]
            break
    if due is None and len({d for _, d in dates}) == 1:
        due = dates[0][1]
    out.due_date = due
    if due is None:
        out.missing.append("due_date")

    link = next((u.rstrip(".,;") for u in _URL.findall(text) if valid_pay_link(u.rstrip(".,;"))), None)
    out.pay_link = link
    return out


def bill_from_parse(
    user_id: str, parse: BillParse, source: BillSource, *, user_link: str | None = None
) -> Bill:
    """An UNCONFIRMED bill from a usable parse. Raises ValueError when something is missing."""
    if parse.due_date is None:
        raise ValueError("due date missing")
    link, link_src = choose_pay_link(parse.biller, user_supplied=user_link, forwarded=parse.pay_link)
    return Bill(
        user_id=user_id,
        biller=parse.biller,
        kind=parse.kind,
        amount_paise=parse.amount_paise,
        min_due_paise=parse.min_due_paise,
        due_date=parse.due_date,
        source=source,
        pay_link=link,
        pay_link_source=link_src,
    )


# ------------------------------------------------------------------ buttons

BILL_PREFIX = "bill"
BILL_ACTIONS = ("ok", "paid", "snooze", "notmine")


def bill_button_id(bill_id: str, action: str) -> str:
    return f"{BILL_PREFIX}:{bill_id}:{action}"


def parse_bill_button(button_id: str) -> tuple[str, str] | None:
    parts = button_id.split(":")
    if len(parts) == 3 and parts[0] == BILL_PREFIX and parts[2] in BILL_ACTIONS:
        return parts[1], parts[2]
    return None


# ------------------------------------------------------------------ reminders


@dataclass(frozen=True)
class ReminderStage:
    name: str  # "d3" | "d1" | "d0" | "snooze"
    days_before: int
    send_at: datetime  # UTC
    expires_at: datetime  # UTC: after this the stage is stale and is not sent


def reminder_stages(bill: Bill, config: SavingsConfig = DEFAULT_CONFIG) -> list[ReminderStage]:
    """Planned reminders, earliest first. A stage stays valid until the next one begins (the last
    one until the end of the due day), so a bill added late gets only the stage that is current."""
    days = sorted(set(config.bill_reminder_days), reverse=True)
    hour = config.bill_reminder_hour_ist
    sends = [at_ist(bill.due_date - timedelta(days=n), hour) for n in days]
    end_of_due = at_ist(bill.due_date + timedelta(days=1), 0)
    stages = []
    for i, n in enumerate(days):
        expires = sends[i + 1] if i + 1 < len(days) else end_of_due
        stages.append(ReminderStage(f"d{n}", n, sends[i], expires))
    return stages


def bill_reminders(
    user_id: str, bills: list[Bill], now: datetime, config: SavingsConfig = DEFAULT_CONFIG
) -> list[NudgeCandidate]:
    """Candidates for the proactive engine (``triggers``-style: snapshot in, candidates out).

    The engine applies its own guardrails to them: quiet hours (22-08 IST), the daily cap (an
    over-cap reminder becomes a line of the morning digest), per-key dedupe and ignore-learning.
    Only confirmed, unpaid bills produce reminders; a snoozed bill is silent until its snooze ends.
    """
    out: list[NudgeCandidate] = []
    today = ist_date(now)
    for bill in bills:
        if bill.user_id and bill.user_id != user_id:
            continue
        if not bill.active:
            continue
        if bill.status == BillStatus.SNOOZED:
            until = bill.snoozed_until
            if until is None or until > now:
                continue
            end = at_ist(bill.due_date + timedelta(days=1), 0)
            if now < end:
                out.append(_candidate(user_id, bill, f"snooze{until:%Y%m%d%H}", until, end, today))
            continue
        for st in reminder_stages(bill, config):
            if st.send_at <= now < st.expires_at:
                out.append(_candidate(user_id, bill, st.name, st.send_at, st.expires_at, today))
    return out


def _candidate(
    user_id: str, bill: Bill, stage: str, due_at: datetime, expires_at: datetime, today: date
) -> NudgeCandidate:
    days_left = (bill.due_date - today).days
    text, buttons = copy.bill_reminder_message(bill, days_left)
    return NudgeCandidate(
        user_id=user_id,
        kind=NudgeKind.DATE_BASED,
        category=AutonomyCategory.REMINDERS,
        urgency=Urgency.NORMAL,
        reason=copy.bill_reminder_reason(bill, days_left),
        due_at=due_at,
        dedupe_key=f"bill:{bill.id}:{stage}",
        data={
            "expires_at": expires_at,
            "bill_id": bill.id,
            "stage": stage,
            "text": text,
            "buttons": [{"id": i, "title": t} for i, t in buttons],
            "pay_link": bill.pay_link,
        },
    )
