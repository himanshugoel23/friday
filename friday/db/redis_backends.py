"""Redis variants of lock, cache and rate limiter (S-3). ``redis`` is only imported when
``FRIDAY_REDIS_URL`` is configured, so it stays an optional runtime dependency.

* ``RedisLock``        - ``SET key token NX PX`` + compare-and-delete Lua release.
* ``RedisCache``       - JSON values with TTL.
* ``RedisRateLimiter`` - token bucket (Lua, atomic) per key + concurrency slots (counter
  with TTL guard) shared by every replica.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from friday.core.interfaces import ProviderError
from friday.core.scale import LockTimeout

if TYPE_CHECKING:
    from friday.core.container import Container

PREFIX = "friday:"
RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)
BUCKET = """
local rate, cap = tonumber(ARGV[1]), tonumber(ARGV[2])
local cost, now = tonumber(ARGV[3]), tonumber(ARGV[4])
local d = redis.call('hmget', KEYS[1], 't', 'ts')
local tokens = tonumber(d[1]) or cap
local ts = tonumber(d[2]) or now
tokens = math.min(cap, tokens + (now - ts) * rate)
local wait = 0
if tokens >= cost then tokens = tokens - cost else wait = (cost - tokens) / rate end
redis.call('hmset', KEYS[1], 't', tokens, 'ts', now)
redis.call('expire', KEYS[1], 3600)
return tostring(wait)
"""


class RedisLock:
    def __init__(self, client: Any, *, ttl_ms: int = 60_000, poll_s: float = 0.05) -> None:
        self.r, self.ttl_ms, self.poll_s = client, ttl_ms, poll_s

    @asynccontextmanager
    async def hold(self, key: str, *, timeout_s: float = 10.0) -> AsyncIterator[None]:
        name, token = f"{PREFIX}lock:{key}", uuid.uuid4().hex
        deadline = time.monotonic() + timeout_s
        while not await self.r.set(name, token, nx=True, px=self.ttl_ms):
            if time.monotonic() >= deadline:
                raise LockTimeout(key)
            await asyncio.sleep(self.poll_s)
        try:
            yield
        finally:
            await self.r.eval(RELEASE, 1, name, token)


class RedisCache:
    def __init__(self, client: Any) -> None:
        self.r = client

    async def get(self, key: str) -> Any | None:
        raw = await self.r.get(f"{PREFIX}cache:{key}")
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl_s: int | None = None) -> None:
        await self.r.set(f"{PREFIX}cache:{key}", json.dumps(value, default=str), ex=ttl_s)

    async def delete(self, key: str) -> None:
        await self.r.delete(f"{PREFIX}cache:{key}")


class RedisRateLimiter:
    def __init__(
        self,
        client: Any,
        rates: dict[str, float] | None = None,
        concurrency: dict[str, int] | None = None,
        *,
        burst_s: float = 1.0,
    ) -> None:
        self.r = client
        self.rates = dict(rates or {})
        self.concurrency = dict(concurrency or {})
        self.burst_s = burst_s

    async def _take(self, key: str, cost: float) -> float:
        rate = self.rates.get(key)
        if not rate:
            return 0.0
        cap = max(rate * self.burst_s, cost)
        wait = await self.r.eval(BUCKET, 1, f"{PREFIX}rl:{key}", rate, cap, cost, time.time())
        return float(wait)

    async def acquire(self, key: str, *, cost: float = 1.0, timeout_s: float | None = None) -> bool:
        wait = await self._take(key, cost)
        if wait == 0.0:
            return True
        if timeout_s is None or wait > timeout_s:
            return False
        await asyncio.sleep(wait)
        return await self._take(key, cost) == 0.0

    @asynccontextmanager
    async def slot(self, key: str, *, timeout_s: float | None = None) -> AsyncIterator[None]:
        limit = self.concurrency.get(key)
        if not limit:
            yield
            return
        name = f"{PREFIX}slots:{key}"
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            n = await self.r.incr(name)
            await self.r.expire(name, 3600)
            if n <= limit:
                break
            await self.r.decr(name)
            if deadline is None or time.monotonic() >= deadline:
                raise LockTimeout(key)
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            await self.r.decr(name)


def _client(c: Container) -> Any:
    if not c.settings.redis_url:
        raise ProviderError("redis", "FRIDAY_REDIS_URL not set")
    import redis.asyncio as aioredis

    return aioredis.from_url(c.settings.redis_url, decode_responses=True)


def build_redis_lock(c: Container) -> RedisLock:
    return RedisLock(_client(c))


def build_redis_cache(c: Container) -> RedisCache:
    return RedisCache(_client(c))


def build_redis_rate_limiter(c: Container) -> RedisRateLimiter:
    return RedisRateLimiter(
        _client(c), c.settings.provider_rate_per_s, c.settings.provider_concurrency
    )
