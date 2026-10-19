"""Money helpers for the savings engine. Everything is integer paise; no floats anywhere.

``rate_bp`` is a rate in basis points (500 = 5%). Rounding is half-up to the paise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

PAISE_PER_RUPEE = 100
BP_DENOM = 10_000


def pct_of(amount_paise: int, rate_bp: int) -> int:
    """``amount * rate_bp / 10000`` rounded half-up to the paise (integers only)."""
    if amount_paise < 0 or rate_bp < 0:
        raise ValueError("amount and rate must be >= 0")
    return (amount_paise * rate_bp * 2 + BP_DENOM) // (BP_DENOM * 2)


def _indian_group(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def format_rs(paise: int) -> str:
    """``Rs 1,24,000`` or ``Rs 32.50`` (paise shown only when not a whole rupee)."""
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    rupees, rem = divmod(paise, PAISE_PER_RUPEE)
    out = f"Rs {_indian_group(rupees)}"
    if rem:
        out += f".{rem:02d}"
    return sign + out


def format_rate(rate_bp: int) -> str:
    """500 -> '5', 150 -> '1.5', 125 -> '1.25'."""
    whole, frac = divmod(rate_bp, 100)
    if not frac:
        return str(whole)
    return f"{whole}.{frac:02d}".rstrip("0")


# ------------------------------------------------------------------ amounts in free text

_MULT = {
    "k": 1000,
    "thousand": 1000,
    "hazaar": 1000,
    "hazar": 1000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "crore": 10_000_000,
    "cr": 10_000_000,
}
_CUR = r"(?:rs\.?|inr|₹|rupees?|rupaye|rupaiye)"
_AMOUNT_RE = re.compile(
    rf"(?P<pre>{_CUR}\s*)?(?<![\w.])(?P<num>\d[\d,]*(?:\.\d{{1,2}})?)"
    rf"(?:\s*(?P<mult>k|thousand|hazaar|hazar|lakhs?|lac|crore|cr)\b)?"
    rf"(?P<post>\s*{_CUR})?",
    re.IGNORECASE,
)
_NOT_MONEY_AFTER = re.compile(
    r"^\s*(%|percent|kg|kgs|g\b|gm|ltr|litre|liter|l\b|km|gb|mb|ml|st\b|nd\b|rd\b|th\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AmountHit:
    paise: int
    marked: bool  # had an explicit currency word or symbol next to it
    start: int
    end: int


def find_amounts(text: str, *, max_digits: int = 9) -> list[AmountHit]:
    """All plausible money amounts in ``text`` as integer paise (deterministic, no model)."""
    hits: list[AmountHit] = []
    for m in _AMOUNT_RE.finditer(text):
        digits = m.group("num").replace(",", "")
        if len(digits.split(".")[0]) > max_digits:
            continue  # phone / account numbers are not amounts
        if not m.group("mult") and _NOT_MONEY_AFTER.match(text[m.end("num") : m.end("num") + 12]):
            continue
        value = Decimal(digits) * _MULT.get((m.group("mult") or "").lower(), 1)
        marked = bool(m.group("pre")) or bool(m.group("post"))
        hits.append(
            AmountHit(
                paise=int(value * PAISE_PER_RUPEE), marked=marked, start=m.start(), end=m.end()
            )
        )
    return hits
