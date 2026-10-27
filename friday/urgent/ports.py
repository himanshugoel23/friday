# ruff: noqa: E501
"""The one outbound port of the escalation: ring the user's OWN number and say one fixed line.

``OwnNumberCaller`` is implemented by ``telephony.TelephonyOwnNumberCaller`` (real, refuses while the
spoken line is PENDING approval) and by ``FakeOwnNumberCaller`` (tests and the simulator; dials nothing).
The caller never decides WHETHER to ring; ``service.py`` does, after the CallGate and every rule. The
port only has to be idempotent on ``dedupe_key`` where it can (the fake is).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from friday.urgent.models import RingOutcome, RingResult


@runtime_checkable
class OwnNumberCaller(Protocol):
    async def ring(
        self, *, user_id: str, number: str, line_key: str, lang: str, user_name: str, dedupe_key: str
    ) -> RingOutcome: ...


@dataclass
class RingRecord:
    user_id: str
    number: str = field(repr=False)
    line_key: str
    lang: str
    dedupe_key: str


class FakeOwnNumberCaller:
    """Scripted: ``results`` are consumed in order, the last repeats (default NO_ANSWER). The same
    ``dedupe_key`` returns the first outcome again and records nothing (a replayed dial is a no-op).
    ``hook`` runs before each real (non-replayed) ring: tests use it to tap Acknowledge mid-call or to
    raise (a crash while ringing)."""

    def __init__(self, *results: RingResult, hook: Callable[[RingRecord], None] | None = None) -> None:
        self.results = list(results) or [RingResult.NO_ANSWER]
        self.calls: list[RingRecord] = []
        self.seen: dict[str, RingOutcome] = {}
        self.hook = hook

    async def ring(
        self, *, user_id: str, number: str, line_key: str, lang: str, user_name: str, dedupe_key: str
    ) -> RingOutcome:
        if dedupe_key in self.seen:
            return self.seen[dedupe_key]
        rec = RingRecord(user_id, number, line_key, lang, dedupe_key)
        if self.hook is not None:
            self.hook(rec)
        self.calls.append(rec)
        res = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        out = RingOutcome(result=res, detail="fake")
        self.seen[dedupe_key] = out
        return out
