"""TTS provider health: last-error memory + circuit breaker with exponential backoff.

Incident 2026-10-28: Sarvam ran out of credits (HTTP 402) and answered 429 under load; the
pre-render retried about once a second and calls were cut the moment the callee answered.

* ``record_error`` classifies a failure: ``quota`` (402 / insufficient credits) opens the
  breaker at once; ``rate`` (429) and ``server`` (5xx) open it after ``threshold`` in a row.
* While open, ``allow()`` is False until the cool-down ends (then ONE probe is let through,
  half-open). A failed probe doubles the cool-down (``base * 2**n``, capped); any success
  closes the breaker and resets the backoff.
* Log lines happen only on a state change (opened / re-opened / recovered), never per attempt.
* ``unavailable()`` is the cheap check callers use BEFORE placing a real call.
* State is written to a small JSON file (when a path is set) so ``friday doctor`` (another
  process) can show the last errors without any network call.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger

log = get_logger(__name__)

# Plain chat line shown to the user when a call is refused (listed in docs/TTS_HEALTH.md).
TTS_UNAVAILABLE_LINE = (
    "Voice is temporarily unavailable on my side, so I have not called. "
    "I will tell you when it is back."
)
TTS_BACK_LINE = "Voice is back. You can ask me to make that call again."
TTS_UNAVAILABLE = "tts_unavailable"  # typed reason (CallResult.error / refusal code)
TTS_FAILED = "tts_failed"  # typed reason: TTS died during a live call

_QUOTA = re.compile(r"\b402\b|insufficient[_ ]quota|no credits|quota", re.I)
_RATE = re.compile(r"\b429\b|rate.?limit|too many requests", re.I)
_SERVER = re.compile(r"\bHTTP 5\d\d\b|bad gateway|service unavailable|timed? ?out", re.I)


class TTSUnavailable(ProviderError):
    """The breaker is open: no vendor call is made."""

    def __init__(self, provider: str = "tts", detail: str = "") -> None:
        super().__init__(provider, f"{TTS_UNAVAILABLE}: {detail}".strip(": "))
        self.code = TTS_UNAVAILABLE


def classify(exc: BaseException | str) -> str | None:
    """'quota' | 'rate' | 'server' | None (not a health signal: bad input, cancelled...)."""
    text = exc if isinstance(exc, str) else f"{type(exc).__name__} {exc}"
    if _QUOTA.search(text):
        return "quota"
    if _RATE.search(text):
        return "rate"
    if _SERVER.search(text):
        return "server"
    return None


class TTSHealth:
    def __init__(
        self,
        *,
        now: Callable[[], float] = time.time,
        threshold: int = 3,
        base_s: float = 5.0,
        quota_base_s: float = 300.0,
        max_s: float = 1800.0,
        path: str | Path | None = None,
    ) -> None:
        self.now, self.threshold = now, threshold
        self.base_s, self.quota_base_s, self.max_s = base_s, quota_base_s, max_s
        self.path = Path(path) if path else None
        self.waiters: list[Callable[[], Awaitable[None]]] = []
        self.reset()

    def reset(self) -> None:
        self.open = False
        self.open_until = 0.0
        self.probing = False
        self.streak = 0
        self.opens = 0  # consecutive opens without a success (backoff exponent)
        self.last_error: dict[str, Any] | None = None
        self.last_ok_at: float | None = None

    # ------------------------------------------------------------------ queries
    def unavailable(self) -> bool:
        """True while the breaker is open and cooling down (cheap, no side effects)."""
        return self.open and self.now() < self.open_until

    def allow(self) -> bool:
        """May a vendor call go out? Closed: yes. Open: no, until the cool-down ends, then
        exactly one probe."""
        if not self.open:
            return True
        if self.now() < self.open_until or self.probing:
            return False
        self.probing = True
        return True

    # ------------------------------------------------------------------ updates
    def record_error(self, provider: str, exc: BaseException | str) -> str | None:
        kind = classify(exc)
        if kind is None:
            return None
        detail = (exc if isinstance(exc, str) else str(exc))[:200]
        self.last_error = {"provider": provider, "kind": kind, "detail": detail, "at": self.now()}
        self.streak += 1
        was_open = self.open
        if self.probing or kind == "quota" or self.streak >= self.threshold:
            self.opens += 1
            base = self.quota_base_s if kind == "quota" else self.base_s
            wait = min(base * 2 ** (self.opens - 1), self.max_s)
            self.open, self.open_until, self.probing = True, self.now() + wait, False
            # one line per state change: first open, or a failed probe (new longer cool-down)
            log.warning(
                "tts %s breaker %s (%s): no vendor calls for %ds. %s",
                provider, "re-opened" if was_open else "opened", kind, wait, detail,
            )
        self._save()
        return kind

    def record_success(self, provider: str = "tts") -> None:
        self.last_ok_at = self.now()
        recovered = self.open
        self.open, self.probing, self.streak, self.opens = False, False, 0, 0
        if recovered:
            log.info("tts %s recovered: breaker closed", provider)
            self._save()
            self._fire_waiters()

    def on_recovery(self, cb: Callable[[], Awaitable[None]]) -> None:
        self.waiters.append(cb)

    def _fire_waiters(self) -> None:
        waiters, self.waiters = self.waiters, []
        for cb in waiters:
            try:
                asyncio.get_running_loop().create_task(cb())
            except RuntimeError:  # no loop (sync caller): drop quietly
                break

    def recent_failure(self, within_s: float = 15.0) -> bool:
        e = self.last_error
        return bool(e and self.now() - float(e["at"]) <= within_s)

    # ------------------------------------------------------------------ persistence
    def snapshot(self) -> dict[str, Any]:
        return {
            "open": self.open, "open_until": self.open_until, "last_error": self.last_error,
            "last_ok_at": self.last_ok_at, "written_at": self.now(),
        }

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.snapshot()))
        except OSError:
            log.debug("tts health file not writable")


def read_snapshot(path: str | Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


_HEALTH = TTSHealth()


def get_health() -> TTSHealth:
    return _HEALTH


def set_health(h: TTSHealth) -> TTSHealth:
    """Swap the process-wide instance (tests)."""
    global _HEALTH
    _HEALTH = h
    return h
