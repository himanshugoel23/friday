"""Read the state of a live call from its transcript (the policy is stateless:
everything it knows comes from the brief + transcript + answers)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from friday.core.clock import to_ist, utcnow
from friday.core.models import CallBrief, CallTurn, Language, Speaker, Transcript, UserAnswer

from ..lang import detect_language
from ..textutil import (
    extract_amounts,
    has_any,
    norm,
    parse_dates,
    parse_time_of_day,
    sentences,
)

# ------------------------------------------------------------------ callee signals

IVR_WORDS = (
    "press",
    "dabaye",
    "dabayein",
    "dabaiye",
    "enter your",
    "enter the",
    "followed by",
    "hash key",
    "star key",
    "to repeat",
    "main menu",
    "for english",
    "for hindi",
    "hindi ke liye",
    "english ke liye",
    "ke liye 1",
    "ke liye 2",
    "#",
)
HOLD_WORDS = (
    "please hold",
    "please stay on the line",
    "your call is important",
    "all our executives are busy",
    "all our agents are busy",
    "wait time",
    "estimated wait",
    "you are in queue",
    "in the queue",
    "hold music",
    "♪",
    "kripya line par bane rahe",
    "line par bane rahiye",
    "intezaar karein",
    "please wait while",
    "call will be answered",
    "next available",
)
AI_QUESTION = (
    "are you a robot",
    "are you robot",
    "are you an ai",
    "are you ai",
    "is this a bot",
    "are you a bot",
    "robot ho",
    "robot hai",
    "machine ho",
    "ai ho",
    "real person",
    "insaan ho",
    "human ho",
    "are you human",
    "computer ho",
    "bot ho",
    "recorded",
    "aap ai",
    "kya aap ai",
    "are you a machine",
)
HOSTILE_AI = (
    "robot se baat nahi",
    "don't talk to robots",
    "dont talk to robots",
    "no robots",
    "no bots",
    "machine se baat nahi",
    "don't talk to ai",
    "dont talk to ai",
    "not talking to a robot",
    "robot se nahi",
    "ai se baat nahi",
    "real person se baat",
    "insaan se baat karao",
    "human please",
)
DO_NOT_CALL = (
    "don't call again",
    "dont call again",
    "do not call",
    "never call",
    "dobara call mat",
    "phir se call mat",
    "call mat karna",
    "stop calling",
)
WRONG_NUMBER = ("wrong number", "galat number", "wrong no", "no such", "yeh woh nahi")
CALL_LATER = (
    "call later",
    "call back later",
    "call after",
    "baad mein call",
    "baad me call",
    "thodi der baad",
    "busy hoon",
    "busy hai abhi",
    "abhi busy",
    "call tomorrow",
    "kal call",
    "call in an hour",
    "ghante baad",
    "please call after",
    "we are prepping",
    "phir call karna",
    "later please",
    "after some time",
    "thodi der mein call",
)
WAIT_WORDS = (
    "ek minute",
    "one minute",
    "one moment",
    "hold on",
    "ruko",
    "rukiye",
    "wait",
    "hold karo",
    "hold kariye",
    "let me check",
    "check karke",
    "dekh ke batata",
    "dekhta hoon",
    "dekhti hoon",
    "just a sec",
    "ek second",
    "do minute",
)
VERIFY_WORDS = (
    "otp",
    "one time password",
    "verification code",
    "verify",
    "account holder",
    "date of birth",
    "mother's maiden",
    "security question",
    "cvv",
    "pin number",
    "your pin",
    "atm pin",
    "password",
)
PAYMENT_WORDS = (
    "advance",
    "deposit",
    "token amount",
    "pay now",
    "payment karna",
    "payment kar",
    "upi",
    "gpay",
    "phonepe",
    "paytm",
    "transfer kar",
    "booking amount",
    "prepay",
    "pehle payment",
    "50%",
    "half payment",
    "advance dena",
)
NEGATIVE_AVAIL = (
    "full",
    "not available",
    "no slot",
    "no slots",
    "booked",
    "khatam",
    "nahi hai",
    "nahin hai",
    "out of stock",
    "unavailable",
    "closed",
    "band hai",
    "not possible",
    "nahi ho payega",
    "nahi milega",
    "can't",
    "cannot",
    "sorry",
    "illa",
    "nahi",
)
POSITIVE_WORDS = (
    "haan",
    "han",
    "yes",
    "ji",
    "available",
    "hai",
    "done",
    "ho jayega",
    "kar denge",
    "sure",
    "ok",
    "okay",
    "theek",
    "confirmed",
    "booked",
    "pakka",
    "ho gaya",
    "sahi hai",
    "correct",
    "right",
    "chalega",
    "milega",
    "in stock",
    "we have",
    "rakh dete",
    "rakh deta",
    "rakh denge",
    "hold kar",
    "sari",
    "houdu",
    "hoy",
    "aamaa",
)
CANT_RESOLVE = (
    "not possible",
    "cannot",
    "can't",
    "nahi ho sakta",
    "authority",
    "only up to",
    "sirf",
    "only",
    "policy nahi",
    "not allowed",
    "unable",
)
DISTRESS = (
    "dizzy",
    "chakkar",
    "fell",
    "fall",
    "gir gaya",
    "gir gayi",
    "gir gaye",
    "chest pain",
    "seene mein dard",
    "seene me dard",
    "breathless",
    "saans",
    "can't breathe",
    "confused",
    "yaad nahi",
    "behosh",
    "unconscious",
    "bleeding",
    "khoon",
    "ulti",
    "vomit",
    "bahut dard",
    "severe pain",
    "tabiyat kharab",
    "bimar",
    "fever",
    "bukhar",
    "not well",
    "unwell",
    "theek nahi",
)
MED_SKIPPED = (
    "dawai nahi li",
    "dawa nahi li",
    "medicine nahi li",
    "didn't take",
    "did not take",
    "bhool gaya",
    "bhool gayi",
    "forgot my medicine",
    "nahi li",
    "skip",
)

_SLOT = re.compile(
    r"(?:(?P<day>today|tomorrow|kal|aaj|parso|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
    r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\s+)?"
    r"(?:(?P<part>subah|shaam|sham|morning|evening|afternoon|dopahar|raat)\s+)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?(?:\s*(?:baje|bje|o'?clock))?",
    re.I,
)


def _slot_strings(sentence: str) -> list[str]:
    out: list[str] = []
    s = norm(sentence)
    for m in _SLOT.finditer(s):
        h = int(m.group("h"))
        mm = m.group("m")
        if h > 23 or h == 0:
            continue
        before = s[max(0, m.start() - 2) : m.start()]
        after = s[m.end() : m.end() + 10]
        if "₹" in before or re.match(
            r"\s*(rs|₹|rupe|min|minute|hour|ghant|din|day|week|%|"
            r"people|log|x|strip|\d)",
            after,
        ):
            continue
        if re.match(
            r"\s*(?:st|nd|rd|th)?\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
            r"dec)",
            after,
        ):
            continue
        if not (
            m.group("ap")
            or mm
            or m.group("day")
            or m.group("part")
            or re.match(r"\s*(baje|bje|o'?clock)", s[m.end() - 6 : m.end() + 6])
            or re.search(
                r"\b(ya|or|aur|slot|at|baje|free|available|hai|ka|ke|wala)\b",
                s[max(0, m.start() - 12) : m.end() + 12],
            )
        ):
            continue
        start, _e, _x = parse_time_of_day(
            m.group(0) if (m.group("ap") or m.group("part")) else m.group(0) + " baje"
        )
        if start is None:
            continue
        hh, mi = divmod(start, 60)
        label = f"{hh % 12 or 12}{':' + f'{mi:02d}' if mi else ''} {'AM' if hh < 12 else 'PM'}"
        day = (m.group("day") or "").lower()
        if day:
            named = {
                "today": "Today",
                "aaj": "Today",
                "tomorrow": "Tomorrow",
                "kal": "Tomorrow",
                "parso": "Day after",
            }.get(day, day[:3].title())
            label = f"{named} {label}"
        if label not in out:
            out.append(label)
    return out


@dataclass
class CallState:
    brief: CallBrief
    transcript: Transcript
    answers: list[UserAnswer]
    friday: list[CallTurn] = field(default_factory=list)  # policy turns (no disclosure)
    callee: list[CallTurn] = field(default_factory=list)
    system: list[CallTurn] = field(default_factory=list)
    last: CallTurn | None = None  # last non-FRIDAY turn
    last_callee: CallTurn | None = None
    callee_lang: Language | None = None
    slots: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    prices: list[int] = field(default_factory=list)
    original_price: int | None = None
    price: int | None = None
    extras: list[str] = field(default_factory=list)
    inclusions: list[str] = field(default_factory=list)
    started: datetime = field(default_factory=utcnow)

    # ---------------------------------------------------------------- helpers
    def friday_said(self, *words: str) -> bool:
        return any(has_any(norm(t.text), words) for t in self.friday)

    def friday_count(self, *words: str) -> int:
        return sum(1 for t in self.friday if has_any(norm(t.text), words))

    def friday_has(self, *fragments: str) -> bool:
        """Plain substring check (for question fragments that may end mid-word)."""
        frs = [norm(f) for f in fragments if f]
        return any(any(f in norm(t.text) for f in frs) for t in self.friday)

    def after_friday_has(self, *fragments: str) -> str:
        frs = [norm(f) for f in fragments if f]
        return self._after(lambda txt: any(f in txt for f in frs))

    def callee_text(self) -> str:
        return " ".join(t.text for t in self.callee)

    def last_text(self) -> str:
        return norm(self.last_callee.text) if self.last_callee else ""

    def callee_after_last_friday(self) -> list[CallTurn]:
        out: list[CallTurn] = []
        for t in reversed(self.transcript.turns):
            if t.speaker == Speaker.FRIDAY and not _is_disclosure(t.text, self.brief):
                break
            if t.speaker == Speaker.CALLEE:
                out.insert(0, t)
        return out

    def reply_text(self) -> str:
        """What the callee said since Friday last spoke."""
        return norm(" ".join(t.text for t in self.callee_after_last_friday()))

    def after_friday_said(self, *words: str) -> str:
        """Callee text right after the LAST Friday turn containing any of ``words``."""
        return self._after(lambda txt: has_any(txt, words))

    def _after(self, match) -> str:
        idx = None
        for i, t in enumerate(self.transcript.turns):
            if t.speaker == Speaker.FRIDAY and match(norm(t.text)):
                idx = i
        if idx is None:
            return ""
        out = []
        for t in self.transcript.turns[idx + 1 :]:
            if t.speaker == Speaker.FRIDAY:
                break
            if t.speaker == Speaker.CALLEE:
                out.append(t.text)
        return norm(" ".join(out))

    def approved_answer(self) -> UserAnswer | None:
        return next((a for a in reversed(self.answers) if a.approves), None)


def _is_disclosure(text: str, brief: CallBrief) -> bool:
    t = norm(text)
    if any(
        norm(brief.disclosure(lang)) == t for lang in (Language.EN, Language.HI, Language.HINGLISH)
    ):
        return True
    return (
        ("ai assistant" in t or "एआई" in t or "ai असिस्टेंट" in t)
        and ("on behalf of" in t or "ki taraf se" in t or "की ओर से" in t)
        and len(t) < 160
        and "?" not in t
    )


def normalize_transcript(transcript: Transcript) -> Transcript:
    """Fold ``CallTurn.audio_class`` (core field) into the runner's text-prefix convention
    (``[ivr_prompt] ...``) so both representations are read the same way."""
    turns = []
    changed = False
    for t in transcript.turns:
        cls = getattr(t, "audio_class", None)
        val = getattr(cls, "value", cls)
        if t.speaker == Speaker.CALLEE and val and val != "human" and audio_tag(t.text) is None:
            t = t.model_copy(update={"text": f"[{val}] {t.text}".strip()})
            changed = True
        turns.append(t)
    return Transcript(turns=turns) if changed else transcript


def read_state(brief: CallBrief, transcript: Transcript, answers: list[UserAnswer]) -> CallState:
    transcript = normalize_transcript(transcript)
    st = CallState(brief=brief, transcript=transcript, answers=list(answers))
    if transcript.turns:
        st.started = transcript.turns[0].at
    for turn in transcript.turns:
        if turn.speaker == Speaker.FRIDAY:
            if not _is_disclosure(turn.text, brief):
                st.friday.append(turn)
            continue
        st.last = turn
        if turn.speaker == Speaker.SYSTEM:
            st.system.append(turn)
            continue
        st.callee.append(turn)
        st.last_callee = turn
    if st.last_callee is not None:
        st.callee_lang = st.last_callee.language or detect_language(
            st.last_callee.text, brief.opening_language
        )
    # offers & prices from callee speech
    negotiated_after = False
    for turn in transcript.turns:
        if turn.speaker == Speaker.FRIDAY:
            if has_any(
                norm(turn.text),
                (
                    "discount",
                    "best price",
                    "kam kar",
                    "could you do",
                    "kar sakte hain kya",
                    "can you do",
                ),
            ):
                negotiated_after = True
            continue
        if turn.speaker != Speaker.CALLEE or is_ivr(turn.text) or is_hold(turn.text):
            continue
        for sent in sentences(turn.text) or [turn.text]:
            s = norm(sent)
            neg = has_any(s, NEGATIVE_AVAIL) and not has_any(
                s, ("ya", "or", "but", "lekin", "aadre", "instead")
            )
            for slot in _slot_strings(sent):
                if neg:
                    if slot not in st.unavailable:
                        st.unavailable.append(slot)
                elif slot not in st.slots:
                    st.slots.append(slot)
            for amt in extract_amounts(sent):
                st.prices.append(amt)
                if st.original_price is None:
                    st.original_price = amt
                    st.price = amt
                elif negotiated_after and st.price is not None and amt < st.price:
                    st.price = amt
                elif amt > (st.price or 0) or has_any(
                    s, ("extra", "alag", "separately", "additional", "se start", "plus")
                ):
                    st.extras.append(sent.strip())
            if (
                has_any(
                    s,
                    (
                        "include",
                        "included",
                        "including",
                        "saath mein",
                        "ke saath",
                        "free",
                        "waived",
                        "nahi lagega",
                        "breakfast",
                    ),
                )
                and not neg
            ):
                st.inclusions.append(sent.strip())
    st.slots = [s for s in st.slots if s not in st.unavailable] or st.slots
    return st


_TAG = re.compile(
    r"^\s*\[(ivr_prompt|queue_announcement|hold_music|voicemail|silence|human)\]\s*", re.I
)
IDENTIFIER_PROMPT = (
    r"enter your|enter the|registered mobile|account number|customer id|"
    r"consumer number|order id|policy number|type your"
)


def audio_tag(text: str) -> str | None:
    """Voice runner prefixes non-human CALLEE chunks: [ivr_prompt], [hold_music]..."""
    m = _TAG.match(text or "")
    return m.group(1).lower() if m else None


def strip_tag(text: str) -> str:
    return _TAG.sub("", text or "")


def affirmative(text: str) -> bool:
    t = norm(text)
    if not t or has_any(t, ("nahi", "no", "not", "can't", "cannot", "sorry", "nahin")):
        return False
    return has_any(t, POSITIVE_WORDS)


def is_ivr(text: str) -> bool:
    tag = audio_tag(text)
    if tag is not None:
        return tag == "ivr_prompt"
    t = norm(text)
    return bool(re.search(r"\b(press|dial|dabaye\w*|enter)\s*\d|\b\d\s*(dabaye|press)", t)) or (
        has_any(t, IVR_WORDS) and has_any(t, ("press", "dabaye", "enter", "dabaiye", "dabayein"))
    )


def is_hold(text: str) -> bool:
    tag = audio_tag(text)
    if tag is not None:
        return tag in ("hold_music", "queue_announcement")
    t = norm(text)
    return has_any(t, HOLD_WORDS) or t in ("", "♪", "(hold music)", "[hold music]")


def ivr_options(text: str) -> list[tuple[str, str]]:
    """[(key, label)] from 'For prepaid press 1, for broadband press 3' / 'press 9 to repeat'
    / 'broadband ke liye 3 dabaye'."""
    t = norm(text)
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(?:for|to)\s+([^,.;]+?)\s*,?\s*(?:please\s+)?press\s+([0-9*#])", t):
        out.append((m.group(2), m.group(1)))
    for m in re.finditer(r"press\s+([0-9*#])\s+(?:for|to)\s+([^,.;]+)", t):
        out.append((m.group(1), m.group(2)))
    for m in re.finditer(r"([^,.;]+?)\s+ke liye\s+([0-9*#])\s*(?:dabaye\w*|press)", t):
        out.append((m.group(2), m.group(1)))
    for m in re.finditer(r"press\s+(star|hash)\s+(?:for|to)\s+([^,.;]+)", t):
        out.append(("*" if m.group(1) == "star" else "#", m.group(2)))
    for m in re.finditer(r"(?:to|for)\s+([^,.;]+?)\s*,?\s*press\s+(star|hash)", t):
        out.append(("*" if m.group(2) == "star" else "#", m.group(1)))
    seen: set[str] = set()
    uniq = []
    for k, lbl in out:
        if k not in seen:
            seen.add(k)
            uniq.append((k, lbl.strip()))
    return uniq


def wait_minutes(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:minutes?|mins?|minute)", norm(text))
    return int(m.group(1)) if m else None


TICKET = re.compile(
    r"(?:ticket|complaint|reference|request|sr|docket|case|token)\s*(?:number|no\.?|id|#)?\s*"
    r"(?:is|hai|:)?\s*([a-z]{0,4}[- ]?\d[\d\- ]{2,}\d|[a-z]{1,4}\d{3,})",
    re.I,
)
AGENT = re.compile(
    r"(?:my name is|this is|main|mera naam|se)\s+([A-Z][a-z]+)\s*"
    r"(?:bol rahi|bol raha|speaking|here|hai|hoon|from|,)",
    re.I,
)


def find_ticket(text: str) -> str | None:
    m = TICKET.search(text or "")
    if not m:
        return None
    val = re.sub(r"\s+", "", m.group(1)).upper()
    return val if re.search(r"\d", val) else None


def find_agent(text: str) -> str | None:
    m = AGENT.search(text or "")
    if m and m.group(1).lower() not in {
        "airtel",
        "main",
        "aapki",
        "aapka",
        "friday",
        "sir",
        "madam",
        "ma'am",
        "ji",
    }:
        return m.group(1).title()
    return None


def find_promise(text: str, now: datetime) -> tuple[date | None, str | None]:
    t = norm(text)
    m = re.search(
        r"(?:within|in|agle)\s+(\d{1,3})\s*(hours?|hrs?|ghante|days?|din|working days)", t
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n / 24 if unit.startswith(("hour", "hr", "ghant")) else n
        return (to_ist(now) + timedelta(days=max(1, round(days + 0.49)))).date(), m.group(0)
    if has_any(t, ("by", "tak", "until", "before")):
        dates = parse_dates(text, now)
        if dates:
            return dates[0], f"by {dates[0]:%d %b}"
    return None, None
