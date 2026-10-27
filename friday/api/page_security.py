"""Small guards shared by the one-time secure pages (saved login, login code).

* ``PageLimiter``: an in-memory sliding window per client. Each request counts against
  ``max_hits``;
  a request for a token that does not exist counts against the stricter ``max_misses`` (someone
  guessing links). Over the limit -> HTTP 429 and no work done.
* ``client_key``: the caller address. Behind Caddy / Docker the TCP peer is the proxy (private or
  loopback address), so the LAST ``X-Forwarded-For`` entry (the one our own proxy appended) is used
  then; from any public peer the header is ignored (it could be forged).
* ``same_site``: Origin / Sec-Fetch-Site check for form posts.
"""

from __future__ import annotations

import ipaddress
import time
from collections import deque
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

WINDOW_SECONDS = 600.0
MAX_HITS = 40
MAX_MISSES = 10
_MAX_KEYS = 5000


def client_key(request: Any) -> str:
    peer = request.client.host if request.client else ""
    try:
        trusted = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        trusted = False
    if trusted:
        xff = request.headers.get("x-forwarded-for", "")
        last = xff.split(",")[-1].strip() if xff else ""
        if last:
            return last
    return peer or "unknown"


class PageLimiter:
    def __init__(self, *, window: float = WINDOW_SECONDS, max_hits: int = MAX_HITS,
                 max_misses: int = MAX_MISSES, clock: Callable[[], float] = time.monotonic) -> None:
        self._window, self._max_hits, self._max_misses, self._clock = (
            window, max_hits, max_misses, clock)
        self._hits: dict[str, deque[float]] = {}
        self._misses: dict[str, deque[float]] = {}

    def _count(self, table: dict[str, deque[float]], key: str, add: bool) -> int:
        now = self._clock()
        q = table.get(key)
        if q is None:
            if len(table) >= _MAX_KEYS:  # bound memory: forget the oldest client
                table.pop(next(iter(table)))
            q = table[key] = deque()
        while q and q[0] <= now - self._window:
            q.popleft()
        if add:
            q.append(now)
        return len(q)

    def allow(self, key: str) -> bool:
        """Count this request; False once the client is over either limit."""
        if self._count(self._misses, key, False) >= self._max_misses:
            return False
        return self._count(self._hits, key, True) <= self._max_hits

    def miss(self, key: str) -> None:
        """A request named a token that does not exist (or is spent)."""
        self._count(self._misses, key, True)


def same_site(headers: Any) -> bool:
    """False for a cross-site form post (Origin on another host, or Sec-Fetch-Site says so)."""
    sfs = headers.get("sec-fetch-site")
    if sfs and sfs not in ("same-origin", "none"):
        return False
    origin = headers.get("origin")
    return not (origin and origin != "null" and urlsplit(origin).netloc != headers.get("host", ""))
