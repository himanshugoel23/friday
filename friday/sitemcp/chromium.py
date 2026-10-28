# ruff: noqa: E501
"""The real browser factory: ONE shared Chromium process, one isolated context (own cookies) per (user, site).

Playwright is an optional dependency (``uv sync --extra browser``) and the browser binaries plus Xvfb are NOT installed on the
droplet yet (see docs/SITE_MCP_DESIGN.md). Nothing here is imported unless a real run is requested; tests never launch it.
Memory: launched lazily, closed by ``aclose`` (the live probe closes it right after the run), blocks images / media / fonts.
We do not touch the user agent, navigator properties, webdriver flags or any stealth setting: a normal browser, as is.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from friday.connectors.browser.playwright_session import (
    VIEWPORT,
    PlaywrightBrowserSession,
    _install_guard,
    find_chromium,
    playwright_installed,
)
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.browser.port import BrowserError


def allowed_hosts(kb: dict[str, Any]) -> list[str]:
    """Default deny: the site's own domains, their subdomains, and the knowledge file's extra_hosts. Nothing else."""
    return [*kb["domains"], *(f"*.{d}" for d in kb["domains"]), *kb.get("extra_hosts", [])]


class ContextSession(PlaywrightBrowserSession):
    """One context on the shared browser. ``close`` closes only the context, never the shared browser."""

    last_status: int | None = None

    async def goto(self, url: str) -> None:
        resp = await self._page.goto(url, wait_until="domcontentloaded")
        self.last_status = resp.status if resp is not None else None

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._context.close()


class SharedChromium:
    def __init__(self, *, headless: bool = True, display: str | None = None, timeout_ms: int = 12000) -> None:
        self.headless, self.display, self.timeout_ms = headless, display, timeout_ms
        self._pw: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()

    @staticmethod
    def available() -> bool:
        return playwright_installed() and find_chromium() is not None

    async def _ensure(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if not playwright_installed():
                raise BrowserError("playwright is not installed (uv sync --extra browser)")
            exe = find_chromium()
            if exe is None:
                raise BrowserError("no Chromium found (playwright install chromium)")
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            args = ["--disable-extensions", "--disable-sync", "--no-first-run", "--disable-dev-shm-usage", "--disable-gpu"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                args.append("--no-sandbox")
            env = {**os.environ, "DISPLAY": self.display} if (self.display and not self.headless) else None
            self._browser = await self._pw.chromium.launch(executable_path=exe, headless=self.headless, args=args, env=env)
            return self._browser

    async def open(self, kb: dict[str, Any], storage_state: dict[str, Any] | None) -> ContextSession:
        browser = await self._ensure()
        context = await browser.new_context(storage_state=storage_state, accept_downloads=False, service_workers="block",
                                            viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]}, permissions=[], locale="en-IN")
        context.set_default_timeout(self.timeout_ms)
        await _install_guard(context, NetworkPolicy.for_hosts(allowed_hosts(kb)), None, None)

        async def _light(route: Any) -> None:  # save RAM and bandwidth: no images / media / fonts
            if route.request.resource_type in ("image", "media", "font"):
                await route.abort()
            else:
                await route.fallback()

        await context.route("**/*", _light)
        page = await context.new_page()
        return ContextSession(self._pw, browser, context, page, self.timeout_ms)

    async def aclose(self) -> None:
        for closer in (lambda: self._browser.close() if self._browser else None, lambda: self._pw.stop() if self._pw else None):
            with contextlib.suppress(Exception):
                r = closer()
                if r is not None:
                    await r
        self._browser = self._pw = None
