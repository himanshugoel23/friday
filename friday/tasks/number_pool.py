"""Friday caller-ID pool (NP-2; founder: caller-ID reputation & number rotation).

Implements ``core.interfaces.NumberPool``:

* **sticky** - a business keeps its Friday number while that number can dial. It is
  moved only when the number is RETIRED (``NumberChoice.changed`` -> the "calling from
  a new number" line). While the sticky number is COOLING the choice carries
  ``not_before = cooling_until`` (the engine waits; it never borrows another number).
* **new businesses** - local presence first (same city, then same telecom circle), then
  best health score, then least load today.
* **pacing** per number: max/hour, max/day (warm-up ramp ``number_warmup_daily_caps``
  while WARMING), max concurrent, min gap between dials -> ``not_before``. No bursts.
* **health** over the last ``number_health_window_calls`` outbound calls: answer rate,
  short-call rate, DNC rate, provider blocks, spam label -> score 0..1.
* ``rescore()``: WARMING -> ACTIVE after the ramp; score below
  ``number_health_min_score`` -> COOLING for ``number_cooldown_h``; more than
  ``number_max_cooldowns_before_retire`` cooldowns -> RETIRED (keeps forwarding
  call-backs for ``number_retired_forward_days``). Publishes ``NumberStatusChanged``.
* **DNC / blocks are pool-wide** (``is_blocked``): rotation is NEVER used to get around
  a business that asked Friday to stop or blocked a number.

Persistence: ``NumberStore``. The default ``MemoryNumberStore`` is per process; when the
repository bundle provides ``repos.numbers`` implementing the same methods (Backend A,
NP-1 tables) it is used instead, so several replicas share one pool.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from friday.core.clock import Clock, SystemClock, ist_date, ist_day_bounds
from friday.core.config import Settings
from friday.core.events import EventBus, NumberStatusChanged
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    FridayNumber,
    NumberChoice,
    NumberHealth,
    NumberLimits,
    NumberOutcome,
    NumberStatus,
)
from friday.discovery.geo import phone_key

log = get_logger(__name__)

MIN_SAMPLE = 10  # calls before health can push a number into cooling
RESERVATION_TTL = timedelta(minutes=30)  # a lost release() never leaks a slot forever

# STD prefix (after +91) -> (city, telecom circle). Small, for local presence only.
_STD: dict[str, tuple[str, str]] = {
    "80": ("Bengaluru", "KA"),
    "22": ("Mumbai", "MH"),
    "20": ("Pune", "MH"),
    "11": ("Delhi", "DL"),
    "44": ("Chennai", "TN"),
    "40": ("Hyderabad", "AP"),
    "33": ("Kolkata", "WB"),
    "79": ("Ahmedabad", "GJ"),
    "141": ("Jaipur", "RJ"),
    "294": ("Udaipur", "RJ"),
    "484": ("Kochi", "KL"),
    "172": ("Chandigarh", "PB"),
}
_CITY_CIRCLE = {city.lower(): circle for city, circle in _STD.values()}


def locality(phone: str) -> tuple[str | None, str | None]:
    """(city, circle) for an Indian landline number; (None, None) for mobiles/unknown."""
    key = phone_key(phone)
    if len(key) == 10 and key[0] in "6789" and not key.startswith("80"):
        return None, None
    for n in (3, 2):
        if key[:n] in _STD:
            return _STD[key[:n]]
    return None, None


def circle_for_city(city: str | None) -> str | None:
    return _CITY_CIRCLE.get((city or "").strip().lower())


@dataclass
class _Outcome:
    at: datetime
    outcome: NumberOutcome
    business: str | None
    duration_s: float


@dataclass
class _Usage:
    dials: deque = field(default_factory=deque)  # dial times (UTC), pruned to 1 day
    inflight: dict[int, datetime] = field(default_factory=dict)  # token -> expires
    last_dial: datetime | None = None
    seq: int = 0


class NumberStore(Protocol):
    """Pool persistence (Backend A's NP-1 repos can implement this as ``repos.numbers``)."""

    async def list_numbers(self) -> list[FridayNumber]: ...
    async def save_number(self, number: FridayNumber) -> None: ...
    async def get_assignment(self, business_key: str) -> str | None: ...
    async def set_assignment(self, business_key: str, number_phone: str) -> None: ...
    async def add_outcome(self, number_phone: str, row: _Outcome) -> None: ...
    async def recent_outcomes(self, number_phone: str, limit: int) -> list[_Outcome]: ...
    async def add_dnc(self, business_key: str, reason: str, at: datetime) -> None: ...
    async def is_dnc(self, business_key: str) -> bool: ...


class MemoryNumberStore:
    def __init__(self) -> None:
        self.numbers: dict[str, FridayNumber] = {}
        self.assignments: dict[str, str] = {}
        self.outcomes: dict[str, list[_Outcome]] = {}
        self.dnc: dict[str, tuple[str, datetime]] = {}

    async def list_numbers(self) -> list[FridayNumber]:
        return [n.model_copy(deep=True) for n in self.numbers.values()]

    async def save_number(self, number: FridayNumber) -> None:
        self.numbers[number.phone] = number.model_copy(deep=True)

    async def get_assignment(self, business_key: str) -> str | None:
        return self.assignments.get(business_key)

    async def set_assignment(self, business_key: str, number_phone: str) -> None:
        self.assignments[business_key] = number_phone

    async def add_outcome(self, number_phone: str, row: _Outcome) -> None:
        self.outcomes.setdefault(number_phone, []).append(row)

    async def recent_outcomes(self, number_phone: str, limit: int) -> list[_Outcome]:
        return self.outcomes.get(number_phone, [])[-limit:]

    async def add_dnc(self, business_key: str, reason: str, at: datetime) -> None:
        self.dnc.setdefault(business_key, (reason, at))

    async def is_dnc(self, business_key: str) -> bool:
        return business_key in self.dnc


class Pool:
    """``NumberPool`` implementation."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Clock | None = None,
        bus: EventBus | None = None,
        store: NumberStore | None = None,
        provider: str = "simulator",
    ) -> None:
        self.s = settings
        self.clock = clock or SystemClock()
        self.bus = bus
        self.store: NumberStore = store or MemoryNumberStore()
        self.provider = provider
        self._usage: dict[str, _Usage] = {}
        self._lock = asyncio.Lock()
        self._bootstrapped = False

    # ------------------------------------------------------------------ numbers
    async def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        existing = {n.phone for n in await self.store.list_numbers()}
        for phone in self.s.friday_numbers:
            if phone in existing:
                continue
            city, circle = locality(phone)
            try:
                number = FridayNumber(
                    phone=phone,
                    provider=self.provider,
                    city=city,
                    circle=circle,
                    # configured numbers are already in service; new ones go through add_number
                    status=NumberStatus.ACTIVE,
                    warmup_day=len(self.s.number_warmup_daily_caps),
                    limits=self._limits(),
                    created_at=self.clock.now(),
                )
            except ValueError:
                log.error(
                    "FRIDAY_NUMBERS entry %s rejected (Indian 10-digit only)", mask_phone(phone)
                )
                continue
            await self.store.save_number(number)

    def _limits(self) -> NumberLimits:
        return NumberLimits(
            max_calls_per_hour=self.s.number_max_calls_per_hour,
            max_calls_per_day=self.s.number_max_calls_per_day,
            max_concurrent=self.s.number_max_concurrent,
            min_gap_s=self.s.number_min_gap_s,
        )

    async def add_number(self, number: FridayNumber) -> FridayNumber:
        """Ops: add a new (normally WARMING) number to the pool."""
        await self._bootstrap()
        if "limits" not in number.model_fields_set:
            number = number.model_copy(update={"limits": self._limits()})
        await self.store.save_number(number)
        return number

    async def _numbers(self) -> dict[str, FridayNumber]:
        await self._bootstrap()
        return {n.phone: n for n in await self.store.list_numbers()}

    async def has_numbers(self) -> bool:
        """False when no caller-ID is configured (dev/simulator): the runner picks one."""
        return bool(await self._numbers())

    async def list_numbers(self) -> list[FridayNumber]:
        nums = await self._numbers()
        for n in nums.values():
            n.health = await self._health(n)
        return sorted(nums.values(), key=lambda n: n.phone)

    async def owner_of(self, number_phone: str) -> FridayNumber | None:
        nums = await self._numbers()
        n = nums.get(number_phone) or next(
            (x for x in nums.values() if phone_key(x.phone) == phone_key(number_phone)), None
        )
        if n is None:
            return None
        if n.status == NumberStatus.RETIRED and (
            n.forward_until is None or n.forward_until <= self.clock.now()
        ):
            return None  # forwarding window over
        return n

    # ------------------------------------------------------------------ DNC (pool-wide)
    async def is_blocked(self, business_phone: str) -> bool:
        return await self.store.is_dnc(phone_key(business_phone))

    async def block(self, business_phone: str, reason: str) -> None:
        """Pool-wide DNC: no Friday number will ever dial this business again."""
        await self.store.add_dnc(phone_key(business_phone), reason, self.clock.now())
        log.info("DNC recorded for %s (%s)", mask_phone(business_phone), reason)

    # ------------------------------------------------------------------ choice + pacing
    def _usage_for(self, phone: str) -> _Usage:
        u = self._usage.setdefault(phone, _Usage())
        now = self.clock.now()
        while u.dials and u.dials[0] <= now - timedelta(days=1):
            u.dials.popleft()
        for token, exp in list(u.inflight.items()):
            if exp <= now:
                del u.inflight[token]
        return u

    def _daily_cap(self, n: FridayNumber) -> int:
        cap = n.limits.max_calls_per_day
        caps = self.s.number_warmup_daily_caps
        if n.status == NumberStatus.WARMING and caps:
            cap = min(cap, caps[min(n.warmup_day, len(caps) - 1)])
        return cap

    def _not_before(self, n: FridayNumber) -> datetime | None:
        """None = may dial now; else the earliest instant pacing allows."""
        now = self.clock.now()
        u = self._usage_for(n.phone)
        waits: list[datetime] = []
        if u.last_dial and now - u.last_dial < timedelta(seconds=n.limits.min_gap_s):
            waits.append(u.last_dial + timedelta(seconds=n.limits.min_gap_s))
        hour = [d for d in u.dials if d > now - timedelta(hours=1)]
        if len(hour) >= n.limits.max_calls_per_hour:
            waits.append(hour[-n.limits.max_calls_per_hour] + timedelta(hours=1))
        start, end = ist_day_bounds(now)
        today = [d for d in u.dials if d >= start]
        if len(today) >= self._daily_cap(n):
            waits.append(end)
        if len(u.inflight) >= n.limits.max_concurrent:
            waits.append(now + timedelta(seconds=max(n.limits.min_gap_s, 30)))
        return max(waits) if waits else None

    def _reserve(self, n: FridayNumber) -> None:
        u = self._usage_for(n.phone)
        now = self.clock.now()
        u.seq += 1
        u.inflight[u.seq] = now + RESERVATION_TTL
        u.dials.append(now)
        u.last_dial = now

    def _load(self, n: FridayNumber) -> int:
        start, _ = ist_day_bounds(self.clock.now())
        return sum(1 for d in self._usage_for(n.phone).dials if d >= start)

    async def choose_for(
        self,
        business_phone: str,
        *,
        city: str | None = None,
        circle: str | None = None,
        business_id: str | None = None,
    ) -> NumberChoice | None:
        async with self._lock:
            if await self.is_blocked(business_phone):
                return None
            key = phone_key(business_phone)
            nums = await self._numbers()
            sticky_phone = await self.store.get_assignment(key)
            sticky = nums.get(sticky_phone) if sticky_phone else None
            changed = False
            if sticky is not None and sticky.status != NumberStatus.RETIRED:
                if sticky.status == NumberStatus.COOLING:
                    # stays with its number; wait for the cooldown (never borrow another)
                    return NumberChoice(
                        number=sticky,
                        sticky=True,
                        not_before=sticky.cooling_until or self.clock.now() + timedelta(hours=1),
                        reason="sticky number cooling",
                    )
                return self._offer(sticky, sticky=True, changed=False, reason="sticky")
            if sticky is not None:
                changed = True  # retired: move the business (brief.number_changed)
            if not city and not circle:
                city, circle = locality(business_phone)
            circle = circle or circle_for_city(city)
            dialable = [n for n in nums.values() if n.can_dial]
            if not dialable:
                return None
            for n in dialable:
                n.health = await self._health(n)

            def rank(n: FridayNumber) -> tuple:
                local = (
                    0
                    if city and n.city and n.city.lower() == city.lower()
                    else (1 if circle and n.circle == circle else 2)
                )
                return (local, -round(n.health.score, 2), self._load(n), n.phone)

            ordered = sorted(dialable, key=rank)
            ready = [n for n in ordered if self._not_before(n) is None]
            pick = ready[0] if ready else ordered[0]
            await self.store.set_assignment(key, pick.phone)
            return self._offer(
                pick,
                sticky=False,
                changed=changed,
                reason="reassigned (retired number)" if changed else "new business",
            )

    def _offer(self, n: FridayNumber, *, sticky: bool, changed: bool, reason: str) -> NumberChoice:
        nb = self._not_before(n)
        if nb is None:
            self._reserve(n)  # concurrency slot + pacing counters; freed by release()
        return NumberChoice(number=n, sticky=sticky, changed=changed, not_before=nb, reason=reason)

    async def release(self, number_phone: str) -> None:
        u = self._usage_for(number_phone)
        if u.inflight:
            u.inflight.pop(min(u.inflight))

    # ------------------------------------------------------------------ health
    async def record_outcome(
        self,
        number_phone: str,
        outcome: NumberOutcome,
        *,
        business_phone: str | None = None,
        duration_s: float = 0.0,
    ) -> None:
        if outcome == NumberOutcome.ANSWERED and 0 < duration_s < self.s.number_short_call_s:
            outcome = NumberOutcome.SHORT_CALL
        await self.store.add_outcome(
            number_phone, _Outcome(self.clock.now(), outcome, business_phone, duration_s)
        )
        if business_phone and outcome in (NumberOutcome.DNC_REQUEST, NumberOutcome.BLOCKED):
            await self.block(business_phone, outcome.value)  # honoured on EVERY number

    async def _health(self, n: FridayNumber) -> NumberHealth:
        rows = await self.store.recent_outcomes(n.phone, self.s.number_health_window_calls)
        answered = {NumberOutcome.ANSWERED, NumberOutcome.SHORT_CALL, NumberOutcome.DNC_REQUEST}
        h = NumberHealth(
            calls=len(rows),
            answered=sum(1 for r in rows if r.outcome in answered),
            short_calls=sum(1 for r in rows if r.outcome == NumberOutcome.SHORT_CALL),
            dnc_requests=sum(1 for r in rows if r.outcome == NumberOutcome.DNC_REQUEST),
            blocks=sum(
                1 for r in rows if r.outcome in (NumberOutcome.BLOCKED, NumberOutcome.REJECTED)
            ),
            spam_labelled=n.health.spam_labelled,
            computed_at=self.clock.now(),
        )
        h.score = self._score(h)
        return h

    def _score(self, h: NumberHealth) -> float:
        if h.spam_labelled:
            return 0.0
        if h.calls < MIN_SAMPLE:
            return 1.0
        s = self.s
        score = (
            min(1.0, h.answer_rate / s.number_min_answer_rate) if s.number_min_answer_rate else 1.0
        )
        if h.short_call_rate > s.number_max_short_call_rate > 0:
            score *= s.number_max_short_call_rate / h.short_call_rate
        dnc_rate = h.dnc_requests / h.calls
        if dnc_rate > s.number_max_dnc_rate > 0:
            score *= s.number_max_dnc_rate / dnc_rate
        score *= 0.5**h.blocks
        return round(max(0.0, min(1.0, score)), 3)

    async def health(self, number_phone: str) -> NumberHealth:
        n = (await self._numbers()).get(number_phone)
        if n is None:
            return NumberHealth()
        return await self._health(n)

    async def rescore(self) -> list[FridayNumber]:
        now = self.clock.now()
        changed: list[FridayNumber] = []
        async with self._lock:
            for n in (await self._numbers()).values():
                old = n.status
                n.health = await self._health(n)
                reason = ""
                if n.status in (NumberStatus.WARMING, NumberStatus.ACTIVE):
                    if n.status == NumberStatus.WARMING:
                        n.warmup_day = max(
                            n.warmup_day, (ist_date(now) - ist_date(n.created_at)).days
                        )
                    if n.health.score < self.s.number_health_min_score:
                        n.cooldowns += 1
                        if n.cooldowns > self.s.number_max_cooldowns_before_retire:
                            self._retire(n, now)
                            reason = "health below threshold too often"
                        else:
                            n.status = NumberStatus.COOLING
                            n.cooling_until = now + timedelta(hours=self.s.number_cooldown_h)
                            reason = f"health {n.health.score:.2f} below threshold"
                    elif n.status == NumberStatus.WARMING and n.warmup_day >= len(
                        self.s.number_warmup_daily_caps
                    ):
                        n.status = NumberStatus.ACTIVE
                        reason = "warm-up complete"
                elif (
                    n.status == NumberStatus.COOLING and n.cooling_until and now >= n.cooling_until
                ):
                    n.status = NumberStatus.ACTIVE
                    n.cooling_until = None
                    n.health = NumberHealth(computed_at=now)  # fresh window after cooldown
                    await self._reset_window(n)
                    reason = "cooldown over"
                if n.status != old:
                    await self.store.save_number(n)
                    changed.append(n)
                    await self._publish(n, old, reason)
                else:
                    await self.store.save_number(n)
        return changed

    async def _reset_window(self, n: FridayNumber) -> None:
        clear = getattr(self.store, "clear_outcomes", None)
        if clear is not None:
            await clear(n.phone)
        elif isinstance(self.store, MemoryNumberStore):
            self.store.outcomes[n.phone] = []

    def _retire(self, n: FridayNumber, now: datetime) -> None:
        n.status = NumberStatus.RETIRED
        n.retired_at = now
        n.forward_until = now + timedelta(days=self.s.number_retired_forward_days)

    async def set_status(self, number_phone: str, status: NumberStatus, *, reason: str) -> None:
        async with self._lock:
            n = (await self._numbers()).get(number_phone)
            if n is None:
                raise KeyError(number_phone)
            old = n.status
            now = self.clock.now()
            if status == NumberStatus.RETIRED:
                self._retire(n, now)
            elif status == NumberStatus.COOLING:
                n.status = status
                n.cooldowns += 1
                n.cooling_until = now + timedelta(hours=self.s.number_cooldown_h)
            else:
                n.status = status
                n.cooling_until = None
            await self.store.save_number(n)
            if old != n.status:
                await self._publish(n, old, f"ops: {reason}")

    async def _publish(self, n: FridayNumber, old: NumberStatus, reason: str) -> None:
        log.info("number %s %s -> %s (%s)", mask_phone(n.phone), old, n.status, reason)
        if self.bus is not None:
            await self.bus.publish(
                NumberStatusChanged(
                    number_id=n.id,
                    phone=n.phone,
                    old=old.value,
                    new=n.status.value,
                    reason=reason,
                    at=self.clock.now(),
                )
            )


def build_number_pool(c: Any) -> Pool:  # c: Container
    store = None
    try:
        store = getattr(c.get("repos"), "numbers", None)
    except Exception:  # noqa: BLE001 - repos not wired (tests / tools)
        store = None
    try:
        provider = c.provider_for("telephony")
    except Exception:  # noqa: BLE001
        provider = "simulator"
    return Pool(c.settings, clock=c.clock, bus=c.bus, store=store, provider=provider)
