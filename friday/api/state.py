"""Per-user conversational state kept OUT of process memory (S-1, SECURITY-34).

Pending PIN-gated actions, the onboarding PIN's first entry (argon2 hash, never the
PIN) and the step-up grace window live in the shared ``Cache`` (``c.get("cache")``:
in-memory in dev, Redis in production) with a TTL, so they are bounded, survive
load-balancing across API replicas, and expire on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.models import InboundMessage, Interpretation
from friday.core.scale import Cache, MemoryCache

PENDING_TTL_S = 600
ONBOARDING_PIN_TTL_S = 900
STEP_UP_TTL_S = 600


@dataclass
class PendingAction:
    kind: str  # "pin" | "delete_confirm"
    interpretation: Interpretation | None
    message: InboundMessage | None
    expires_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)

    def dump(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "interpretation": (
                self.interpretation.model_dump(mode="json") if self.interpretation else None
            ),
            "message": self.message.model_dump(mode="json") if self.message else None,
            "expires_at": self.expires_at.isoformat(),
            "extra": self.extra,
        }

    @classmethod
    def load(cls, data: dict[str, Any]) -> PendingAction:
        return cls(
            kind=data["kind"],
            interpretation=(
                Interpretation.model_validate(data["interpretation"])
                if data.get("interpretation")
                else None
            ),
            message=InboundMessage.model_validate(data["message"]) if data.get("message") else None,
            expires_at=datetime.fromisoformat(data["expires_at"]),
            extra=dict(data.get("extra") or {}),
        )


class UserState:
    def __init__(self, cache: Cache | None) -> None:
        self.cache: Cache = cache or MemoryCache()

    # ------------------------------------------------------------------ pending actions
    async def get_pending(self, user_id: str, now: datetime) -> PendingAction | None:
        raw = await self.cache.get(f"pending:{user_id}")
        if not raw:
            return None
        pending = PendingAction.load(raw)
        if pending.expires_at <= now:
            await self.clear_pending(user_id)
            return None
        return pending

    async def set_pending(self, user_id: str, pending: PendingAction) -> None:
        await self.cache.set(f"pending:{user_id}", pending.dump(), ttl_s=PENDING_TTL_S)

    async def clear_pending(self, user_id: str) -> None:
        await self.cache.delete(f"pending:{user_id}")

    # ------------------------------------------------------------------ onboarding PIN
    async def get_first_pin_hash(self, user_id: str) -> str | None:
        return await self.cache.get(f"obpin:{user_id}")

    async def set_first_pin_hash(self, user_id: str, pin_hash: str) -> None:
        await self.cache.set(f"obpin:{user_id}", pin_hash, ttl_s=ONBOARDING_PIN_TTL_S)

    async def clear_first_pin_hash(self, user_id: str) -> None:
        await self.cache.delete(f"obpin:{user_id}")

    # ------------------------------------------------------------------ step-up grace
    async def stepped_up(self, user_id: str) -> bool:
        return bool(await self.cache.get(f"stepup:{user_id}"))

    async def mark_stepped_up(self, user_id: str) -> None:
        await self.cache.set(f"stepup:{user_id}", True, ttl_s=STEP_UP_TTL_S)

    async def clear_user(self, user_id: str) -> None:
        for prefix in ("pending", "obpin", "stepup"):
            await self.cache.delete(f"{prefix}:{user_id}")


INBOUND_RATE_PER_MIN = 20  # SECURITY-21 (per sender)
INBOUND_RATE_PER_DAY = 300
SLOW_DOWN = "You're sending messages faster than I can keep up. Give me a minute."


class InboundThrottle:
    """Fixed-window per-sender counters in the shared Cache (minute + IST-agnostic UTC
    day). Over the limit -> the message never reaches the brain (cost DoS / abuse)."""

    def __init__(
        self,
        cache: Cache | None,
        *,
        per_min: int = INBOUND_RATE_PER_MIN,
        per_day: int = INBOUND_RATE_PER_DAY,
    ) -> None:
        self.cache: Cache = cache or MemoryCache()
        self.per_min = per_min
        self.per_day = per_day

    async def _bump(self, key: str, ttl_s: int) -> int:
        n = int(await self.cache.get(key) or 0) + 1
        await self.cache.set(key, n, ttl_s=ttl_s)
        return n

    async def allow(self, sender_key: str, now: datetime) -> bool:
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        per_min = await self._bump(f"rl:m:{sender_key}:{minute}", 120)
        per_day = await self._bump(f"rl:d:{sender_key}:{day}", 2 * 86400)
        return per_min <= self.per_min and per_day <= self.per_day

    async def first_notice(self, sender_key: str, now: datetime) -> bool:
        """True once per sender per hour: answer the flood at most once."""
        key = f"rl:n:{sender_key}:{now.strftime('%Y%m%d%H')}"
        if await self.cache.get(key):
            return False
        await self.cache.set(key, True, ttl_s=3600)
        return True
