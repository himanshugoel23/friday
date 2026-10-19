"""Request understander: a WhatsApp message in English / Hinglish / Hindi -> a call-request draft
plus the list of missing fields (A1.10, A2.2, A2.3).

Deterministic first. An optional ``DraftLLM`` may propose values for fields the rules could not
fill, but every proposal is checked against the user's own words and dropped if it contains
anything the user did not say (a name, a number, a company). Friday never invents facts: the
purpose is the user's words, trimmed, never a rewrite.

One question at a time: ``Understanding.question_key`` is the copy key of the FIRST missing field;
the caller sends it, stores ``awaiting`` with the draft, and feeds the user's next message back in
through ``understand(text, prior=...)`` where it fills exactly that field.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field

from friday.calls.classify import classify, normalise
from friday.calls.contacts import RELATION_WORDS
from friday.calls.models import CalleeKind, Limits, PurposeKind
from friday.calls.numbers import canonical, is_emergency
from friday.core.clock import at_ist, ist_day_bounds, to_ist, utcnow

# ------------------------------------------------------------------ lexicons

FAMILY = {w for ws in RELATION_WORDS.values() for w in ws} | {
    "chacha", "chachi", "mama", "mami", "nana", "nani", "dada", "dadi", "bua", "fufa", "beta",
    "beti", "bhabhi", "jija", "saala", "saali", "sasur", "saas", "cousin", "uncle", "aunty",
    "dost", "friend", "yaar", "mom", "dad", "grandma", "grandpa", "son", "daughter",
}  # fmt: skip
PROVIDER = {
    "plumber", "electrician", "driver", "cook", "maid", "bai", "kaamwali", "carpenter", "mistri",
    "painter", "tutor", "landlord", "dhobi", "mechanic", "doodhwala", "gardener", "maali",
    "makaan malik", "makan malik", "ac wala", "bijli wala", "nanny", "watchman",
}  # fmt: skip
OFFICIAL = {
    "school", "college", "university", "rwa", "society", "municipal", "nagar nigam", "panchayat",
    "tehsil", "passport", "rto", "post office", "police station", "clinic", "hospital", "front desk",
    "help desk", "helpdesk", "principal", "admission", "ward office", "gram panchayat",
    "school office", "society office", "front office",
}  # fmt: skip
BRANDS = {
    "airtel", "jio", "vi", "vodafone", "bsnl", "hdfc", "icici", "sbi", "axis", "kotak", "amazon",
    "flipkart", "swiggy", "zomato", "paytm", "phonepe", "uber", "ola", "bescom", "tata power",
    "adani", "indane", "hp gas", "bharat gas", "irctc", "lic", "myntra", "bigbasket", "blinkit",
    "dunzo", "bank", "gas", "electricity", "bijli", "broadband", "dth", "tata play",
}  # fmt: skip
CARE_WORDS = {"customer care", "customer support", "helpline", "toll free", "tollfree", "support"}
BUSINESS = {
    "shop", "store", "restaurant", "salon", "dukaan", "dukan", "hotel", "showroom", "dealer",
    "boutique", "bakery", "pharmacy", "medical store", "gym", "cafe", "tailor",
}  # fmt: skip
GROUP_CUES = re.compile(
    r"\b(sabko|sab ko|sabhi ko|sab logon|everyone|everybody|all of them|group|invite all)\b", re.I
)
VAGUE = {
    "thing", "cheez", "baat", "kaam", "wo", "woh", "vo", "us", "uske", "uska", "baare", "bare",
    "about", "it", "the", "wali", "wala", "mein", "me", "ka", "ki", "ke", "uss", "iss", "iske",
}  # fmt: skip

_NUMBER = re.compile(r"(?<![\w])(\+?\d[\d\s\-]{6,}\d)(?![\w])")
_VERB_TAIL = (
    r"(?:phone|call|fone|dial|ring)(?:\s+(?:karke|kar\s*ke|kar\s*do|kardo|karo|karna|kijiye|"
    r"kijiyega|krke|krna|krdo|karein|kare))?"
)
_SAY = (
    r"(?:(?:bata\s*do|batao|bol\s*do|bolo|bolna|kehna|keh\s*do|batana|bata\s*dena|bol\s*dena|"
    r"let\s+\w+\s+know|tell(?:\s+\w+)?)\s*(?:ki|that)?)"
)
_CALLEE_KO = re.compile(
    rf"^\s*(?:please\s+|plz\s+|zara\s+)?(?:(?:mere|meri|apne|apni|my|the|ek)\s+)?"
    rf"(?P<who>.+?)\s+(?:ko|se|ka|ki)\s+{_VERB_TAIL}\b(?P<rest>.*)$",
    re.I | re.S,
)
_CALLEE_EN = re.compile(
    rf"^\s*(?:please\s+)?{_VERB_TAIL}\s+(?:(?:my|the|mere|meri)\s+)?(?P<who>[\w' .&\-]+?)"
    r"\s+(?:and|to|about|for|regarding|that|ko|se|aur|ki)\b(?P<rest>.*)$",
    re.I | re.S,
)
_CALLEE_SE = re.compile(r"^\s*(?P<who>.+?)\s+se\s+(?P<rest>.+)$", re.I | re.S)
_CALLEE_PLAIN = re.compile(
    rf"^\s*{_VERB_TAIL}\s+(?!(?:karo|karna|kar|kijiye|karein|kare|do|dijiye)\b)"
    r"(?:(?:my|the)\s+)?(?P<who>.+)$",
    re.I | re.S,
)
_MONEY = re.compile(
    r"(?:₹|rs\.?|rupees?|inr)\s*(\d[\d,]*(?:\.\d+)?)(\s*k\b)?|(\d[\d,]*)\s*(k\b\s*)?(?:rupe\w*|rs\b|₹)",
    re.I,
)
_DEADLINE = re.compile(r"\b(aaj|kal|parso|today|tomorrow|tonight)\s+(?:tak|se pehle|by|before)\b|"
                       r"\b(?:by|before)\s+(today|tomorrow|tonight)\b", re.I)  # fmt: skip
_TIME_CALL = re.compile(
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm|baje)?\s*(?:pe|par|tak|ko)?\s*"
    r"(?:ko\s+)?(?:call|phone|fone)\b",
    re.I,
)
_CALLBACK = re.compile(
    r"\b(missed call|call back|callback|wapas call|vapas call|jisne call kiya|jinhone call kiya)\b",
    re.I,
)
_MONEYISH = re.compile(
    r"₹|\brs\b|\brupe|\bprice\b|\bbudget\b|\bunder \d|\bmax\b|\btak\b|\bdeadline", re.I
)

PURPOSE_RULES: tuple[tuple[PurposeKind, re.Pattern[str]], ...] = (
    (PurposeKind.CALLBACK, _CALLBACK),
    (
        PurposeKind.DISPUTE,
        re.compile(
            r"\b(dispute|complaint|shikayat|galat charge|refund|overcharg|wrong bill|"
            r"galat bill|cancel|band kar)",
            re.I,
        ),  # fmt: skip
    ),
    (PurposeKind.INVITE, re.compile(r"\b(invite|party|shaadi|function|rsvp|aana hai)\b", re.I)),
    (PurposeKind.REMIND, re.compile(r"\b(yaad dila|remind|yaad)\b", re.I)),
    (PurposeKind.CONFIRM, re.compile(r"\b(confirm|pakka|reconfirm|sure kar)\b", re.I)),
    (
        PurposeKind.REQUEST,
        re.compile(
            r"\b(aane ke liye|aane|aao|bula|to come|book|appointment|schedule|bhej|"
            r"send|arrange|karwa|kara do|theek kar|repair)",
            re.I,
        ),  # fmt: skip
    ),
    (
        PurposeKind.ASK,
        re.compile(
            r"\b(puch|pooch|poochh|puchh|date|kab|kitna|kitne|ask|kya|kaun|price|"
            r"rate|timing)",
            re.I,
        ),  # fmt: skip
    ),
    (
        PurposeKind.INFORM,
        re.compile(
            r"\b(late|aa raha|aa rahi|pahunch|reach|nikal|busy|bata do|bol do|"
            r"let .* know|inform|tell)",
            re.I,
        ),  # fmt: skip
    ),
)

_DEVA_MAP = {
    "को": "ko", "से": "se", "फोन": "phone", "फ़ोन": "phone", "कॉल": "call", "करके": "karke",
    "करो": "karo", "कर": "kar", "बताओ": "batao", "बता": "bata", "दो": "do", "बोल": "bol",
    "कि": "ki", "का": "ka", "की": "ki", "के": "ke", "लिए": "liye", "पूछो": "puchho",
    "पूछ": "puch", "कहना": "kehna", "दीजिए": "dijiye",
}  # fmt: skip
FAMILY |= {"मम्मी", "मां", "माँ", "पापा", "भैया", "दीदी", "दोस्त", "भाई", "बहन", "पत्नी", "पति"}

_HINDI_WORDS = re.compile(
    r"\b(ko|se|karo|kar|karke|hai|hoon|hu|ki|ke|ka|bata|batao|kal|aaj|puchho|mein|nahi|aap|"
    r"mujhe|main|liye|wala|wali)\b",
    re.I,
)


# ------------------------------------------------------------------ result types


class Draft(BaseModel):
    """What we know so far. Every value is the user's own, or derived by a plain rule."""

    callee_ref: str | None = None
    callee_kind: CalleeKind | None = None
    kind_confident: bool = False  # False: could be a business or a person; contacts decide
    company: str | None = None
    number: str | None = Field(default=None, repr=False)  # E.164 typed by the user
    purpose: str | None = None
    purpose_kind: PurposeKind = PurposeKind.OTHER
    details: str | None = None
    limits: Limits = Field(default_factory=Limits)
    language: str = "hinglish"
    scheduled_for: datetime | None = None
    callback_of: str | None = None  # "missed:last" sentinel until the flow resolves the call
    group_members: list[str] = Field(default_factory=list)
    raw_text: str | None = Field(default=None, repr=False)


