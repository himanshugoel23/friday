"""Daily cap per user and a per-day cost log for voice replies.

Counters live in the shared cache with a 2-day TTL: ``vn:cnt:<user>:<IST date>`` and
``vn:cost:<IST date>``. The cost is an ESTIMATE (``voice_note_cost_per_1k_chars_inr``), counted only
when a reply was really synthesised (a cache hit costs nothing). The cache has no atomic increment,
so two simultaneous replies to one user may both pass the cap by one; the cap is a cost guard, not
a security limit.
"""

from __future__ import annotations

from dataclasses import dataclass

from friday.core.clock import Clock, ist_date
from friday.core.logging import get_logger
from friday.core.scale import Cache

log = get_logger(__name__)
TTL_S = 2 * 86400


@dataclass
class DayCost:
    day: str
    replies: int = 0
    synthesised_chars: int = 0
    cache_hits: int = 0
    est_inr: float = 0.0


def _load(day: str, raw: object) -> DayCost:
    data = raw if isinstance(raw, dict) else {}
    keys = ("replies", "synthesised_chars", "cache_hits", "est_inr")
    return DayCost(day=day, **{k: data[k] for k in keys if k in data})


class VoiceLedger:
    def __init__(self, cache: Cache, clock: Clock, *, daily_cap: int, cost_per_1k_chars_inr: float):
        self.cache, self.clock = cache, clock
        self.daily_cap, self.cost_per_1k = daily_cap, cost_per_1k_chars_inr

    def _day(self) -> str:
        return ist_date(self.clock.now()).isoformat()

    async def used_today(self, user_id: str) -> int:
        return int(await self.cache.get(f"vn:cnt:{user_id}:{self._day()}") or 0)

    async def allow(self, user_id: str) -> bool:
        return await self.used_today(user_id) < self.daily_cap

    async def record(self, user_id: str, chars: int, *, cached: bool) -> DayCost:
        day = self._day()
        await self.cache.set(
            f"vn:cnt:{user_id}:{day}", await self.used_today(user_id) + 1, ttl_s=TTL_S
        )
        cost = _load(day, await self.cache.get(f"vn:cost:{day}"))
        cost.replies += 1
        if cached:
            cost.cache_hits += 1
        else:
            cost.synthesised_chars += chars
            cost.est_inr = round(cost.synthesised_chars / 1000 * self.cost_per_1k, 4)
        await self.cache.set(f"vn:cost:{day}", cost.__dict__, ttl_s=TTL_S)
        log.info(
            "voice reply cost day=%s chars=%d cached=%s day_total_chars=%d est_inr=%.2f",
            day, chars, cached, cost.synthesised_chars, cost.est_inr,
        )  # fmt: skip
        return cost

    async def cost_today(self) -> DayCost:
        day = self._day()
        return _load(day, await self.cache.get(f"vn:cost:{day}"))
