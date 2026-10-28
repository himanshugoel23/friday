# ruff: noqa: E501
"""QaGuard: every rule that stands between a QA run and a phone. All code-enforced, all tested.

* QA mode is a switch, ``FRIDAY_QA_LIVE=true`` (default OFF). The page and the CLI refuse to start
  unless it is on AND ``FRIDAY_MODE=live`` AND ``FRIDAY_PROFILE=pilot`` AND the allow-list
  (``FRIDAY_PILOT_ALLOWED_NUMBERS``) holds exactly one number: the founder's own.
* The only number a QA call may reach is that number. A scenario or flow that supplies any other
  number (a vendor, a family member, a redirect) is refused before anything is dialled.
* The number is shown only as its last two digits (``mask2``).
* The kill switch (``friday pause``) is checked before a run and again before the dial.
* Caps: at most ``FRIDAY_QA_MAX_CALLS_PER_DAY`` calls (default 20) and an estimated spend of
  ``FRIDAY_QA_MAX_SPEND_INR`` (default Rs 100) per IST day, counted in ``var/qa/ledger.jsonl``.
* Each call lasts at most 3 minutes (``HARD_MAX_CALL_SECONDS``).
* No recording unless it is already configured (QA never turns it on); no OTP, PIN or payment
  prompt is ever part of a scenario (``scenarios.assert_no_secret_prompts``).
"""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from friday.integration.telephony import mask2
from friday.qa import override
from friday.qa.config import HARD_MAX_CALL_SECONDS, QaConfig
from friday.qa.store import QaStore


class QaRefused(RuntimeError):
    """A rule said no. ``code`` is machine-readable; ``str(e)`` is safe to show (masked)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def startup_problems(settings: Any, qa: QaConfig) -> list[str]:
    """Why QA mode may not start (empty list == go). No network, no file access."""
    problems: list[str] = []
    if not qa.live:
        problems.append("FRIDAY_QA_LIVE is not true (QA mode is OFF by default).")
    if not getattr(settings, "is_live", False):
        problems.append("FRIDAY_MODE must be live.")
    if not getattr(settings, "is_pilot", False):
        problems.append("FRIDAY_PROFILE must be pilot.")
    allow = list(getattr(settings, "pilot_allowed_numbers", []) or [])
    if len(allow) != 1:
        problems.append(
            "FRIDAY_PILOT_ALLOWED_NUMBERS must hold exactly one number, your own "
            f"(it holds {len(allow)})."
        )
    return problems


def estimate_cost(seconds: float) -> float:
    from friday.pilot import estimate_cost_inr

    return float(estimate_cost_inr(seconds))


class QaGuard:
    def __init__(
        self,
        settings: Any,
        qa: QaConfig,
        store: QaStore,
        *,
        paused: Callable[[], bool] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings, self.qa, self.store = settings, qa, store
        self._paused = paused or self._default_paused
        self._now = now

    def _default_paused(self) -> bool:
        from friday.pause import is_paused

        return is_paused(self.settings)

    # ------------------------------------------------------------------ start-up
    def problems(self) -> list[str]:
        return startup_problems(self.settings, self.qa)

    def require_startable(self) -> None:
        problems = self.problems()
        if problems:
            raise QaRefused("not_startable", "QA mode will not start: " + " ".join(problems))

    # ------------------------------------------------------------------ the one number
    @property
    def target(self) -> str:
        self.require_startable()
        return list(self.settings.pilot_allowed_numbers)[0]

    @property
    def masked_target(self) -> str:
        allow = list(getattr(self.settings, "pilot_allowed_numbers", []) or [])
        return mask2(allow[0]) if len(allow) == 1 else "<not set>"

    def check_number(self, number: str | None) -> str:
        """The number to dial must be exactly the allow-listed one. Never any other."""
        target = self.target
        if not number or number != target or self.settings.pilot_dial_blocked(number):
            raise QaRefused(
                "number_not_allowed",
                f"{mask2(number)} is not your allow-listed number ({mask2(target)}): not dialled.",
            )
        return number

    # ------------------------------------------------------------------ checks before a call
    def clamp_seconds(self, seconds: int | None = None) -> int:
        return int(max(30, min(seconds or self.qa.seconds, self.qa.seconds, HARD_MAX_CALL_SECONDS)))

    def check_call(
        self, number: str | None, seconds: int | None = None, *, extra_numbers: tuple[str, ...] = ()
    ) -> tuple[str, int, float]:
        """(number, seconds, cost estimate) or raises ``QaRefused``. Run before every dial."""
        self.require_startable()
        for other in extra_numbers:  # a flow that supplies another number is refused outright
            self.check_number(other)
        n = self.check_number(number)
        if self._paused():
            raise QaRefused("kill_switch", "The kill switch is on (friday pause): no call.")
        secs = self.clamp_seconds(seconds)
        calls, spend = self.store.today(self._now() if self._now else None)
        if calls >= self.qa.max_calls_per_day:
            raise QaRefused(
                "daily_call_cap",
                f"{calls} QA calls already today (cap {self.qa.max_calls_per_day}).",
            )
        est = estimate_cost(secs)
        if spend + est > self.qa.max_spend_inr:
            raise QaRefused(
                "daily_spend_cap",
                f"Estimated spend today Rs {spend:.1f} + this call Rs {est:.1f} is above "
                f"the QA cap Rs {self.qa.max_spend_inr:g}.",
            )
        return n, secs, est

    def record_call(self, scenario: str, seconds: float, cost_inr: float) -> None:
        self.store.add_ledger(scenario, seconds, cost_inr, now=self._now() if self._now else None)

    # ------------------------------------------------------------------ the QA session
    @contextlib.contextmanager
    def session(self, scenario: str, run_id: str | None = None) -> Iterator[override.QaSession]:
        """While this is open the QA-only override (pending lines, caps, window) is on, for the
        one allow-listed number. It is switched off again on exit, even on an error."""
        target = self.target  # raises unless QA is startable
        sess = override.QaSession(
            run_id=run_id or secrets.token_hex(4),
            scenario=scenario,
            target=target,
            pending_log=self.store.pending_path,
        )
        override.activate(sess)
        try:
            yield sess
        finally:
            override.deactivate()