class Understanding(BaseModel):
    draft: Draft
    missing: list[str] = Field(default_factory=list)
    awaiting: str | None = None  # the field the next user message should fill
    question_key: str | None = None  # copy key of the one question to ask now
    rejected_llm_fields: list[str] = Field(default_factory=list)
    # set when the message itself must be refused or routed (threat, scam, emergency, ...)
    refusal_key: str | None = None
    refusal_category: str | None = None

    @property
    def ready(self) -> bool:
        return not self.missing


QUESTION_FOR = {
    "callee": "ask_callee",
    "purpose": "ask_purpose",
    "details": "ask_details",
    "limits": "ask_limits",
    "group_members": "ask_group_members",
}


class DraftLLM(Protocol):
    """Optional model hook. Returns a dict of PROPOSED fields (callee_ref, callee_kind, company,
    purpose, number) or None. The understander drops anything not grounded in the user's text."""

    async def propose(
        self, text: str, *, prior: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...


# ------------------------------------------------------------------ helpers


def detect_language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hindi"
    if len(_HINDI_WORDS.findall(text)) >= 1:
        return "hinglish"
    return "en"


def _romanise_function_words(text: str) -> str:
    """Devanagari function words -> roman so one set of rules serves both scripts; names and
    the purpose text are left in the user's script."""
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    return " ".join(_DEVA_MAP.get(tok, tok) for tok in text.split())


def _strip_determiners(who: str) -> str:
    who = re.sub(r"^(?:mere|meri|mera|apne|apni|my|the|ek|please)\s+", "", who.strip(), flags=re.I)
    return who.strip(" ,.-")


def _kind_of(who: str, purpose: str) -> tuple[CalleeKind | None, str | None, bool]:
    """(kind, company, confident) from the callee phrase and the purpose words."""
    w = normalise(who)
    words = set(w.split())
    company = next(
        (b for b in sorted(BRANDS, key=len, reverse=True) if re.search(rf"\b{re.escape(b)}\b", w)),
        None,
    )
    if words & FAMILY or any(f in w for f in ("mummy ji",)):
        return CalleeKind.FAMILY_FRIEND, None, True
    if any(c in w for c in CARE_WORDS) or (
        company and re.search(r"\b(care|support|helpline|service|desk)\b", w)
    ):
        return CalleeKind.CUSTOMER_CARE, (_company_before_care(who) or _pretty(company)), True
    if any(re.search(rf"\b{re.escape(o)}\b", w) for o in OFFICIAL):
        return CalleeKind.OFFICIAL, None, True
    if words & PROVIDER or any(p in w for p in PROVIDER if " " in p):
        return CalleeKind.PROVIDER, None, True
    if company:
        return CalleeKind.CUSTOMER_CARE, _pretty(company), True
    if any(re.search(rf"\b{re.escape(b)}\b", w) for b in BUSINESS):
        return CalleeKind.BUSINESS, None, True
    return None, None, False


_ACRONYMS = {"hdfc", "icici", "sbi", "lic", "bsnl", "irctc", "dth", "rto", "ola", "vi"}


def _pretty(company: str | None) -> str | None:
    if not company:
        return None
    return company.upper() if company in _ACRONYMS else company.title()


def _company_before_care(who: str) -> str | None:
    m = re.match(
        r"\s*([\w&.\- ]+?)\s+(customer care|customer support|helpline|support)\b", who, re.I
    )
    return m.group(1).strip() if m else None


def _split_names(who: str) -> list[str]:
    parts = re.split(r"\s*(?:,|\baur\b|\band\b|&|\+)\s*", who, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def _classify_purpose(text: str) -> PurposeKind:
    for kind, pat in PURPOSE_RULES:
        if pat.search(text):
            return kind
    return PurposeKind.OTHER


def _clean_purpose(rest: str) -> str:
    rest = rest.strip(" ,.-:")
    rest = re.sub(rf"^(?:{_VERB_TAIL}\s*)?", "", rest, flags=re.I).strip(" ,.-:")
    rest = re.sub(rf"^{_SAY}\s*", "", rest, flags=re.I).strip(" ,.-:")
    rest = re.sub(r"^(?:ki|that|ke|about|baare mein|bare me|regarding)\s+", "", rest, flags=re.I)
    return re.sub(r"\s+", " ", rest).strip(" ,.-:")


def _is_vague(purpose: str | None) -> bool:
    if not purpose:
        return True
    toks = [t for t in normalise(purpose).split() if t]
    return not toks or all(t in VAGUE for t in toks)


def parse_limits(text: str, *, now: datetime | None = None) -> Limits:
    """Price ceiling and deadline from the user's words. Nothing is guessed."""
    now = now or utcnow()
    out = Limits()
    m = _MONEY.search(text)
    if m:
        amount = m.group(1) or m.group(3)
        k = m.group(2) or m.group(4)
        try:
            value = float((amount or "0").replace(",", ""))
            out.max_price_inr = int(value * (1000 if k else 1))
        except ValueError:
            pass
    else:
        m2 = re.search(
            r"\b(?:under|upto|up to|max|maximum|tak)\s*(\d[\d,]*)\b|\b(\d[\d,]*)\s*(?:tak|se kam|ya kam)\b",
            text,
            re.I,
        )
        if m2:
            out.max_price_inr = int((m2.group(1) or m2.group(2)).replace(",", ""))
    d = _DEADLINE.search(text)
    if d:
        word = (d.group(1) or d.group(2) or "").lower()
        offset = {"aaj": 0, "today": 0, "tonight": 0, "kal": 1, "tomorrow": 1, "parso": 2}[word]
        day = to_ist(now).date() + timedelta(days=offset)
        out.deadline = ist_day_bounds(at_ist(day, 12))[1] - timedelta(minutes=1)
    return out


def _parse_call_time(text: str, now: datetime) -> datetime | None:
    """ "5 pm pe call karna" -> next 17:00 IST. Only when the hour is unambiguous (am/pm or 24h)."""
    m = _TIME_CALL.search(text)
    if not m:
        return None
    h, mi, ap = int(m.group("h")), int(m.group("m") or 0), (m.group("ap") or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif ap in ("", "baje") and h < 13:
        return None  # "5 baje" could be morning or evening: do not guess
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    local = to_ist(now)
    when = at_ist(local.date(), h, mi)
    if re.search(r"\bkal\b|\btomorrow\b", text, re.I) or when <= now:
        when = at_ist(local.date() + timedelta(days=1), h, mi)
    return when


# ------------------------------------------------------------------ understander


class RequestUnderstander:
    def __init__(self, llm: DraftLLM | None = None) -> None:
        self.llm = llm

    async def understand(
        self,
        text: str,
        *,
        prior: Understanding | None = None,
        now: datetime | None = None,
        profile_language: str | None = None,
    ) -> Understanding:
        now = now or utcnow()
        text = (text or "").strip()
        if prior is not None and prior.awaiting:
            draft = self._answer(prior.draft.model_copy(deep=True), prior.awaiting, text, now)
            return self._finish(draft, [])
        draft = self._parse(text, now)
        if profile_language and draft.language == "hinglish" and not _HINDI_WORDS.search(text):
            draft.language = profile_language
        rejected: list[str] = []
        if self.llm is not None and self._gaps(draft):
            rejected = await self._ask_llm(draft, text)
        return self._finish(draft, rejected)

    # ------------------------------------------------------------ deterministic parse
    def _parse(self, text: str, now: datetime) -> Draft:
        d = Draft(raw_text=text, language=detect_language(text))
        text = _romanise_function_words(text)
        d.scheduled_for = _parse_call_time(text, now)
        d.limits = parse_limits(text, now=now)
        if _CALLBACK.search(text):
            d.callback_of = "missed:last"
            d.purpose_kind = PurposeKind.CALLBACK
        num = _NUMBER.search(text)
        if num and (e164 := canonical(num.group(1))):
            d.number = e164
            d.callee_ref = num.group(1).strip()
        elif num and is_emergency(num.group(1)):
            d.callee_ref = num.group(1).strip()  # kept so the gate can refuse it by name
        who, rest = self._split(text)
        if GROUP_CUES.search(text) or (who and len(_split_names(who)) >= 3):
            d.callee_kind, d.kind_confident = CalleeKind.GROUP, True
            if ":" in text and GROUP_CUES.search(text):  # "sabko ... call karo: Raj, Amit, Neha"
                head, _, tail = text.partition(":")
                names = _split_names(tail)
                rest = GROUP_CUES.sub(" ", head)
            else:
                names = _split_names(who or "")
            d.group_members = [n for n in names if not GROUP_CUES.search(n)]
            d.callee_ref = d.callee_ref or (", ".join(d.group_members) or None)
            who = None
            rest = re.sub(rf"\b{_VERB_TAIL}\b", " ", rest or "", flags=re.I)
        if who:
            who = _strip_determiners(who)
            if d.callee_ref is None or d.number is None:
                d.callee_ref = d.callee_ref or who
            if d.callee_kind is None:
                kind, company, confident = _kind_of(who, rest)
                d.callee_kind, d.company, d.kind_confident = kind, company, confident
        elif d.callee_ref and d.number:
            d.callee_kind = d.callee_kind or CalleeKind.UNKNOWN
        purpose = _clean_purpose(rest) if rest else ""
        if num and purpose:
            purpose = _NUMBER.sub("", purpose).strip(" ,.-:")
        if d.callee_kind == CalleeKind.GROUP and not purpose:
            purpose = _clean_purpose(_CALLEE_PLAIN.sub(r"\g<who>", text)) if not who else ""
        d.purpose = purpose or None
        if d.callee_kind is None and d.number:
            d.callee_kind = CalleeKind.UNKNOWN  # a bare number: the most careful kind
        if d.callee_kind == CalleeKind.GROUP and d.purpose:
            d.purpose = (
                re.sub(r"\b(?:kal|aaj|parso)\b\s*\d{1,2}\s*(?:baje|am|pm)\b", "", d.purpose).strip(
                    " ,.-:"
                )
                or None
            )
        if d.purpose_kind == PurposeKind.OTHER:
            d.purpose_kind = _classify_purpose(d.purpose or text)
        if d.callee_kind in (None, CalleeKind.UNKNOWN) and d.company is None:
            kind, company, confident = _kind_of(text, purpose)
            if confident and d.callee_kind is None:
                d.callee_kind, d.company, d.kind_confident = kind, company, confident
        return d

    @staticmethod
    def _split(text: str) -> tuple[str | None, str]:
        for pat in (_CALLEE_KO, _CALLEE_EN):
            m = pat.match(text)
            if m and m.group("who").strip():
                return m.group("who"), m.group("rest")
        m = re.match(
            r"^\s*(?P<who>.+?)\s+ko\s+(?P<rest>.*\b(?:call|phone|fone)\b.*)$", text, re.I | re.S
        )
        if m:  # "Raj, Amit ko party ke liye call karo"
            rest = re.sub(rf"\b{_VERB_TAIL}\b", " ", m.group("rest"), flags=re.I)
            return m.group("who"), rest
        m = _CALLEE_SE.match(text)
        if m:
            return m.group("who"), m.group("rest")
        m = _CALLEE_PLAIN.match(text)
        if m:
            return m.group("who"), ""
        return None, text if GROUP_CUES.search(text) else ""

    # ------------------------------------------------------------ answers to a question
    def _answer(self, d: Draft, awaiting: str, text: str, now: datetime) -> Draft:
        if awaiting == "callee":
            sub = self._parse(f"{text} ko call karo", now)  # reuse callee rules on the bare answer
            d.callee_ref = sub.callee_ref or text.strip()
            d.number = sub.number or d.number
            d.callee_kind = d.callee_kind or sub.callee_kind
            d.company = d.company or sub.company
            d.kind_confident = d.kind_confident or sub.kind_confident
        elif awaiting == "purpose":
            d.purpose = _clean_purpose(text) or text.strip()
            d.purpose_kind = _classify_purpose(d.purpose)
        elif awaiting == "details":
            d.details = text.strip()
            d.limits = _merge_limits(d.limits, parse_limits(text, now=now))
        elif awaiting == "limits":
            d.limits = _merge_limits(d.limits, parse_limits(text, now=now))
            if not (d.limits.max_price_inr or d.limits.deadline):
                d.limits.time_windows = []  # answered, but no number: record "no limit stated"
                d.details = ((d.details + "; ") if d.details else "") + f"limits: {text.strip()}"
        elif awaiting == "group_members":
            d.group_members = _split_names(text)
        return d

    # ------------------------------------------------------------ missing fields
    def _gaps(self, d: Draft) -> bool:
        return not d.callee_ref or _is_vague(d.purpose) or d.callee_kind is None

    def _missing(self, d: Draft, answered: set[str]) -> list[str]:
        miss: list[str] = []
        if d.callee_kind == CalleeKind.GROUP:
            if not d.group_members:
                miss.append("group_members")
        elif not d.callee_ref and d.callback_of is None:
            miss.append("callee")
        if _is_vague(d.purpose) and d.callback_of is None:
            miss.append("purpose")
        elif (
            d.purpose_kind == PurposeKind.DISPUTE
            and not d.details
            and len(normalise(d.purpose or "").split()) <= 3
        ):
            miss.append("details")
        text = f"{d.raw_text or ''} {d.purpose or ''} {d.details or ''}"
        needs_limits = d.callee_kind in (
            CalleeKind.BUSINESS, CalleeKind.PROVIDER, CalleeKind.CUSTOMER_CARE,
        ) and d.purpose_kind in (PurposeKind.REQUEST, PurposeKind.DISPUTE)  # fmt: skip
        if (
            needs_limits
            and "limits" not in answered
            and not (d.limits.max_price_inr or d.limits.deadline)
            and not _MONEYISH.search(text)
        ):
            miss.append("limits")
        return miss

    def _finish(self, d: Draft, rejected: list[str]) -> Understanding:
        answered = {"limits"} if re.search(r"limits:", d.details or "") else set()
        missing = self._missing(d, answered)
        first = missing[0] if missing else None
        verdict = classify(d.raw_text, d.purpose, d.details)
        if d.callee_ref and is_emergency(d.callee_ref):
            verdict_key, verdict_cat = "refuse_emergency_number", "emergency_number"
        else:
            verdict_key, verdict_cat = verdict.line_key, verdict.category
        return Understanding(
            refusal_key=verdict_key,
            refusal_category=verdict_cat,
            draft=d,
            missing=missing,
            awaiting=first,
            question_key=QUESTION_FOR.get(first) if first else None,
            rejected_llm_fields=rejected,
        )

    # ------------------------------------------------------------ optional model hook
    async def _ask_llm(self, d: Draft, text: str) -> list[str]:
        assert self.llm is not None
        proposal = await self.llm.propose(
            text, prior=d.model_dump(mode="json", exclude={"raw_text"})
        )
        rejected: list[str] = []
        if not proposal:
            return rejected
        norm = normalise(text)
        for name in ("callee_ref", "company", "purpose"):
            value = proposal.get(name)
            if not value or getattr(d, name):
                continue
            if _grounded(str(value), norm):
                setattr(d, name, str(value).strip())
            else:
                rejected.append(name)
        number = proposal.get("number")
        if number and d.number is None:
            e164 = canonical(str(number))
            digits = re.sub(r"\D", "", str(number))
            if e164 and digits[-10:] in re.sub(r"\D", "", text):
                d.number = e164
            else:
                rejected.append("number")
        kind = proposal.get("callee_kind")
        if kind and d.callee_kind is None:
            try:
                d.callee_kind = CalleeKind(kind)
            except ValueError:
                rejected.append("callee_kind")
        if d.purpose and d.purpose_kind == PurposeKind.OTHER:
            d.purpose_kind = _classify_purpose(d.purpose)
        return rejected


def _grounded(value: str, normalised_text: str) -> bool:
    """Every word of ``value`` (and every digit run) must occur in the user's own message."""
    toks = [t for t in normalise(value).split() if t]
    return bool(toks) and all(t in normalised_text for t in toks)


def _merge_limits(old: Limits, new: Limits) -> Limits:
    return Limits(
        max_price_inr=new.max_price_inr or old.max_price_inr,
        deadline=new.deadline or old.deadline,
        time_windows=new.time_windows or old.time_windows,
        max_duration_s=new.max_duration_s or old.max_duration_s,
    )
