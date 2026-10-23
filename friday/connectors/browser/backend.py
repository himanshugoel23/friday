"""Browser backends behind one interface: local Playwright now, a cloud-browser provider later.

``select_backend(name)`` picks one. A cloud provider (Browserbase, Steel, ...) is added by
registering a factory with ``register_cloud_provider``; nothing else in Friday changes, because
connectors only see ``BrowserSession`` and the runtime only sees ``LiveBrowserSession``. A cloud
backend MUST honour the same ``SessionSpec`` (policy, limits, no downloads, CAPTCHA solving OFF)
and must wrap any provider live-view URL behind our own token (see docs/PRIVATE_BROWSER_RUNTIME.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from friday.connectors.browser.fake import FakeLiveSession
from friday.connectors.browser.policy import LimitCounter, NetworkPolicy, ResourceLimits
from friday.connectors.browser.port import BrowserError, LiveBrowserSession


class BackendUnavailable(BrowserError):
    """The chosen backend cannot run here (not installed, not configured)."""


@dataclass
class SessionSpec:
    user_id: str
    site: str
    task_id: str
    policy: NetworkPolicy
    limits: ResourceLimits
    counter: LimitCounter
    storage_state: dict[str, Any] | None = None


class BrowserBackend(Protocol):
    name: str

    async def open(self, spec: SessionSpec) -> LiveBrowserSession: ...


class LocalPlaywrightBackend:
    """Chromium on our own server. ``headed=True`` + ``display=":99"`` = headed Chromium inside a
    virtual display (``xvfb-run`` / ``Xvfb :99``), which some sites treat more kindly than
    headless. Never calls ``playwright install``."""

    name = "local"

    def __init__(self, *, headed: bool = False, display: str | None = None,
                 resolve_dns: bool = False) -> None:
        self.headed, self.display, self.resolve_dns = headed, display, resolve_dns

    async def open(self, spec: SessionSpec) -> LiveBrowserSession:
        from friday.connectors.browser.playwright_session import PlaywrightBrowserSession

        resolver = _dns_resolver if self.resolve_dns else None
        return await PlaywrightBrowserSession.open(  # type: ignore[return-value]
            storage_state=spec.storage_state, policy=spec.policy, counter=spec.counter,
            timeout_ms=spec.limits.timeout_ms, headless=not self.headed,
            display=self.display, resolver=resolver)


async def _dns_resolver(host: str) -> list[str]:
    import asyncio
    import socket

    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(i[4][0]) for i in infos]


class FakeBackend:
    """Test backend: every ``open`` returns a ``FakeLiveSession`` (kept in ``self.sessions``)."""

    name = "fake"

    def __init__(self) -> None:
        self.sessions: list[FakeLiveSession] = []

    async def open(self, spec: SessionSpec) -> LiveBrowserSession:
        s = FakeLiveSession(spec.storage_state, spec.policy, spec.counter)
        self.sessions.append(s)
        return s  # type: ignore[return-value]


_CLOUD: dict[str, Callable[[], BrowserBackend]] = {}


def register_cloud_provider(provider: str, factory: Callable[[], BrowserBackend]) -> None:
    _CLOUD[provider.lower()] = factory


def select_backend(
    name: str = "local", *, provider: str = "", headed: bool = False, display: str | None = None,
    resolve_dns: bool = False,
) -> BrowserBackend:
    n = name.lower()
    if n == "local":
        return LocalPlaywrightBackend(headed=headed, display=display, resolve_dns=resolve_dns)
    if n == "fake":
        return FakeBackend()
    if n == "cloud":
        factory = _CLOUD.get(provider.lower())
        if factory is None:
            raise BackendUnavailable(
                f"no cloud browser provider registered for {provider!r}; "
                "register one with register_cloud_provider()")
        return factory()
    raise BackendUnavailable(f"unknown browser backend {name!r}")
