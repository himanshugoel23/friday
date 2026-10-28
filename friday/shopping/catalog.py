# ruff: noqa: E501
"""The curated category table (categories.yaml) and the matcher that maps chat text to a category."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from friday.planner import signals as sg

_FILE = Path(__file__).with_name("categories.yaml")
_OFFICE_RE = re.compile(r"\b(office|work|workplace|daftar|dafter|karyalay)\b", re.I)
_FILLER = {
    "a", "an", "the", "of", "for", "on", "in", "at", "me", "my", "to", "ka", "ki", "ke", "ko", "hai", "hain", "kya",
    "chahiye", "chaiye", "do", "dikhao", "dikha", "batao", "bata", "best", "good", "popular", "top", "check",
    "price", "prices", "rate", "rates", "cost", "daam", "dam", "bhav", "kitna", "kitne", "kitni", "mrp", "sasta",
    "cheapest", "compare", "which", "konsa", "kaun", "kaunsa", "show", "find", "need", "want", "please", "pls",
    "buy", "lena", "lana", "mangwana", "and", "or", "se", "pe", "par", "mein", "me.", "online", "brand", "brands",
    "i", "is", "are", "what", "how", "much", "kg", "g", "l", "ltr", "ml", "pack",
}  # fmt: skip


class Category(BaseModel):
    id: str
    words: list[str]
    brands: list[str] = Field(default_factory=list)
    unit: Literal["kg", "l"]
    default_pack: str
    popular: list[str]
    compare: list[str]
    weights: dict[str, float] = Field(default_factory=dict)
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.id


@lru_cache(maxsize=1)
def categories() -> dict[str, Category]:
    raw = yaml.safe_load(_FILE.read_text(encoding="utf-8")) or {}
    return {cid: Category(id=cid, **body) for cid, body in raw.items()}


def _has(low: str, term: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", low) is not None


def match(text: str) -> Category | None:
    """The category a message is about, or None. Longest matching phrase wins; a brand implies its category."""
    low = (text or "").lower()
    best: tuple[int, Category] | None = None
    for cat in categories().values():
        for term in (*cat.words, *cat.brands):
            if _has(low, term) and (best is None or len(term) > best[0]):
                best = (len(term), cat)
    return best[1] if best else None


def is_shopping_request(text: str) -> Category | None:
    """A shopping-type request: a category word with only filler around it ("atta", "5 kg atta rate",
    "price of aashirvaad atta on zepto"). Knowledge questions, explicit call requests and bare orders are not."""
    t = (text or "").strip()
    cat = match(t)
    if cat is None or len(t) > 90:
        return None
    if sg.KNOWLEDGE_RE.search(t) or sg.explicit_call_request(t):
        return None
    if sg.ORDER_RE.search(t) and not sg.PRICE_RE.search(t):
        return None
    known = {w for term in (*cat.words, *cat.brands) for w in re.findall(r"[a-z0-9]+", term.lower())}
    retailer = sg.retailer_in(t)
    retailer_words = set(re.findall(r"[a-z0-9]+", retailer)) if retailer else set()
    extra = [
        w for w in re.findall(r"[a-z]+", t.lower())
        if w not in known and w not in _FILLER and w not in retailer_words
    ]  # fmt: skip
    return cat if len(extra) <= 2 else None


def wants_office(text: str) -> bool:
    return bool(_OFFICE_RE.search(text or ""))
