# ruff: noqa: E501
"""Shared test harness: fake stores (one per skin), a hub over HtmlFakeFactory, fake clock/sleep. No network, no browser."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry
from friday.connectors.session.vault import InMemoryVaultStore, StorageVault
from friday.core.crypto import FieldCipher, LocalKeyProvider
from friday.sitemcp.fakes.htmlsession import HtmlFakeFactory
from friday.sitemcp.fakes.store import FakeStore, fake_kb
from friday.sitemcp.guard import MemoryGuard, RateLimiter, RobotsPolicy
from friday.sitemcp.hub import SiteMcpHub
from friday.sitemcp.runtime import SessionPool
from friday.sitemcp.site import SiteServer

SITES = {"zepto": "testid", "blinkit": "class", "instamart": "qa"}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@dataclass
class World:
    stores: dict[str, FakeStore]
    kbs: dict[str, dict[str, Any]]
    factory: HtmlFakeFactory
    pool: SessionPool
    hub: SiteMcpHub
    clock: Clock
    otp: OneTimeOtpChannel
    tokens: OtpTokenRegistry
    vault: StorageVault
    started: list[tuple[str, str, str]] = field(default_factory=list)
    mem: list[float | None] = field(default_factory=lambda: [4000.0])

    def stop(self) -> None:
        for s in self.stores.values():
            s.stop()


def make_world(*, max_sessions: int = 4, rate: tuple[float, float] | None = None, robots_aware: bool = False, proceed_verified: bool = True) -> World:
    stores = {site: FakeStore(skin) for site, skin in SITES.items()}
    kbs = {}
    for site, st in stores.items():
        kb = fake_kb(site, st.start(), st.skin, proceed_verified=proceed_verified)
        if rate:
            kb["rate"] = {"min_interval_s": rate[0], "per_user_min_interval_s": rate[1], "max_wait_s": 30.0}
        kbs[site] = kb
    clock = Clock()
    factory = HtmlFakeFactory()
    vault = StorageVault(InMemoryVaultStore(), FieldCipher(LocalKeyProvider({"k1": os.urandom(32)}, index_key=os.urandom(32))))
    mem: list[float | None] = [4000.0]

    async def fetch(url: str) -> tuple[int, str]:
        import asyncio
        import urllib.request

        def get() -> tuple[int, str]:
            with urllib.request.urlopen(url, timeout=5) as r:  # the local fake only
                return r.status, r.read().decode()

        return await asyncio.to_thread(get)

    robots = RobotsPolicy(fetch, clock=clock) if robots_aware else None
    pool = SessionPool(factory, vault=vault, robots=robots, limiter=RateLimiter(clock, clock.sleep),
                       memory=MemoryGuard(250.0, lambda: mem[0]), max_sessions=max_sessions, idle_s=100.0, clock=clock)
    otp, tokens = OneTimeOtpChannel(), OtpTokenRegistry()
    started: list[tuple[str, str, str]] = []
    servers = {s: SiteServer(kb, pool, otp=otp, tokens=tokens, otp_url=lambda t: f"https://friday.test/connectors/otp/{t}",
                             on_login_started=lambda u, s_, t: started.append((u, s_, t))) for s, kb in kbs.items()}
    hub = SiteMcpHub(servers, pool)
    return World(stores, kbs, factory, pool, hub, clock, otp, tokens, vault, started, mem)
