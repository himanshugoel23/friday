# ruff: noqa: E501
"""Shared building blocks of the train, shopping and swiggy packages (no import of sites/adapters.py,
so ``sites/adapters.py`` may import these packages without a cycle).

* ``HandOver``: captcha / booking-window events. We stop and give the user the link; we never
  solve, wait out or retry around them.
* ``AddOnStuck``: a pre-ticked extra (insurance, protection plan, trial, tip) could not be unticked.
* ``allowed_hosts``: the network allow-list of a site comes from ``catalog.policy_hosts(key)``.
* ``build_kit``: the guarded session (domain, secret and payment rules, injection reader, verifier).
* ``ScriptedConnector``: goto / text / money helpers and the login-code step (one-time channel only).
* ``read_payment``: the QR / UPI hand-off. Friday never pays.
* ``SimSession``: the generic in-process BrowserSession the FAKE sites are built on.
All selectors in the packages target the FAKE sites only; real sites are UNVERIFIED.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from pydantic import ValidationError

from friday.connectors import catalog
from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.contract import (
    ConnectorError,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    PaymentHandoff,
    TotalsMismatch,
    rupees_to_paise,
)
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.scrub import scrub_text
from friday.connectors.sites.errors import SiteBlocked
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.injection import strip_injection
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import SiteSafety
from friday.connectors.sites.verifier import Expect, Verifier

TEST_HOSTS = frozenset({"fake.invalid", "127.0.0.1", "localhost"})
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
Sleep = Callable[[float], Awaitable[None]]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ------------------------------------------------------------------ errors
class HandOver(SiteBlocked):
    """A moment only the user can handle (captcha, booking window not open). Subclass of
    ``SiteBlocked`` so BrowserFlow stops and gives the link. ``reason`` is a fixed word."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"handover: {reason}")
        self.reason = reason


class AddOnStuck(ConnectorError):
    """A pre-ticked extra could not be unticked. ``names`` are page labels (cleaned), ``amount_paise``
    is what they add to the total. The message never carries page text."""

    def __init__(self, names: list[str], amount_paise: int = 0, quote: Any = None) -> None:
        super().__init__("a pre-selected extra could not be removed")
        self.names, self.amount_paise, self.quote = names, amount_paise, quote


# ------------------------------------------------------------------ small helpers
def allowed_hosts(site_key: str, extra: frozenset[str] = frozenset()) -> frozenset[str]:
    """Hosts from the catalog (``*.x`` becomes ``x``: SiteSafety matches subdomains) + test hosts."""
    hosts = {h[2:] if h.startswith("*.") else h for h in catalog.policy_hosts(site_key)}
    return frozenset(hosts) | TEST_HOSTS | extra


def clean(text: str, limit: int = 90) -> str:
    """Page text for display: instruction-like sentences removed, scrubbed, one line, short."""
    out, _ = strip_injection(text or "")
    return re.sub(r"\s+", " ", scrub_text(out)).strip()[:limit]


def safe_id(value: str, what: str) -> str:
    if not SAFE_ID.match(value or ""):
        raise ConnectorError(f"unexpected {what} format")
    return value


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{(\w+)\}", template)
    rx = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^'\"\\]]+)" for i, p in enumerate(parts))
    return re.compile(rf"^{rx}$")


