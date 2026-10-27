# ruff: noqa: E501
"""Item 9: INR-only prices and refusal of USD / US-card-only routes."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from friday.chatbot.parity import copy

_US_ONLY = re.compile(
    r"\bUSD\b|\bUS\s*\$|\$\s*\d|\bdollars?\b|\bUS[- ]?(?:issued\s+)?(?:credit\s+|debit\s+)?card(?:s)?\s+only\b|"
    r"\bonly\s+(?:accepts?\s+)?US\s+cards?\b|\bUS[- ]only\s+(?:payment|card)\b|\bstripe\s+link\b|\bpaypal\s+only\b",
    re.I,
)


def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def format_inr(amount: Decimal | int | float | str) -> str:
    """Rs amount with Indian digit grouping: 1234567.5 -> '₹12,34,567.50'. Whole rupees drop paise."""
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    neg = d < 0
    d = abs(d)
    whole, paise = divmod(int(d * 100), 100)
    text = f"₹{_group_indian(whole)}" + (f".{paise:02d}" if paise else "")
    return f"-{text}" if neg else text


def is_usd_only(text: str) -> bool:
    """A price or payment route that works only in dollars or with a US card."""
    return bool(_US_ONLY.search(text or ""))


def check_route(text: str, lang: str = "hinglish") -> str | None:
    """The refusal line when ``text`` describes a USD / US-card-only route, else None."""
    return copy.line("price_usd_refused", lang) if is_usd_only(text) else None
