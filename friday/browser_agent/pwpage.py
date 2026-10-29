# ruff: noqa: E501
"""The REAL page adapter: a compact snapshot of a live Playwright page, plus a provider that reuses the site-MCP runtime
(one shared Chromium, one context per user, session cap, idle timeout, memory guard, robots, pacing, block detection).

NOTHING HERE HAS RUN ON A REAL SITE. The snapshot script, the label rules and the file-upload path are written from general
knowledge of how forms are built and are covered only by the fake pages in the tests (and a skipped-without-Playwright smoke
test). Expect to tune them on the first supervised run (docs/BROWSER_AGENT_DESIGN.md, "unverified")."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from friday.browser_agent.errors import ActionFailed, Blocked, Busy
from friday.browser_agent.observe import clip
from friday.browser_agent.types import Element, PageSnapshot, RunSpec
from friday.connectors.browser.port import BrowserError, ElementNotFound
from friday.sitemcp.guard import PaymentBlocked, PoolBusy, RateLimited, SiteBlocked
from friday.sitemcp.runtime import SessionPool

SNAPSHOT_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = (el) => (el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim();
  const labelOf = (el) => {
    const aria = el.getAttribute('aria-label'); if (aria) return aria;
    const lb = el.getAttribute('aria-labelledby'); if (lb) { const t = lb.split(' ').map(i => txt(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return txt(l); }
    const wrap = el.closest('label'); if (wrap) return txt(wrap);
    if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.getAttribute('role') === 'button') return txt(el) || el.getAttribute('title') || '';
    if (el.tagName === 'INPUT' && ['submit','button'].includes(el.type)) return el.value || '';
    return el.getAttribute('title') || el.getAttribute('name') || '';
  };
  const groupOf = (el) => { const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg); }
    const f = el.closest('form'); return f ? (f.getAttribute('aria-label') || '') : ''; };
  document.querySelectorAll('[data-fa-id]').forEach(n => n.removeAttribute('data-fa-id'));
  const sel = 'a[href], button, input, select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=combobox]';
  const out = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const tag = el.tagName.toLowerCase(); const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'hidden') continue;
    if (!vis(el) && type !== 'file') continue;
    if (++n > 120) break;
    const id = 'e' + n; el.setAttribute('data-fa-id', id);
    let role = el.getAttribute('role') || tag;
    if (tag === 'a') role = 'link';
    else if (tag === 'select') role = 'select';
    else if (tag === 'textarea') role = 'textarea';
    else if (tag === 'input') role = type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : type === 'file' ? 'file' : ['submit','button','reset','image'].includes(type) ? 'button' : 'textbox';
    else if (tag === 'button') role = 'button';
    if (role === 'combobox') role = 'select';
    const isSubmit = (tag === 'button' && (type === '' || type === 'submit') && !!el.closest('form')) || (tag === 'input' && type === 'submit');
    let href = ''; if (tag === 'a') { try { href = new URL(el.href).hostname; } catch (e) {} }
    out.push({ id, role, name: labelOf(el).slice(0, 200), type, autocomplete: el.getAttribute('autocomplete') || '',
      placeholder: el.getAttribute('placeholder') || '',
      value: (type === 'password' || type === 'file') ? '' : (el.value || '').toString().slice(0, 60),
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      checked: (type === 'checkbox' || type === 'radio') ? !!el.checked : (el.getAttribute('aria-checked') ? el.getAttribute('aria-checked') === 'true' : null),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      options: tag === 'select' ? Array.from(el.options).slice(0, 30).map(o => txt(o)) : [],
      group: groupOf(el).slice(0, 80), href_host: href, submit: isSubmit });
  }
  const captcha = !!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, [data-sitekey], #cf-challenge-running');
  return { title: document.title || '', text: (document.body ? document.body.innerText : '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, 6000), elements: out, captcha };
}
"""

MASKS = ["input[type=password]", "input[autocomplete^=cc-]", "input[name*=card i]", "input[name*=aadhaar i]", "input[name*=otp i]"]


def sel(eid: str) -> str:
    if not eid.startswith("e") or not eid[1:].isdigit():
        raise ActionFailed("bad element id")
    return f'[data-fa-id="{eid}"]'


