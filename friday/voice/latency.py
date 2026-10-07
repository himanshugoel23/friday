"""V-9: per-turn latency budget (STT -> policy -> TTS) for live calls.

The runner times the policy itself; STT finalisation and TTS time-to-first-audio come
from the leg when it exposes ``last_stt_ms`` / ``last_tts_ms`` (``TwilioCallLeg``
does); otherwise the runner's own wall-clock measurement of ``speak`` is used.
Target (US-19.5): p50 < 1.2 s per turn; the report is logged and published as a
``CallLatencyReport`` event at the end of every call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[k]


@dataclass
class TurnLatency:
    stt_ms: float = 0.0
    policy_ms: float = 0.0
    tts_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.stt_ms + self.policy_ms + self.tts_ms


@dataclass
class LatencyRecorder:
    turns: list[TurnLatency] = field(default_factory=list)
    _pending: TurnLatency | None = None

    def stt(self, ms: float | None) -> None:
        self._current().stt_ms = ms or 0.0

    def policy(self, ms: float) -> None:
        self._current().policy_ms = ms

    def tts(self, ms: float | None) -> None:
        cur = self._current()
        cur.tts_ms = ms or 0.0
        self.close()

    def close(self) -> None:
        if self._pending is not None and self._pending.policy_ms:
            self.turns.append(self._pending)
        self._pending = None

    def _current(self) -> TurnLatency:
        if self._pending is None:
            self._pending = TurnLatency()
        return self._pending

    def summary(self) -> dict[str, float]:
        self.close()
        totals = [t.total_ms for t in self.turns]
        return {
            "turns": float(len(self.turns)),
            "p50_ms": percentile(totals, 50),
            "p95_ms": percentile(totals, 95),
            "max_ms": max(totals) if totals else 0.0,
            "policy_p95_ms": percentile([t.policy_ms for t in self.turns], 95),
            "stt_p95_ms": percentile([t.stt_ms for t in self.turns], 95),
            "tts_p95_ms": percentile([t.tts_ms for t in self.turns], 95),
        }
