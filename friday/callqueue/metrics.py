"""In-process counters and PII-safe log text for the call queue (never a full phone number)."""

from __future__ import annotations

from collections import Counter

counters: Counter[str] = Counter()


def inc(name: str, n: int = 1) -> None:
    counters[name] += n


def snapshot() -> dict[str, int]:
    return dict(counters)


def reset() -> None:
    counters.clear()


def tail2(number: str | None) -> str:
    """'+919876543210' -> '******10' (only the last two digits)."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return "******" + digits[-2:] if digits else "<none>"