def build_kit(inner: BrowserSession, *, site_key: str, selectors: Mapping[str, str],
              alternates: Mapping[str, list[str]], irreversible: frozenset[str], task_id: str,
              repairer: SelectorRepairer | None = None,
              expect: Mapping[str, tuple[str, ...]] | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    """``expect`` maps an action key to the keys that must be on the page afterwards."""
    safety = SiteSafety(allowed_hosts(site_key, extra_hosts), irreversible)
    log = RepairLog()
    loc = ElementLocator(dict(selectors), dict(alternates), repairer=repairer, log=log,
                         task_id=task_id, irreversible=irreversible)
    exp: dict[str, Expect] = {}
    for key, present in (expect or {}).items():
        e = Expect(present=tuple(selectors[p] for p in present))
        for sel in (selectors[key], *alternates.get(key, [])):
            exp[sel] = e
    return AgentKit(GuardedSession(inner, safety, loc, PageReader(), Verifier(exp)), safety, loc, log)


async def read_payment(s: BrowserSession, sel: Mapping[str, str], expected_paise: int) -> PaymentHandoff:
    """Read the pay page the user finishes on: amount must equal the approved total; QR / UPI only."""
    try:
        amount = rupees_to_paise(await s.text(sel["pay_amount"]))
        merchant = clean(await s.text(sel["pay_merchant"]), 60)
    except (ElementNotFound, ValueError):
        raise LayoutChanged("payment page could not be read") from None
    if amount != expected_paise:
        raise TotalsMismatch("payment page amount differs from the approved total")
    ref = await s.query_all(sel["pay_order_ref"])
    qr = None
    for r in await s.query_all(sel["pay_qr"], {"src": "@src"}):
        if r.get("src", "").startswith("data:image/png;base64,"):
            try:
                qr = base64.b64decode(r["src"].split(",", 1)[1], validate=True)
            except ValueError:
                qr = None
    link = None
    for r in await s.query_all(sel["pay_upi_link"], {"href": "@href"}):
        href = r.get("href", "")
        if href.startswith("upi://pay"):
            am = parse_qs(urlsplit(href).query).get("am")
            if am and rupees_to_paise(am[0]) != amount:
                raise TotalsMismatch("UPI link amount differs from the approved total")
            link = href
    if qr is None and link is None:
        raise LayoutChanged("no QR or UPI link on the payment page")
    try:
        return PaymentHandoff(kind="qr" if qr else "upi_intent", amount_paise=amount,
                              merchant=merchant or "merchant",
                              order_ref=(clean(ref[0]["text"], 40) if ref else None),
                              qr_png=qr, upi_link=link)
    except ValidationError:
        raise LayoutChanged("payment page data failed validation") from None


# ------------------------------------------------------------------ connector base
class ScriptedConnector:
    """goto / text / money helpers and the login-code step. Subclasses set ``P`` (paths),
    ``S`` (selectors) and ``F`` (row fields). The code comes only from the one-time channel."""

    P: Mapping[str, str] = {}
    S: Mapping[str, str] = {}
    F: Mapping[str, Mapping[str, str]] = {}
    backend = "scripted_browser"

    def __init__(self, session: BrowserSession, *, base_url: str, task_id: str,
                 otp_channel: OneTimeOtpChannel | None = None, phone: str | None = None,
                 on_code_wait: Callable[[], Awaitable[None]] | None = None,
                 otp_wait_s: float = 120.0, poll_s: float = 0.5, sleep: Sleep = asyncio.sleep,
                 ) -> None:
        self._s, self._base, self._task = session, base_url.rstrip("/"), task_id
        self._otp, self._phone, self._on_wait = otp_channel, phone, on_code_wait
        self._otp_wait_s, self._poll_s, self._sleep = otp_wait_s, poll_s, sleep

    def __repr__(self) -> str:
        return f"{type(self).__name__}(task_id={self._task!r})"

    async def _goto(self, key: str, **params: str) -> None:
        await self._s.goto(self._base + self.P[key].format(
            **{k: quote(str(v), safe="") for k, v in params.items()}))

    async def _text(self, key: str) -> str:
        try:
            return await self._s.text(self.S[key])
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _money(self, key: str) -> int:
        try:
            return rupees_to_paise(await self._text(key))
        except ValueError:
            raise LayoutChanged(f"'{key}' is not a money amount") from None

    async def _rows(self, key: str, fields: str | None = None) -> list[dict[str, str]]:
        return await self._s.query_all(self.S[key], self.F.get(fields or key))

    async def _present(self, key: str) -> bool:
        return bool(await self._s.query_all(self.S[key]))

    async def _wait(self, key: str, ms: int = 3000) -> None:
        try:
            await self._s.wait_for(self.S[key], ms)
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _phone_login(self) -> None:
        if not self._phone or self._otp is None:
            raise LoginRequired("not logged in and no phone / OTP channel available")
        await self._goto("login")
        await self._s.fill(self.S["phone_input"], self._phone)
        await self._s.click(self.S["send_otp_button"])
        await self._otp_step()

    async def _otp_step(self) -> None:
        """The site is waiting for the one-time code: announce once, wait on the one-time channel."""
        if self._otp is None:
            raise LoginRequired("no one-time channel for the login code")
        await self._wait("otp_input")
        if self._on_wait:
            await self._on_wait()
        code = await self._wait_for_code()
        try:
            await self._s.fill(self.S["otp_input"], code)
            await self._s.click(self.S["submit_otp_button"])
        finally:
            code = ""  # noqa: F841 - drop our reference; the channel already wiped its copy
        try:
            await self._s.wait_for(self.S["account_name"], 3000)
        except ElementNotFound:
            raise LoginFailed("the site did not accept the login code") from None

    async def _wait_for_code(self) -> str:
        assert self._otp is not None
        deadline = time.monotonic() + self._otp_wait_s
        while True:
            code = self._otp.take(self._task)
            if code:
                return code
            if time.monotonic() >= deadline:
                raise LoginRequired("login code not received in time")
            await self._sleep(self._poll_s)

    async def _read_payment(self, expected: int) -> PaymentHandoff:
        return await read_payment(self._s, self.S, expected)


# ------------------------------------------------------------------ fake-site support
@dataclass
class FakeSiteKit:
    """What a fake-site factory returns: the state and a way to open a browser session on it."""

    state: Any
    new_session: Callable[..., Any]


class SimSession:
    """Generic in-process BrowserSession for the FAKE sites (no Chromium, no sockets).

    A subclass sets ``route`` (url -> page), ``present`` (rows that exist on the page for a selector
    key) and ``act`` (what a click does). ``calls`` logs selector KEYS only, never typed values.
    ``info`` / ``current_host`` let ``CredentialService.autofill`` run against it."""

    def __init__(self, state: Any, selectors: Mapping[str, str], *, site_key: str,
                 user_id: str = "u-sim", task_id: str = "t-sim") -> None:
        self.state, self.sid = state, state.new_session()
        self._sel = {"page_body": "body", **selectors}
        self._rx = {k: template_regex(v) for k, v in self._sel.items()}
        self.page: tuple[str, str] = ("home", "")
        self.fills: dict[str, str] = {}
        self.calls: list[str] = []
        self.closed = False
        self.info = SimpleNamespace(user_id=user_id, site=site_key, task_id=task_id, mode="agent")
        self._host = "fake.invalid"
        self.query: dict[str, str] = {}

    # ---- hooks
    def route(self, head: str, arg: str, q: dict[str, str]) -> None:
        self.page = (head or "home", arg)

    def present(self, key: str, p: dict[str, str]) -> list[dict[str, str]]:
        return []

    def act(self, key: str, p: dict[str, str]) -> None:
        return None

    def visible_text(self) -> str:
        """Everything a person would read on the page (titles, banners): feeds the page reader."""
        return ""

    @property
    def sess(self) -> dict[str, Any]:
        return self.state.sessions[self.sid]

    @property
    def logged_in(self) -> bool:
        return bool(self.sess.get("logged_in"))

    def current_host(self) -> str:
        return self._host

    # ---- selector resolution
    def _key(self, selector: str) -> tuple[str, dict[str, str]]:
        for key, rx in self._rx.items():
            m = rx.match(selector)
            if m:
                return key, m.groupdict()
        raise ElementNotFound(f"unknown selector: {selector}")

    def _rows(self, key: str, p: dict[str, str]) -> list[dict[str, str]]:
        if key == "page_body":
            st = self.state
            if getattr(st, "block", None) == "captcha":
                return [{"text": "Please verify you are a human. Captcha"}]
            if getattr(st, "block", None) == "denied":
                return [{"text": "Access Denied"}]
            return [{"text": f"page {self.page[0]}\n{self.visible_text()}".strip()}]
        return self.present(key, p)

    def _require(self, key: str, p: dict[str, str]) -> list[dict[str, str]]:
        rows = self._rows(key, p)
        if not rows:
            raise ElementNotFound(f"not on this page: {key}")
        return rows

    # ---- BrowserSession
    async def goto(self, url: str) -> None:
        self.calls.append("goto")
        u = urlsplit(url)
        self._host = u.hostname or ""
        parts = [unquote(x) for x in u.path.strip("/").split("/")]
        self.query = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.route(parts[0] or "home", "/".join(parts[1:]), self.query)

    async def fill(self, selector: str, value: str, *, allow_secret_field: bool = False) -> None:
        key, p = self._key(selector)
        if key == "password_input" and not allow_secret_field:  # like TaskSession: only autofill may
            from friday.connectors.sites.errors import UnsafeAction

            raise UnsafeAction("password fields are filled only by the credential service")
        self._require(key, p)
        self.calls.append(f"fill:{key}")
        self.fills[key + "".join(p.values())] = value

    async def click(self, selector: str) -> None:
        key, p = self._key(selector)
        self._require(key, p)
        self.calls.append(f"click:{key}")
        self.act(key, p)

    async def text(self, selector: str) -> str:
        key, p = self._key(selector)
        return self._require(key, p)[0]["text"]

    async def query_all(self, selector: str, fields: Mapping[str, str] | None = None
                        ) -> list[dict[str, str]]:
        try:
            key, p = self._key(selector)
        except ElementNotFound:
            return []
        return self._rows(key, p)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> None:
        key, p = self._key(selector)
        self._require(key, p)

    async def screenshot(self, mask_selectors: Sequence[str] = ()) -> bytes:
        return PNG

    async def close(self) -> None:
        self.closed = True


def pay_rows(key: str, amount: int, ref: str, merchant: str) -> list[dict[str, str]]:
    """Rows of the fake pay page (shared by the fake sites)."""
    from friday.connectors.contract import format_rupees

    t = {"pay_amount": {"text": format_rupees(amount)}, "pay_merchant": {"text": merchant},
         "pay_order_ref": {"text": ref},
         "pay_qr": {"text": "", "src": "data:image/png;base64," + base64.b64encode(PNG).decode()},
         "pay_upi_link": {"text": "Pay", "href":
                          f"upi://pay?pa=fakepay@fakebank&pn=FakePay&am={amount / 100:.2f}&cu=INR&tr={ref}"}}
    return [t[key]] if key in t else []
