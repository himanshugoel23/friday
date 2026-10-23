"""Default-deny network policy and resource limits for one browser task.

The allow-list is per connector (exact host or ``*.example.com``). Everything else is blocked:
other hosts, non-http(s) schemes, private / loopback / link-local ranges and cloud metadata IPs
(SSRF). ``allow_loopback`` exists for tests against the local fake site and is never set in
production code paths. An EMPTY allow-list blocks everything.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_ALWAYS_BLOCKED_HOSTS = frozenset({"metadata.google.internal", "metadata", "instance-data"})


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _is_private(host: str) -> bool | None:
    """True/False for an IP literal, None for a name."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    return not ip.is_global


@dataclass(frozen=True)
class NetworkPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    allow_loopback: bool = False  # tests only: lets 127.0.0.1 / localhost through if listed

    @classmethod
    def for_hosts(cls, hosts: Iterable[str], *, allow_loopback: bool = False) -> NetworkPolicy:
        return cls(frozenset(h.lower() for h in hosts), allow_loopback)

    def _host_listed(self, host: str) -> bool:
        for pat in self.allowed_hosts:
            if pat == host or (pat.startswith("*.") and host.endswith(pat[1:])):
                return True
        return False

    def check(self, url: str) -> str | None:
        """None if the request may go out, else a short reason (never page content)."""
        if url == "about:blank" or url.startswith("data:"):
            return None
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https", "ws", "wss"):
            return f"scheme {parts.scheme or '?'} not allowed"
        host = _host_of(url)
        if not host or host in _ALWAYS_BLOCKED_HOSTS:
            return "host not allowed"
        loopback = _is_loopback(host)
        private = _is_private(host)
        if (private is True or host == "localhost") and not (
            self.allow_loopback and loopback and self._host_listed(host)
        ):
            return "private or local address blocked"
        if not self._host_listed(host):
            return f"host {host} not in allow-list"
        return None

    def check_resolved(self, host: str, addresses: Iterable[str]) -> str | None:
        """DNS-rebinding guard: a listed name that resolves to a private address is blocked."""
        for a in addresses:
            if _is_private(a) is True and not (self.allow_loopback and _is_loopback(a)):
                return f"{host} resolves to a private address"
        return None


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


@dataclass(frozen=True)
class ResourceLimits:
    timeout_ms: int = 8000  # per action
    max_seconds: float = 600.0  # whole task, then the session is closed
    max_pages: int = 3  # open tabs/popups
    max_downloads: int = 0  # downloads are off by default


@dataclass
class LimitCounter:
    """Shared between the backend (which sees pages/downloads/requests) and the manager."""

    limits: ResourceLimits
    pages: int = 0
    downloads: int = 0
    tripped: str | None = None
    violations: list[str] = field(default_factory=list)
    on_violation: Callable[[str, str], None] | None = None  # (kind, detail)

    def trip(self, what: str) -> None:
        self.tripped = self.tripped or what
        self._emit("limit", what)

    def blocked(self, url: str, reason: str) -> None:
        host = _host_of(url) or "?"
        self.violations.append(f"{host}: {reason}")
        self._emit("network_blocked", f"{host}: {reason}")

    def note_page(self) -> bool:
        self.pages += 1
        if self.pages > self.limits.max_pages:
            self.trip("max_pages")
            return False
        return True

    def page_closed(self) -> None:
        self.pages = max(0, self.pages - 1)

    def note_download(self) -> bool:
        self.downloads += 1
        if self.downloads > self.limits.max_downloads:
            self.trip("max_downloads")
            return False
        return True

    def _emit(self, kind: str, detail: str) -> None:
        if self.on_violation:
            self.on_violation(kind, detail)