class PlaywrightAgentPage:
    """AgentPage over a ``SafeSession`` (so payment-looking selectors/urls, robots, pacing and block detection still apply)."""

    def __init__(self, safe: Any) -> None:
        self.safe = safe

    @property
    def _page(self) -> Any:
        return self.safe.inner._page

    @staticmethod
    def _map(e: Exception) -> Exception:
        if isinstance(e, SiteBlocked):
            return Blocked(e.reason)
        if isinstance(e, RateLimited):
            return Busy("rate_limited")
        if isinstance(e, (PaymentBlocked, ElementNotFound, BrowserError)):
            return ActionFailed(type(e).__name__)
        return e

    async def _do(self, coro: Any) -> Any:
        try:
            return await coro
        except (SiteBlocked, RateLimited, PaymentBlocked, BrowserError) as e:
            raise self._map(e) from None
        except Exception as e:  # noqa: BLE001 - Playwright timeouts / detached nodes
            if type(e).__name__ in {"TimeoutError", "Error"}:
                raise ActionFailed(type(e).__name__) from None
            raise

    async def goto(self, url: str) -> None:
        await self._do(self.safe.goto(url))

    async def snapshot(self) -> PageSnapshot:
        data = await self._do(self._page.evaluate(SNAPSHOT_JS))
        els = [Element(**e) for e in data["elements"]]
        return PageSnapshot(url=self._page.url, title=clip(data.get("title", ""), 120), http_status=getattr(self.safe.inner, "last_status", None),
                            text=data.get("text", ""), elements=els, captcha=bool(data.get("captcha")))

    async def click(self, element_id: str) -> None:
        await self._do(self.safe.click(sel(element_id)))

    async def fill(self, element_id: str, value: str) -> None:
        await self._do(self.safe.fill(sel(element_id), value))

    async def select(self, element_id: str, option: str) -> None:
        await self._do(self._page.select_option(sel(element_id), label=option))

    async def check(self, element_id: str, checked: bool) -> None:
        await self._do(self._page.set_checked(sel(element_id), checked))

    async def upload(self, element_id: str, path: str) -> bool:
        """set_input_files on the <input type=file> itself (works when the input is hidden behind a drop zone, and headless).
        Then read the input back: True only when the browser reports the file attached. UNVERIFIED on real sites."""
        s = sel(element_id)
        await self._do(self._page.set_input_files(s, path))
        n = await self._do(self._page.eval_on_selector(s, "el => (el.files ? el.files.length : 0)"))
        return bool(n)

    async def press(self, key: str) -> None:
        await self._do(self._page.keyboard.press(key))

    async def wait(self, ms: int) -> None:
        await self._do(self._page.wait_for_timeout(ms))

    async def screenshot(self) -> bytes:
        masks = [self._page.locator(m) for m in MASKS]
        return await self._do(self._page.screenshot(type="jpeg", quality=45, mask=masks))

    def current_url(self) -> str:
        return str(self._page.url)


def synthetic_kb(spec: RunSpec, domains: list[str], *, min_interval_s: float = 3.0, per_user_s: float = 2.0, max_wait_s: float = 20.0) -> dict[str, Any]:
    """A knowledge-file shaped dict so the existing SessionPool / SafeSession can serve an arbitrary task."""
    return {
        "site": "agent:" + (spec.allowed_domains[0] if spec.allowed_domains else "task"),
        "domains": list(domains),
        "extra_hosts": [],
        "rate": {"min_interval_s": min_interval_s, "per_user_min_interval_s": per_user_s, "max_wait_s": max_wait_s},
        "blocked": {"selectors": ["iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[src*='turnstile']"],
                    "markers": ["verify you are human", "are you a robot", "unusual traffic from your"]},
        "checkout": {},
    }


class PoolPageProvider:
    def __init__(self, pool: SessionPool, **rate: float) -> None:
        self.pool, self.rate = pool, rate

    @contextlib.asynccontextmanager
    async def session(self, user_id: str, spec: RunSpec, domains: list[str]) -> AsyncIterator[PlaywrightAgentPage]:
        kb = synthetic_kb(spec, domains, **self.rate)
        try:
            async with self.pool.session(user_id, kb) as s:
                yield PlaywrightAgentPage(s.safe)
        except PoolBusy as e:
            raise Busy(e.reason) from None
        except SiteBlocked as e:
            raise Blocked(e.reason) from None
        except RateLimited:
            raise Busy("rate_limited") from None

    async def reopen(self, user_id: str, spec: RunSpec) -> None:
        await self.pool.close_site(user_id, "agent:" + (spec.allowed_domains[0] if spec.allowed_domains else "task"))
