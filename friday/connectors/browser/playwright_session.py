"""BrowserSession on Playwright + the preinstalled Chromium (headless, isolated context per user).

Playwright is an OPTIONAL dependency (``uv sync --extra browser``); nothing imports this module
unless a browser run is requested. We never run ``playwright install``: the Chromium binary comes
from PLAYWRIGHT_CHROMIUM_PATH or is found under /opt/pw-browsers/chromium-*/.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import importlib.util
import os
from collections.abc import Mapping, Sequence
from typing import Any

from friday.connectors.browser.policy import LimitCounter, NetworkPolicy
from friday.connectors.browser.port import BrowserError, ElementNotFound

VIEWPORT = (1280, 800)

CHROMIUM_ENV = "PLAYWRIGHT_CHROMIUM_PATH"
_SEARCH = (
    "/opt/pw-browsers/chromium-*/chrome-linux*/chrome",
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux*/headless_shell",
    # `playwright install chromium` run as the service user (the droplet): ~/.cache/ms-playwright
    "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome",
    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux*/headless_shell",
    "/home/friday/.cache/ms-playwright/chromium-*/chrome-linux*/chrome",
    "/home/friday/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux*/headless_shell",
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
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    patterns = list(_SEARCH)
    if custom:
        patterns += [
            f"{custom}/chromium-*/chrome-linux*/chrome",
            f"{custom}/chromium_headless_shell-*/chrome-linux*/headless_shell",
        ]
    for pattern in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pattern)))
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
        policy: NetworkPolicy | None = None,
        counter: LimitCounter | None = None,
        headless: bool = True,
        display: str | None = None,
        resolver: Any = None,
    ) -> PlaywrightBrowserSession:
        """``storage_state``: a previously exported session (callers keep it encrypted).
        ``policy``: default-deny network policy enforced on EVERY request (also sub-resources and
        popups). ``allowed_hosts`` is the older shorthand (loopback allowed, tests/demos).
        ``headless=False`` + ``display`` runs headed Chromium in a virtual display (Xvfb).
        ``counter`` receives page / download / blocked-request events."""
        if not playwright_installed():
            raise BrowserError("playwright is not installed (uv sync --extra browser)")
        exe = find_chromium()
        if exe is None:
            raise BrowserError(f"no Chromium found; set {CHROMIUM_ENV}")
        from playwright.async_api import async_playwright

        if policy is None and allowed_hosts is not None:
            policy = NetworkPolicy.for_hosts(allowed_hosts, allow_loopback=True)
        pw = await async_playwright().start()
        try:
            args = ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
            args += ["--disable-extensions", "--disable-sync", "--no-first-run"]
            env = {**os.environ, "DISPLAY": display} if (display and not headless) else None
            browser = await pw.chromium.launch(
                executable_path=exe, headless=headless, args=args, env=env)
            context = await browser.new_context(  # fresh per task, never shared
                storage_state=storage_state, accept_downloads=False, service_workers="block",
                viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]}, permissions=[])
            context.set_default_timeout(timeout_ms)
            if policy is not None:
                await _install_guard(context, policy, counter, resolver)
            if counter is not None:
                _install_counters(context, counter)
            if trace:
                await context.tracing.start(screenshots=True, snapshots=True)
            page = await context.new_page()
        except Exception:
            await pw.stop()
            raise
        return cls(pw, browser, context, page, timeout_ms, trace)

    # ---- takeover / live view support (used only by friday.connectors.session)
    def viewport(self) -> tuple[int, int]:
        return VIEWPORT

    def current_url(self) -> str:
        return str(self._page.url)

    async def pointer_click(self, x: int, y: int) -> None:
        await self._page.mouse.click(x, y)

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text)

    async def press_key(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def scroll(self, dy: int) -> None:
        await self._page.mouse.wheel(0, dy)

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


async def _install_guard(
    context: Any, policy: NetworkPolicy, counter: LimitCounter | None, resolver: Any
) -> None:
    """Abort every request the policy does not allow. ``resolver(host) -> [ip]`` (optional) adds
    the DNS-rebinding check; omitted in offline tests."""
    cache: dict[str, str | None] = {}

    async def _verdict(url: str) -> str | None:
        reason = policy.check(url)
        if reason or resolver is None:
            return reason
        host = url.split("/")[2].split(":")[0] if "//" in url else ""
        if host not in cache:
            try:
                cache[host] = policy.check_resolved(host, await resolver(host))
            except Exception:  # noqa: BLE001 - unresolvable: fail closed
                cache[host] = "host did not resolve"
        return cache[host]

    async def _guard(route: Any) -> None:
        url = route.request.url
        reason = await _verdict(url)
        if reason is None:
            await route.continue_()
            return
        if counter is not None:
            counter.blocked(url, reason)
        await route.abort()

    await context.route("**/*", _guard)
    with contextlib.suppress(Exception):  # websockets: older Playwright has no route_web_socket

        async def _ws(ws: Any) -> None:
            reason = policy.check(ws.url)
            if reason is None:
                ws.connect_to_server()
            else:
                if counter is not None:
                    counter.blocked(ws.url, reason)
                await ws.close()

        await context.route_web_socket("**/*", _ws)


def _install_counters(context: Any, counter: LimitCounter) -> None:
    def _download(dl: Any) -> None:
        counter.note_download()  # accept_downloads=False: the file itself is always discarded

    def _new_page(page: Any) -> None:
        if not counter.note_page():
            asyncio.ensure_future(_close_quietly(page))
            return
        page.on("download", _download)
        page.on("close", lambda _p: counter.page_closed())

    context.on("page", _new_page)


async def _close_quietly(page: Any) -> None:
    with contextlib.suppress(Exception):
        await page.close()
