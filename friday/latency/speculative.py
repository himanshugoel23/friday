"""Speculative understanding: start understanding the caller's words BEFORE they finish speaking.

While the call leg is still timing out the caller's pause (650-900 ms), the early REST transcript
or a stable streaming partial usually already exists. ``Speculator`` lets the policy start the
(rules + classifier + model) understanding on that text right away. When the utterance is finally
committed:

* final text equals the speculative text (same words, ignoring case / punctuation / spacing):
  the result is REUSED (``hit``), saving up to the whole model call (~0.45-0.65 s),
* final text differs: the speculative result is dropped (``miss``) and a fresh call runs,
* the caller kept talking, or barged in: the speculative task is cancelled (``cancelled``).

Safety rules this module enforces by construction:

* it only ever runs a pure ``factory`` coroutine that RETURNS a value; it holds no call state and
  changes nothing: acting on the result (moving the script, learning, speaking) happens only in the
  normal path after the commit,
* at most ONE speculative call per turn (``calls_this_turn``); a cancelled or missed one still
  counts, so a second guess in the same turn is never started (no double billing),
* a numeric difference is a difference ("400" is not "500"): the comparison keeps digits.

Log lines (INFO), in the style of the ``reply gap`` lines::

    speculative understanding started (text 'haan ji bataiye', step S1)
    speculative understanding hit (saved ~430 ms, text 'haan ji bataiye')
    speculative understanding miss (text changed 'haan ji' -> 'haan ji bataiye'; model call wasted)
    speculative understanding cancelled (caller kept talking)
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from friday.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")

_PUNCT = re.compile(r"[^\w\u0900-\u0963\u0966-\u097F]+")  # the danda is punctuation


def normalise_utterance(text: str) -> str:
    """Case-folded words only: punctuation / spacing differences vanish, digits and words stay."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(_PUNCT.sub(" ", t.replace("_", " ")).split())


def same_utterance(a: str, b: str) -> bool:
    na = normalise_utterance(a)
    return bool(na) and na == normalise_utterance(b)


@dataclass
class Speculation(Generic[T]):
    key: tuple[str, str]  # (step, what Friday said): the context the answer was computed in
    text: str
    task: asyncio.Task[T]
    started: float
    finished: float | None = None


@dataclass
class SpecStats:
    started: int = 0
    hits: int = 0
    misses: int = 0
    cancelled: int = 0
    failed: int = 0
    skipped_cap: int = 0
    saved_ms: list[float] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        done = self.hits + self.misses
        return self.hits / done if done else 0.0


class Speculator(Generic[T]):
    """One per call (kept on the call state). Not thread-safe; runs on the event loop."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock
        self.current: Speculation[T] | None = None
        self.calls_this_turn = 0
        self.stats = SpecStats()

    def _now(self) -> float:
        return self._clock() if self._clock else asyncio.get_running_loop().time()

    @property
    def active(self) -> bool:
        return self.current is not None

    def start(
        self, key: tuple[str, str], text: str, factory: Callable[[], Awaitable[T]]
    ) -> bool:
        """Begin understanding ``text``. False (nothing started) when empty, when a speculation
        is already running for this very text, or when this turn already used its one call."""
        if not normalise_utterance(text):
            return False
        cur = self.current
        if cur is not None and cur.key == key and same_utterance(cur.text, text):
            return False  # the same guess again (e.g. a repeated partial): keep the one in flight
        if self.calls_this_turn >= 1:
            self.stats.skipped_cap += 1
            return False
        self.calls_this_turn += 1
        self.stats.started += 1
        started = self._now()

        async def run() -> T:
            return await factory()

        task: asyncio.Task[T] = asyncio.ensure_future(run())
        spec: Speculation[T] = Speculation(key, text, task, started)

        def done(_t: asyncio.Task[T]) -> None:
            spec.finished = self._now()
            if not _t.cancelled():
                _t.exception()  # mark retrieved: a failed guess must never log "never retrieved"

        task.add_done_callback(done)
        self.current = spec
        log.info("speculative understanding started (text %r, step %s)", text[:60], key[0])
        return True

    def cancel(self, reason: str = "caller kept talking") -> bool:
        """Drop the running guess (caller continued, barge-in, hold, hang-up). The turn's one
        speculative call stays spent."""
        spec, self.current = self.current, None
        if spec is None:
            return False
        if not spec.task.done():
            spec.task.cancel()
        self.stats.cancelled += 1
        log.info("speculative understanding cancelled (%s)", reason)
        return True

    async def take(self, key: tuple[str, str], text: str) -> tuple[T | None, str]:
        """At the commit. ``(result, "hit")`` when the final ``text`` is the speculative text in
        the same context; ``(None, "miss")`` when it differs (the guess is cancelled);
        ``(None, "failed")`` when the guess itself failed; ``(None, "none")`` with no guess.
        Always ends the turn: the next turn may speculate again."""
        spec, self.current = self.current, None
        self.calls_this_turn = 0
        if spec is None:
            return None, "none"
        if spec.key != key or not same_utterance(spec.text, text):
            if not spec.task.done():
                spec.task.cancel()
            self.stats.misses += 1
            log.info(
                "speculative understanding miss (text changed %r -> %r; model call wasted)",
                spec.text[:60], text[:60],
            )
            return None, "miss"
        try:
            result = await spec.task
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if me is not None and me.cancelling():
                raise  # we were cancelled, not the guess
            self.stats.failed += 1
            return None, "failed"
        except Exception as e:  # noqa: BLE001 - a failed guess just means the normal path runs
            self.stats.failed += 1
            log.info("speculative understanding failed (%s); running it again", type(e).__name__)
            return None, "failed"
        end = spec.finished if spec.finished is not None else self._now()
        saved = max(0.0, (min(end, self._now()) - spec.started) * 1000)
        self.stats.hits += 1
        self.stats.saved_ms.append(saved)
        log.info("speculative understanding hit (saved ~%.0f ms, text %r)", saved, text[:60])
        return result, "hit"

    def end_turn(self) -> None:
        """A turn ended without a commit going through ``take`` (call ended, hold music)."""
        self.cancel("turn ended")
        self.calls_this_turn = 0

