"""Shared httpx plumbing for voice vendors: one client per provider, normalised
errors (``ProviderError`` with ``retryable``), a small retry loop, no secrets in logs."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger

log = get_logger(__name__)

_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


class VendorHTTP:
    def __init__(
        self,
        provider: str,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout_s: float = 20.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.retries = retries
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout_s, transport=transport
        )

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = await self._client.request(method, url, **kw)
            except httpx.HTTPError as e:
                last = ProviderError(
                    self.provider, f"network error: {type(e).__name__}", retryable=True
                )
            else:
                if resp.status_code < 400:
                    return resp
                retryable = resp.status_code in _RETRYABLE
                last = ProviderError(
                    self.provider,
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                    retryable=retryable,
                )
                if not retryable:
                    raise last
            if attempt < self.retries:
                await asyncio.sleep(0.25 * (2**attempt))
        assert last is not None
        raise last

    async def aclose(self) -> None:
        await self._client.aclose()
