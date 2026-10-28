# ruff: noqa: E501
"""A BrowserSession over plain HTTP + the tiny DOM (no JavaScript). Own cookie jar per session = real isolation between users.
Clicks follow links (``a[href]``, ``[data-href]``) and submit forms (``button`` / ``input[type=submit]`` inside a form)."""

from __future__ import annotations

import asyncio
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from friday.connectors.browser.fake import PNG_1PX
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.browser.port import ElementNotFound, NetworkBlocked
from friday.sitemcp.fakes.dom import Node, inner_text, parse_html, select


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:  # we follow redirects ourselves (policy check on each hop)
        return None


class HtmlFakeSession:
    def __init__(self, policy: NetworkPolicy, storage_state: dict[str, Any] | None = None) -> None:
        self.policy = policy
        self.jar = http.cookiejar.CookieJar()
        for c in (storage_state or {}).get("cookies", []):
            self.jar.set_cookie(http.cookiejar.Cookie(0, c["name"], c["value"], None, False, c.get("domain", "127.0.0.1"), True, False,
                                                      c.get("path", "/"), True, False, None, True, None, None, {}))
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)
        self.url = "about:blank"
        self.doc: Node = parse_html("")
        self.last_status: int | None = None
        self.values: dict[int, str] = {}  # id(node) -> filled value
        self.closed = False
        self.requests: list[str] = []

    # ---- http
    def _fetch(self, url: str, data: bytes | None) -> tuple[int, str, str | None]:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "FridayTestBrowser/1"})
        try:
            with self._opener.open(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307):
                return e.code, "", urllib.parse.urljoin(url, e.headers.get("Location", "/"))
            return e.code, e.read().decode("utf-8", "replace"), None

    async def _load(self, url: str, data: bytes | None = None) -> None:
        for _ in range(5):
            reason = self.policy.check(url)
            if reason:
                raise NetworkBlocked(reason)
            self.requests.append(urllib.parse.urlsplit(url).path)
            status, body, loc = await asyncio.to_thread(self._fetch, url, data)
            if loc:
                url, data = loc, None
                continue
            self.url, self.last_status, self.doc, self.values = url, status, parse_html(body), {}
            return
        raise NetworkBlocked("too many redirects")

    async def goto(self, url: str) -> None:
        await self._load(url)

    # ---- dom
    def _first(self, selector: str) -> Node:
        found = select(self.doc, selector)
        if not found:
            raise ElementNotFound(f"selector not found: {selector}")
        return found[0]

    async def fill(self, selector: str, value: str) -> None:
        self.values[id(self._first(selector))] = value

    async def click(self, selector: str) -> None:
        n = self._first(selector)
        href = n.attrs.get("href") or n.attrs.get("data-href")
        if n.tag == "a" or (href and n.tag != "button"):
            await self._load(urllib.parse.urljoin(self.url, href or ""))
            return
        form = n.parent
        while form is not None and form.tag != "form":
            form = form.parent
        if form is None:
            if href:
                await self._load(urllib.parse.urljoin(self.url, href))
            return
        pairs: list[tuple[str, str]] = []
        for inp in (x for x in form.walk() if x.tag in ("input", "select", "textarea")):
            name = inp.attrs.get("name")
            if name and inp.attrs.get("type") not in ("submit", "button"):
                pairs.append((name, self.values.get(id(inp), inp.attrs.get("value", ""))))
        if n.attrs.get("name"):
            pairs.append((n.attrs["name"], n.attrs.get("value", "")))
        action = urllib.parse.urljoin(self.url, form.attrs.get("action", "") or self.url)
        body = urllib.parse.urlencode(pairs)
        if form.attrs.get("method", "get").lower() == "post":
            await self._load(action, body.encode())
        else:
            await self._load(action.split("?")[0] + "?" + body)

    async def text(self, selector: str) -> str:
        return inner_text(self._first(selector))

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None) -> list[dict[str, str]]:
        out = []
        for row in select(self.doc, selector):
            d = {"text": inner_text(row)}
            for name, spec in (fields or {}).items():
                sel, _, attr = spec.rpartition("@") if "@" in spec else (spec, "", "")
                node = (select(row, sel)[:1] or [None])[0] if sel else row
                if node is None:
                    d[name] = ""
                elif attr:
                    d[name] = node.attrs.get(attr, "")
                else:
                    d[name] = inner_text(node)
            out.append(d)
        return out

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        self._first(selector)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG_1PX

    async def storage_state(self) -> dict[str, Any]:
        return {"cookies": [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.jar], "origins": []}

    def current_url(self) -> str:
        return self.url

    async def close(self) -> None:
        self.closed = True


class HtmlFakeFactory:
    """BrowserFactory for tests: one HtmlFakeSession (own cookie jar) per open(); tracks live sessions."""

    def __init__(self, extra_hosts: Sequence[str] = ()) -> None:
        self.sessions: list[HtmlFakeSession] = []
        self.extra_hosts = list(extra_hosts)
        self.opened = 0

    async def open(self, kb: dict[str, Any], storage_state: dict[str, Any] | None) -> HtmlFakeSession:
        policy = NetworkPolicy.for_hosts([*kb["domains"], *self.extra_hosts], allow_loopback=True)
        s = HtmlFakeSession(policy, storage_state)
        self.sessions.append(s)
        self.opened += 1
        return s

    def live(self) -> int:
        return sum(1 for s in self.sessions if not s.closed)

    async def aclose(self) -> None:
        for s in self.sessions:
            s.closed = True
