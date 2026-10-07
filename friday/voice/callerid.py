"""Sticky caller-ID (BRIEF E30): the same Friday number calls the same business, so
call-backs route back to call memory reliably.

Resolution order when placing a call (all providers):
  1. ``OutboundCallRequest.metadata["from_number"]`` - set by the runner from
     ``run(..., from_number=...)`` / ``CallBrief.from_number`` (proposed core field).
     The Backend owns the business -> Friday-number mapping (call memory).
  2. ``provider.caller_id_selector(to_phone, request)`` if the Backend installed one.
  3. Deterministic hash of the destination over the number pool (sticky with no
     storage at all), pool = ``Settings.friday_numbers`` (proposed) or the provider's
     single configured from-number.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from friday.core.models import OutboundCallRequest

CallerIdSelector = Callable[[str, OutboundCallRequest], "str | None"]

SIM_FRIDAY_NUMBERS: tuple[str, ...] = ("+918069110001", "+918069110002", "+918069110003")


def sticky_pick(to_phone: str, pool: Sequence[str]) -> str | None:
    if not pool:
        return None
    h = int(hashlib.sha256(to_phone.encode()).hexdigest(), 16)
    return pool[h % len(pool)]


def choose_from_number(
    request: OutboundCallRequest,
    pool: Sequence[str],
    selector: CallerIdSelector | None = None,
) -> str | None:
    explicit = request.metadata.get("from_number") or getattr(request, "from_number", None)
    if explicit:
        return explicit
    if selector is not None:
        picked = selector(request.to_phone, request)
        if picked:
            return picked
    return sticky_pick(request.to_phone, pool)


def number_pool(settings: object, fallback: Sequence[str | None] = ()) -> list[str]:
    pool = list(getattr(settings, "friday_numbers", None) or [])
    return pool or [n for n in fallback if n]
