# ruff: noqa: E501
"""Every rule that stands between the web channel and a phone. Code-enforced, tested.

* The channel needs ``FRIDAY_PROFILE=pilot``; a tester's number must be in
  ``FRIDAY_PILOT_ALLOWED_NUMBERS`` or ``FRIDAY_CHATBOT_TESTERS`` (checked at invite time and again
  on every request and every call).
* ``GuardedTelephony`` sits on ``c.telephony`` (so it catches vendor calls, consumer calls, urgent
  calls, everything that dials): the destination of any call is forced to the requesting tester's
  OWN number when the call can be tied to a tester (task requester), and otherwise must BE an active
  tester's number. Any other destination is refused before the provider is touched. This is how a
  vendor call lands on the tester's own phone and never on a real business.
* Kill switch (``friday pause``) is checked on every message and every dial.
* Per-tester calls/day and INR/day, a global INR/day, messages per minute: 0 = unlimited (pilot
  default; the Vobiz prepaid balance is then the ceiling).
* No Meta/WhatsApp send is possible: ``WebChannel`` has no network code (tests/webchat).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.pilot import estimate_cost_inr
from friday.webchat.config import WebConfig
from friday.webchat.registry import Registry, Tester, allowed_numbers, mask

log = get_logger(__name__)


class WebRefused(ProviderError):
    """A rule said no (a ProviderError so every caller treats it as a failed dial)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__("web", message)
        self.code = code


def startup_problems(settings: Any, cfg: WebConfig) -> list[str]:
    """Why the web channel may not start (empty == go). No network, no files."""
    problems = list(cfg.problems())
    if not getattr(settings, "is_pilot", False):
        problems.append("FRIDAY_PROFILE must be pilot.")
    redirect = getattr(settings, "vendor_call_redirect_to", None)
    if redirect and redirect not in allowed_numbers(settings):
        problems.append("FRIDAY_VENDOR_CALL_REDIRECT_TO is not an allow-listed number.")
    return problems


def ensure_dialable(settings: Any, phone: str) -> bool:
    """Make an allowed tester number dialable in THIS process (testers listed only in
    FRIDAY_CHATBOT_TESTERS are added to the in-memory pilot allow-list). False = not allowed."""
    if phone not in allowed_numbers(settings):
        return False
    lst = settings.pilot_allowed_numbers
    if phone not in lst:
        lst.append(phone)
    return True


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute, self._clock = per_minute, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


class WebGuard:
    def __init__(
        self,
        settings: Any,
        cfg: WebConfig,
        registry: Registry,
        *,
        paused: Callable[[], bool] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings, self.cfg, self.registry = settings, cfg, registry
        self._paused = paused or self._default_paused
        self._now = now

    def _default_paused(self) -> bool:
        from friday.pause import is_paused

        return is_paused(self.settings)

    def paused(self) -> bool:
        return bool(self._paused())

    def check_call(self, tester: Tester, seconds: int | None = None) -> tuple[int, float]:
        """(clamped seconds, cost estimate) or raises ``WebRefused``. Run before every dial."""
        now = self._now() if self._now else None
        if self.paused():
            raise WebRefused("kill_switch", "The kill switch is on (friday pause): no call.")
        if not tester.active(now) or not ensure_dialable(self.settings, tester.phone):
            raise WebRefused("number_not_allowed", f"{mask(tester.phone)} is not an allowed tester number: not dialled.")
        secs = int(max(30, min(seconds or self.cfg.max_call_seconds, self.cfg.max_call_seconds)))
        est = estimate_cost_inr(secs)
        calls, spend = self.registry.usage(tester.id, now)
        cap = self.cfg.max_calls_per_day
        if cap and calls >= cap:
            raise WebRefused("daily_call_cap", f"{calls} calls already today (cap {cap}).")
        cap_s = self.cfg.max_spend_inr
        if cap_s and spend + est > cap_s:
            raise WebRefused("daily_spend_cap", f"Estimated spend today Rs {spend:.1f} + this call Rs {est:.1f} is above the cap Rs {cap_s:g}.")
        g_cap = self.cfg.global_max_spend_inr
        if g_cap and self.registry.usage(None, now)[1] + est > g_cap:
            raise WebRefused("global_spend_cap", f"The all-testers spend cap Rs {g_cap:g} for today would be passed.")
        return secs, est

    def record_call(self, tester: Tester, seconds: float, cost_inr: float) -> None:
        self.registry.add_call(tester.id, seconds, cost_inr, self._now() if self._now else None)


Resolver = Callable[[Any], Awaitable[Tester | None]]


class GuardedTelephony:
    """Wraps the container's telephony provider; everything else is delegated untouched."""

    def __init__(self, inner: Any, guard: WebGuard, requester: Resolver | None = None) -> None:
        self._inner, self.guard, self._requester = inner, guard, requester

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "telephony")

    async def place_call(self, request: Any, *a: Any, **k: Any) -> Any:
        g = self.guard
        tester: Tester | None = None
        if self._requester is not None:
            try:
                tester = await self._requester(request)
            except Exception:  # noqa: BLE001 - an unresolvable requester falls back to the strict rule
                tester = None
        if tester is None:
            tester = g.registry.by_phone(request.to_phone)
        if tester is None:
            raise WebRefused("number_not_allowed", f"{mask(request.to_phone)} is not a tester's own number: not dialled.")
        secs, est = g.check_call(tester, getattr(request, "max_duration_s", None))
        if request.to_phone != tester.phone or request.max_duration_s != secs:
            request = request.model_copy(update={"to_phone": tester.phone, "max_duration_s": secs})
        g.record_call(tester, secs, est)  # counted before the dial: concurrent calls cannot slip past a cap
        return await self._inner.place_call(request, *a, **k)
