"""Slot reading (rules first), language detection, yes/no and cancel detection, question writer.

``SlotExtractor`` is a Protocol: the rule-based one here is the offline baseline; an LLM extractor
(closed JSON schema, output validated by ``clean_slots``) can implement the same Protocol.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from .plans import slot_kind
from .taxonomy import categories

SLOT_KEYS = ["where", "service", "when", "budget", "for_whom", "delegation", "details"]

_HINGLISH = set(
    ["hai", "hain", "kya", "kitna", "kitne", "karo", "kar", "do", "chahiye", "chahie", "mujhe", "mera", "meri", "mere", "aaj", "kal", "parso", "shaam", "subah", "mein", "me", "ke", "ki", "ka", "liye", "batao", "bata", "dijiye", "nahi", "haan", "ji", "theek", "aur", "ya", "se", "tak", "wala", "wale", "ghar", "kab", "abhi", "lega", "lagega", "milega", "sakte", "sakta"]
)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def detect_language(text: str) -> str:
    """en | hinglish | hi (Devanagari). Replies for hi use the Hinglish wording."""
    if _DEVANAGARI.search(text):
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    if sum(w in _HINGLISH for w in words) >= 2:
        return "hinglish"
    return "en"


_YES = re.compile(r"\b(yes|yeah|yep|y|ok|okay|sure|go ahead|haan|han|ha|haa|ji haan|theek hai|"
                  r"thik hai|kar do|karo|kardo|kar dijiye|bilkul|done|proceed|please do)\b|हाँ|हां|ठीक")
_NO = re.compile(r"\b(no|nope|nahi|nahin|na|mat|don't|dont|do not|not now|rehne do|"
                 r"cancel|stop)\b|नहीं|मत")
_CANCEL = re.compile(r"\b(cancel|rehne do|rehne de|mat karo|chhod do|chod do|band karo|stop|"
                     r"nahi chahiye|forget it|never ?mind|ignore this|drop it)\b|रहने दो|कैंसल")


def parse_yes_no(text: str) -> bool | None:
    low = text.lower().strip()
    yes, no = bool(_YES.search(low)), bool(_NO.search(low))
    if yes == no:
        return None
    return yes


def is_cancel(text: str) -> bool:
    return bool(_CANCEL.search(text.lower())) and len(text.split()) <= 8


_WHEN = re.compile(
    r"\b(today|tonight|tomorrow|day after tomorrow|aaj|kal|parso|abhi|now|asap|shaam|evening|"
    r"morning|subah|dopahar|afternoon|raat|night|weekend|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|somvar|mangalvar|budhvar|guruvar|shukravar|shanivar|ravivar|"
    r"next week|this week|\d{1,2}(?::\d{2})?\s*(?:baje|am|pm)|\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b", re.I)
_BUDGET = [
    re.compile(r"(?:max(?:imum)?|under|budget|within|upto|up to|below|less than|tak|se kam)\s*"
               r"(?:of\s*)?(?:rs\.?|inr|₹)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.I),
    re.compile(r"(?:rs\.?|inr|₹)\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\b(?!\s*(?:km|sq))", re.I),
    re.compile(r"\b(\d[\d,]*)\s*(k)?\s*(?:rs|rupees|rupaye|ke andar|tak|se kam)\b", re.I),
]
_FOR_WHOM = re.compile(
    r"\b(?:for|ke liye|ki|ka)\s+(?:my\s+|meri\s+|mere\s+|apni\s+|apne\s+)?"
    r"(mummy|mom|mother|maa|papa|dad|father|wife|biwi|husband|pati|bhai|brother|behen|sister|"
    r"friend|dost|son|daughter|beta|beti|kid|child|parents|bhabhi|boss)\b", re.I)
_FOR_WHOM_REV = re.compile(
    r"\b(mummy|mom|mother|maa|papa|dad|father|wife|biwi|husband|pati|bhai|brother|behen|sister|"
    r"parents|bhabhi)\s+(?:ke liye|ki|ka|ke)\b", re.I)
_DELEGATE_YES = re.compile(r"\b(book kar do|book kardo|book karo|book kr do|book it|please book|"
                           r"book a|book me|book my|reserve|fix kar do|book kar dijiye)\b", re.I)
_DELEGATE_NO = re.compile(r"\b(sirf|bas|only|just)\s+(price|rate|quote|availability|pooch|puch)", re.I)
_WHERE_TRAIL = re.compile(r"((?:[\w\-]+\s+){0,3}[\w\-]+)\s+(?:mein|me|ke paas|ke pass|ke aaspaas|"
                          r"ke aas paas|near)\b", re.I)
_WHERE_LEAD = re.compile(r"\b(?:in|near|around|at|nearby)\s+((?:[\w\-]+\s*){1,4})", re.I)
_SECTOR = re.compile(r"\b(sector\s*\d+[a-z]?(?:\s+[a-z]+)?)", re.I)
_STOP = set(["in", "at", "on", "ka", "ki", "ke", "mein", "hum", "mujhe", "mera", "meri", "mere", "kal", "aaj", "parso", "shaam", "subah", "raat", "today", "tomorrow", "tonight", "the", "a", "an", "is", "kya", "kitna", "kitne", "lega", "lagega", "hai", "hain", "for", "and", "aur", "ya", "to", "please", "need", "want", "chahiye", "book", "kar", "do", "karo", "koi", "achha", "good", "best", "my", "me", "i", "we", "you", "can", "could", "would", "nearby", "near", "ke", "paas", "se", "tak", "abhi", "ghar", "haan", "ji", "ok", "ek", "do", "teen", "char", "paanch", "cost", "price", "rate", "fee", "fees", "much", "how", "does", "what", "salon", "saloon", "parlour", "doctor", "dentist", "clinic", "gym", "vet", "plumber", "electrician", "restaurant", "table", "haircut", "beard", "facial", "service", "repair", "dj", "cab", "tailor", "flowers", "lab", "test"])
_TIMEISH = re.compile(r"^\d")


def _money(num: str, k: str | None) -> int | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    return int(v * 1000) if k else int(v)


def _where(text: str) -> str | None:
    m = _SECTOR.search(text)
    if m:
        extra = re.sub(r"\s+", " ", m.group(1)).strip()
        return extra.title()
    for rx in (_WHERE_TRAIL, _WHERE_LEAD):
        for m in rx.finditer(text):
            toks = [t for t in re.findall(r"[\w\-]+", m.group(1))
                    if t.lower() not in _STOP and not _TIMEISH.match(t)]
            if toks:
                return " ".join(toks).title()
    return None


@runtime_checkable
class SlotExtractor(Protocol):
    async def extract(self, text: str, category: str | None) -> dict[str, Any]: ...


class RuleSlotExtractor:
    """Conservative: only fills a slot when a pattern clearly matches; never guesses."""

    async def extract(self, text: str, category: str | None) -> dict[str, Any]:
        return self.extract_sync(text, category)

    def extract_sync(self, text: str, category: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        low = text.lower()
        when = [m.group(0) for m in _WHEN.finditer(low)]
        if when:
            out["when"] = " ".join(dict.fromkeys(when))
        for rx in _BUDGET:
            m = rx.search(low)
            if m and (b := _money(m.group(1), m.group(2))) is not None:
                out["budget"] = b
                break
        if (m := _FOR_WHOM.search(low) or _FOR_WHOM_REV.search(low)):
            out["for_whom"] = m.group(1).lower()
        if _DELEGATE_NO.search(low):
            out["delegation"] = False
        elif _DELEGATE_YES.search(low):
            out["delegation"] = True
        if (w := _where(text)):
            out["where"] = w
        if category:
            hits = [kw for kw in categories()[category].keywords
                    if re.search(rf"(?<![\w]){re.escape(kw)}(?![\w])", low)]
            if hits:
                out["service"] = ", ".join(dict.fromkeys(hits[:3]))
        return clean_slots(out)


def clean_slots(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate any extractor output (rule or LLM): known keys, right types, non-empty."""
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in SLOT_KEYS or v is None:
            continue
        kind = slot_kind(k)
        if kind == "money":
            if isinstance(v, bool) or not isinstance(v, int | float) or v <= 0 or v > 10_000_000:
                continue
            out[k] = int(v)
        elif kind == "yesno":
            if isinstance(v, bool):
                out[k] = v
        elif isinstance(v, str) and v.strip():
            out[k] = v.strip()[:200]
    return out


