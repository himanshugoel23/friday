"""BrowserSession on Playwright + the preinstalled Chromium (headless, isolated context per user).

Playwright is an OPTIONAL dependency (``uv sync --extra browser``); nothing imports this module
unless a browser run is requested. We never run ``playwright install``: the Chromium binary comes
from PLAYWRIGHT_CHROMIUM_PATH or is found under /opt/pw-browsers/chromium-*/.
"""

from __future__ import annotations

import contextlib
import glob
import importlib.util
import os
from collections.abc import Mapping, Sequence
from typing import Any

from friday.connectors.browser.port import BrowserError, ElementNotFound

CHROMIUM_ENV = "PLAYWRIGHT_CHROMIUM_PATH"
_SEARCH = (
    "/opt/pw-browsers/chromium-*/chrome-linux*/chrome",
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux*/headless_shell",
)

_ROWS_JS = """
(els, fields) => els.map((el) => {
  const out = {text: (el.innerText || el.textContent || '').trim()};
  for (const [name, spec] of Object.entries(fields)) {
    const at = spec.lastIndexOf('@');
    const sel = at >= 0 ? spec.slice(0, at) : spec;
    const attr = at >= 0 ? spec.slice(at + 1) : null;
    const node = sel ? el.querySelector(sel) : el;
    if (!node) { out[name] = ''; continue; }
    out[name] = attr ? (node.getAttribute(attr) || '')
                     : (node.innerText || node.textContent || '').trim();
  }
  return out;
})
"""


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def find_chromium() -> str | None:
    env = os.environ.get(CHROMIUM_ENV)
    if env and os.path.exists(env):
        return env
    for pattern in _SEARCH:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def browser_available() -> bool:
    return playwright_installed() and find_chromium() is not None


class PlaywrightBrowserSession:
    """One user's isolated browser context. Build with ``await PlaywrightBrowserSession.open()``."""

    def __init__(
        self, pw: Any, browser: Any, context: Any, page: Any, timeout_ms: int, tracing: bool = False
    ) -> None:
        self._pw, self._browser, self._context, self._page = pw, browser, context, page
        self._timeout = timeout_ms
        self._tracing = tracing

    @classmethod
    async def open(
        cls,
        *,
        storage_state: dict[str, Any] | None = None,
        allowed_hosts: set[str] | None = None,
        timeout_ms: int = 8000,
        trace: bool = False,
    ) -> PlaywrightBrowserSession:
        """``storage_state``: a previously exported session (callers keep it encrypted).
        ``allowed_hosts``: when set, every request to another host is aborted (tests use it)."""
        if not playwright_installed():
            raise BrowserError("playwright is not installed (uv sync --extra browser)")
        exe = find_chromium()
        if exe is None:
            raise BrowserError(f"no Chromium found; set {CHROMIUM_ENV}")
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        try:
            args = ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
            browser = await pw.chromium.launch(executable_path=exe, headless=True, args=args)
            context = await browser.new_context(storage_state=storage_state)  # fresh per user
            context.set_default_timeout(timeout_ms)
            if allowed_hosts is not None:
                hosts = set(allowed_hosts)

                async def _guard(route: Any) -> None:
                    host = route.request.url.split("/")[2].split(":")[0] if "//" in (
                        route.request.url) else ""
                    if route.request.url.startswith(("data:", "about:")) or host in hosts:
                        await route.continue_()
                    else:
                        await route.abort()

                await context.route("**/*", _guard)
            if trace:
                await context.tracing.start(screenshots=True, snapshots=True)
            page = await context.new_page()
        except Exception:
            await pw.stop()
            raise
        return cls(pw, browser, context, page, timeout_ms, trace)

    async def goto(self, url: str) -> None:
        await self._page.goto(url)

    async def fill(self, selector: str, value: str) -> None:
        await self._wrap(self._page.fill(selector, value), selector)

    async def click(self, selector: str) -> None:
        await self._wrap(self._page.click(selector), selector)

    async def text(self, selector: str) -> str:
        return str(await self._wrap(self._page.inner_text(selector), selector)).strip()

    async def query_all(
        self, selector: str, fields: Mapping[str, str] | None = None
    ) -> list[dict[str, str]]:
        return await self._page.eval_on_selector_all(selector, _ROWS_JS, dict(fields or {}))

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        await self._wrap(self._page.wait_for_selector(selector, timeout=timeout_ms), selector)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        masks = [self._page.locator(sel) for sel in mask_selectors]
        return await self._page.screenshot(mask=masks)

    async def stop_trace(self, path: str) -> bool:
        """Write the Playwright trace zip (if tracing was on). The trace holds page content, so it
        is only ever served behind the watch token."""
        if not self._tracing:
            return False
        await self._context.tracing.stop(path=path)
        self._tracing = False
        return True

    async def storage_state(self) -> dict[str, Any]:
        """Cookies/localStorage for session reuse. SECRET: encrypt before storing."""
        return await self._context.storage_state()

    async def close(self) -> None:
        for closer in (self._context.close, self._browser.close, self._pw.stop):
            with contextlib.suppress(Exception):  # best-effort teardown
                await closer()

    @staticmethod
    async def _wrap(coro: Any, selector: str) -> Any:
        try:
            return await coro
        except Exception as e:  # noqa: BLE001 - map Playwright timeouts to our error
            if type(e).__name__ in {"TimeoutError", "Error"}:
                raise ElementNotFound(f"selector not found: {selector}") from None
            raise