def parse_answer(slot: str, text: str) -> Any | None:
    """Read a free-text reply as the value for the slot that was just asked."""
    kind = slot_kind(slot)
    t = text.strip()
    if not t:
        return None
    if kind == "yesno":
        yn = parse_yes_no(t)
        if yn is None and slot == "delegation":
            low = t.lower()
            yn = False if _DELEGATE_NO.search(low) else True if _DELEGATE_YES.search(low) else None
        return yn
    if kind == "money":
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", t.lower())
        if m:
            return _money(m.group(1), m.group(2))
        return None
    if slot == "where":
        return _where(t) or t[:120]
    return t[:200]


# ------------------------------------------------------------------------------ question writer


class QuestionWriter(Protocol):
    async def write(self, slot: str, template_text: str, language: str) -> str: ...


class TemplateWriter:
    async def write(self, slot: str, template_text: str, language: str) -> str:
        return template_text


class GuardedRewriter:
    """Optional LLM rewrite of a template question. ``rewrite`` is any async callable; its output
    is accepted only if it is short, has the same numbers/links as the template (no invented
    facts) and still asks something; otherwise the template text is used."""

    def __init__(self, rewrite: Callable[[str, str], Awaitable[str]]) -> None:
        self.rewrite = rewrite

    async def write(self, slot: str, template_text: str, language: str) -> str:
        try:
            new = (await self.rewrite(template_text, language)).strip()
        except Exception:  # noqa: BLE001 - any LLM failure falls back to the template
            return template_text
        if not new or len(new) > 240 or "?" not in new or "\n" in new:
            return template_text
        if re.findall(r"\d+", new) != re.findall(r"\d+", template_text):
            return template_text
        if re.search(r"https?://|www\.|@", new):
            return template_text
        return new
