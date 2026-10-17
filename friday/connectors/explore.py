"""Founder-supervised EXPLORE run of the Zomato food connector (real site, no order).

What it does: open the site, confirm the location, search, open the first matching restaurant,
read the menu if the (UNVERIFIED) locators fit, log in with the founder's OWN phone number and
the OTP he types on the secure one-time page, confirm the login, and stop. With ``add_item`` it
adds that one item, shows the cart and the payment hand-off screen (QR / UPI link) and stops
there. It never pays, never clicks anything named like pay / place order (``FORBIDDEN_CLICK``),
and has no place-order tool.

Unknown page states (challenge, block page, empty page, HTTP error, missing locator) are
screenshot-recorded, written to ``state.json`` as ``blocked_reason`` in plain English, and the run
ends cleanly: no retries, no evasion, no stealth, no proxies. Pacing is polite (small random
delays).

Secrets: the phone number and the OTP never reach a log, a note, a file or a screenshot. During
the login phase every input is painted over and the phone text is masked. The Playwright trace
is ended just before the phone is typed and a FRESH trace session starts only after the login is
confirmed, so neither value can be in a trace. Exact values are also stripped from text
snapshots. The OTP is typed straight into the page from the one-time channel and the variable is
dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from friday.connectors.browser.playwright_session import (
    CHROMIUM_ENV,
    find_chromium,
    playwright_installed,
)
from friday.connectors.contract import Menu, MenuItem, rupees_to_paise
from friday.connectors.food.zomato_live import (
    BLOCK_MARKERS,
    CANDIDATES,
    FORBIDDEN_CLICK,
    Cand,
    classify_page,
    parse_menu_rows,
    phone_regex,
)
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.recorder import MASK_SELECTORS, StepRecorder
from friday.connectors.report import render_report
from friday.connectors.scrub import OTP, PHONE, scrub_text

SITE_URL = "https://www.zomato.com"
TRACE_1 = "trace-1-before-login.zip"
TRACE_2 = "trace-2-after-login.zip"
_TEXT_CAP = 20_000
_ELEMENTS_JS = """
() => Array.from(document.querySelectorAll(
  'a,button,input,select,textarea,[role=button],[role=link],[role=option],[data-testid]'))
  .slice(0, 400).map((e) => ({
    tag: e.tagName.toLowerCase(), type: e.getAttribute('type') || '',
    role: e.getAttribute('role') || '',
    name: (e.getAttribute('aria-label') ||
           ((e.tagName === 'INPUT' || e.tagName === 'TEXTAREA') ? '' : e.innerText) || '')
           .trim().slice(0, 80),
    placeholder: e.getAttribute('placeholder') || '',
    autocomplete: e.getAttribute('autocomplete') || '',
    testid: e.getAttribute('data-testid') || '', id: e.id || '',
    href: (e.getAttribute('href') || '').split('?')[0].slice(0, 120),
    visible: !!(e.offsetWidth || e.offsetHeight),
  }))
"""


class Blocked(Exception):
    """The run cannot continue safely; ends cleanly with this reason in state.json."""

    def __init__(self, code: str, explanation: str) -> None:
        super().__init__(code)
        self.code, self.explanation = code, explanation


def local_digits(phone: str) -> str:
    """10-digit Indian mobile number from '+91...' / '91...' / '0...' / plain; '' if not Indian."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) == 10 and d[0] in "6789" else ""


def mask_phone(phone: str) -> str:
    """Only the last two digits are ever shown."""
    d = re.sub(r"\D", "", phone or "")
    return f"..{d[-2:]}" if len(d) >= 2 else ".."


class Sanitiser:
    """Text that may be written to disk: exact phone/OTP values out, then scrub() applied."""

    def __init__(self, phone_digits: str = "") -> None:
        self._phone = phone_regex(phone_digits) if phone_digits else None
        self._secrets: list[str] = []

    @property
    def phone_pattern(self) -> re.Pattern[str] | None:
        return self._phone

    def add_secret(self, value: str) -> None:
        if value:
            self._secrets.append(value)

    def clear_secrets(self) -> None:
        self._secrets.clear()

    def text(self, s: str) -> str:
        for sec in self._secrets:
            s = s.replace(sec, OTP)
        if self._phone is not None:
            s = self._phone.sub(PHONE, s)
        return scrub_text(s)

    def obj(self, o: Any) -> Any:
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        if isinstance(o, list | tuple):
            return [self.obj(v) for v in o]
        return o


@dataclass
class ExploreConfig:
    out: Path
    base_url: str = SITE_URL
    area: str = "Gurgaon"
    query: str = "Domino's"
    headed: bool = True
    add_item: str | None = None
    probe: bool = False  # reachability check only: stops after the menu step, no login, no phone
    phone: str = ""  # runtime only; never printed, logged or written
    otp: OneTimeOtpChannel = field(default_factory=OneTimeOtpChannel)
    task_id: str = "zomato-explore"
    otp_timeout_s: float = 300.0
    login_confirm_s: float = 12.0
    timeout_scale: float = 1.0  # multiplies every locate timeout (tests shrink it)
    pace: tuple[float, float] = (0.8, 2.0)
    allowed_hosts: set[str] | None = None  # set => other hosts' requests are aborted (fake site)
    on_waiting_for_otp: Callable[[], None] | None = None
    say: Callable[[str], None] = print  # progress lines: step names only, never values
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    rng: random.Random = field(default_factory=random.Random)


class Explorer:
    def __init__(self, cfg: ExploreConfig, recorder: StepRecorder) -> None:
        self.cfg, self.rec = cfg, recorder
        digits = local_digits(cfg.phone)
        self._digits = digits
        self.san = Sanitiser(digits)
        self.page: Any = None
        self.context: Any = None
        self.last_status: int | None = None
        self.login_phase = False
        self._trace_chunk = 0  # 0 none active, 1 before login, 2 after login
        self.restaurant_url = ""
        self.state: dict[str, Any] = {
            "status": "running", "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "finished_at": None, "headed": cfg.headed, "area": cfg.area, "query": cfg.query,
            "phone_hint": mask_phone(cfg.phone), "steps": [], "blocked_reason": None,
            "logged_in": False, "observe_only": False, "menu_items": 0, "add_item": cfg.add_item,
            "handoff": None, "notes": [],
        }
        cfg.out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ files
    def flush(self) -> None:
        tmp = self.cfg.out / "state.json.tmp"
        tmp.write_text(json.dumps(self.san.obj(self.state), indent=2, ensure_ascii=False))
        os.replace(tmp, self.cfg.out / "state.json")

    def _write(self, path: Path, content: str | bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------ capture
    async def _masks(self) -> list[Any]:
        p = self.page
        masks = [p.locator(sel) for sel in MASK_SELECTORS]
        if self.login_phase:
            masks.append(p.locator("input, textarea"))
            if self.san.phone_pattern is not None:
                masks.append(p.get_by_text(self.san.phone_pattern))
        return masks

    async def capture(self, name: str, note: str, outcome: str = "ok",
                      matched: dict[str, str] | None = None, check: bool = True) -> None:
        """Record one step (screenshot, title, sanitised text, element outline). Then, unless
        ``check`` is False, raise Blocked if the page is a challenge / error / empty page."""
        p = self.page
        n = len(self.state["steps"]) + 1
        d = self.cfg.out / "steps" / f"{n:02d}-{name}"
        try:
            png = await p.screenshot(mask=await self._masks())
        except Exception:  # noqa: BLE001 - a failed screenshot must not end the run
            png = b""
        title = text = ""
        elements: list[Any] = []
        markers: list[str] = []
        with contextlib.suppress(Exception):
            title = await p.title()
        with contextlib.suppress(Exception):
            text = await p.evaluate("() => document.body ? document.body.innerText : ''")
        with contextlib.suppress(Exception):
            elements = await p.evaluate(_ELEMENTS_JS)
        with contextlib.suppress(Exception):
            markers = await self._challenge_markers()
        url = self.san.text(p.url or "")
        clean_text = self.san.text(text)[:_TEXT_CAP]
        meta = {"n": n, "step": name, "note": note, "outcome": outcome, "url": url,
                "title": self.san.text(title), "http_status": self.last_status,
                "matched": matched or {}, "challenge_markers": len(markers)}
        if png:
            self._write(d / "screenshot.png", png)
        self._write(d / "text.txt", clean_text)
        self._write(d / "elements.json",
                    json.dumps(self.san.obj(elements), indent=1, ensure_ascii=False))
        self._write(d / "meta.json", json.dumps(self.san.obj(meta), indent=1, ensure_ascii=False))
        self.rec.add(name, url, note, png)
        self.state["steps"].append({k: meta[k] for k in ("n", "step", "outcome", "url", "title",
                                                         "matched")})
        self.flush()
        self.cfg.say(f"step {n:02d} {name}: {outcome}")
        if check:
            verdict = classify_page(status=self.last_status, title=title, text=text,
                                    markers=markers)
            if verdict:
                raise Blocked(*verdict)

    async def _challenge_markers(self) -> list[str]:
        found = []
        for sel in BLOCK_MARKERS:
            loc = self.page.locator(sel)
            if await loc.count():
                box = await loc.first.bounding_box()
                if box and box["width"] >= 100 and box["height"] >= 50:
                    found.append(sel)
        return found

    # ------------------------------------------------------------ locating
    @staticmethod
    def _build(scope: Any, c: Cand, query: str = "") -> Any:
        v, extra = c.value.replace("{query}", re.escape(query)), c.extra.replace(
            "{query}", re.escape(query))
        if c.kind == "css":
            return scope.locator(v)
        if c.kind == "role":
            return scope.get_by_role(v, name=re.compile(extra, re.I)) if extra \
                else scope.get_by_role(v)
        if c.kind == "placeholder":
            return scope.get_by_placeholder(re.compile(v, re.I))
        if c.kind == "text":
            return scope.get_by_text(re.compile(v, re.I))
        raise ValueError(f"unknown candidate kind {c.kind}")

    async def find(self, key: str, *, timeout_s: float = 6.0, scope: Any = None,
                   query: str = "") -> tuple[Any, str] | None:
        """First visible match among the candidates for ``key``; returns (locator, name)."""
        scope = scope or self.page
        deadline = time.monotonic() + timeout_s * self.cfg.timeout_scale
        while True:
            for c in CANDIDATES[key]:
                try:
                    loc = self._build(scope, c, query)
                    if await loc.count() and await loc.first.is_visible():
                        return loc, c.name
                except Exception:  # noqa: BLE001 - a bad candidate must not stop the others
                    continue
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.3)

    async def absent(self, key: str) -> bool:
        for c in CANDIDATES[key]:
            with contextlib.suppress(Exception):
                loc = self._build(self.page, c)
                if await loc.count() and await loc.first.is_visible():
                    return False
        return True

    async def _click(self, loc: Any) -> None:
        label = " ".join(filter(None, [
            await loc.first.inner_text(timeout=3000) if await loc.count() else "",
            await loc.first.get_attribute("aria-label") or "",
            await loc.first.get_attribute("value") or "",
        ]))
        if FORBIDDEN_CLICK.search(label):
            raise Blocked("forbidden_click_refused",
                          "The next click looked like a payment / place-order button. Friday "
                          "never clicks those, so the run stopped here.")
        self.last_status = None
        await loc.first.click(timeout=8000)

    async def _pace(self) -> None:
        lo, hi = self.cfg.pace
        await self.cfg.sleep(self.cfg.rng.uniform(lo, hi))

    async def _settle(self) -> None:
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("load", timeout=10000)
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("networkidle", timeout=4000)

    async def _adopt_new_tab(self, pages_before: int) -> None:
        await asyncio.sleep(0.5)
        if len(self.context.pages) > pages_before:
            self.page = self.context.pages[-1]
            self._watch(self.page)
            await self._settle()

    def _watch(self, page: Any) -> None:
        def on_response(resp: Any) -> None:
            with contextlib.suppress(Exception):
                if resp.request.is_navigation_request() and resp.frame == page.main_frame:
                    self.last_status = resp.status

        page.on("response", on_response)

    def _missing(self, step: str, what: str) -> Blocked:
        return Blocked("selector_missing",
                       f"Could not find {what} on the page (step '{step}'). The site layout "
                       "probably differs from the guessed locators; see the screenshot.")

    # ------------------------------------------------------------ tracing
    async def _trace_stop_chunk(self) -> None:
        if self._trace_chunk:
            name = TRACE_1 if self._trace_chunk == 1 else TRACE_2
            with contextlib.suppress(Exception):
                await self.context.tracing.stop(path=str(self.cfg.out / name))
            self._trace_chunk = 0

    async def _trace_start_chunk(self, which: int) -> None:
        with contextlib.suppress(Exception):
            # a brand-new tracing session: its network log and resource cache start empty, so
            # nothing typed during the (untraced) login phase can leak into it
            await self.context.tracing.start(screenshots=True, snapshots=True)
            self._trace_chunk = which

    # ------------------------------------------------------------ the steps
    async def s_open_home(self) -> None:
        self.cfg.say("opening the site")
        try:
            await self.page.goto(self.cfg.base_url, wait_until="domcontentloaded", timeout=45000)
        except Exception:  # noqa: BLE001
            await self.capture("open_home", "page did not load", "failed", check=False)
            raise Blocked("navigation_failed", "The site did not load (timeout or network "
                          "error from this server).") from None
        await self._settle()
        await self._pace()
        await self.capture("open_home", "opened the home page")

    async def s_location(self) -> None:
        found = await self.find("location_input", timeout_s=3)
        if found is None:
            await self.capture("location", "site did not ask for a location", "skipped")
            return
        loc, name = found
        await loc.first.click(timeout=5000)
        await loc.first.fill(self.cfg.area)
        await self._pace()
        opt = await self.find("location_option", timeout_s=3)
        matched = {"location_input": name}
        if opt is not None:
            matched["location_option"] = opt[1]
            await opt[0].first.click(timeout=5000)
        else:
            await loc.first.press("Enter")
        await self._settle()
        await self._pace()
        await self.capture("location", f"set location to '{self.cfg.area}'", matched=matched)

    async def s_search(self) -> None:
        found = await self.find("search_input", timeout_s=8)
        if found is None:
            await self.capture("search", "no search box found", "failed", check=False)
            raise self._missing("search", "the search box")
        loc, name = found
        self.last_status = None
        await loc.first.fill(self.cfg.query)
        await self._pace()
        await loc.first.press("Enter")
        await self._settle()
        await self._pace()
        await self.capture("search", f"searched for '{self.cfg.query}'",
                           matched={"search_input": name})

    async def s_open_restaurant(self) -> None:
        found = await self.find("restaurant_result", timeout_s=10, query=self.cfg.query)
        if found is None:
            await self.capture("restaurant", "no result for the query", "failed", check=False)
            raise self._missing("restaurant", f"a result for '{self.cfg.query}'")
        loc, name = found
        before = len(self.context.pages)
        await self._click(loc)
        await self._adopt_new_tab(before)
        await self._settle()
        await self._pace()
        self.restaurant_url = self.page.url
        await self.capture("restaurant", "opened the first matching restaurant",
                           matched={"restaurant_result": name})

    async def s_menu(self) -> None:
        found = await self.find("menu_rows", timeout_s=5)
        rows: list[dict[str, object]] = []
        if found is not None:
            texts = await found[0].all_inner_texts()
            rows = parse_menu_rows(texts[:300])
        if not rows:
            self.state["observe_only"] = True
            await self.capture("menu_observe_only",
                               "menu locators did not match; observe-only from here",
                               "observe_only")
            return
        rid = re.sub(r"[^A-Za-z0-9_.-]", "", self.page.url.rstrip("/").rsplit("/", 1)[-1])[:64]
        items = []
        for i, r in enumerate(rows, 1):
            with contextlib.suppress(ValueError, TypeError):
                items.append(MenuItem(item_id=f"item-{i}", name=str(r["name"]),
                                      price_paise=rupees_to_paise(str(r["price_text"])),
                                      veg=bool(r["veg"])))
        if not items:
            self.state["observe_only"] = True
            await self.capture("menu_observe_only", "menu rows had no readable price",
                               "observe_only")
            return
        menu = Menu(restaurant_id=rid or "unknown", items=items)
        self._write(self.cfg.out / "menu.json",
                    json.dumps(self.san.obj(menu.model_dump()), indent=1, ensure_ascii=False))
        self.state["menu_items"] = len(items)
        self.state["notes"].append("menu veg flag is a text guess (UNVERIFIED)")
        await self.capture("menu", f"read {len(items)} menu items", matched={"menu_rows": found[1]
                                                                         if found else ""})

    async def s_login(self) -> None:
        if not self._digits:
            raise Blocked("no_indian_phone",
                          "The configured test number is not a 10-digit Indian mobile number.")
        found = await self.find("login_open", timeout_s=8)
        if found is None:
            await self.capture("login_open", "no login button found", "failed", check=False)
            raise self._missing("login_open", "the Log in button")
        self.login_phase = True  # from here every input is masked and the trace is off
        await self._click(found[0])
        await self._settle()
        await self._pace()
        await self._trace_stop_chunk()
        await self.capture("login_open", "opened the login screen",
                           matched={"login_open": found[1]})
        ph = await self.find("phone_input", timeout_s=8)
        if ph is None:
            raise self._missing("phone", "the phone number field")
        await ph[0].first.fill(self._digits)
        await self._pace()
        await self.capture("phone_entered", "phone typed (masked)", matched={"phone_input": ph[1]})
        send = await self.find("send_otp", timeout_s=5)
        if send is None:
            raise self._missing("send_otp", "the button that sends the login code")
        await self._click(send[0])
        await self._settle()
        otp_in = await self.find("otp_input", timeout_s=12)
        await self.capture("code_requested", "asked the site to send the login code",
                           matched={"send_otp": send[1], **({"otp_input": otp_in[1]}
                                                            if otp_in else {})})
        if otp_in is None:
            raise self._missing("otp_input", "the login code field (the site may have refused "
                                "the number)")
        await self._wait_and_enter_otp(otp_in[0], send_name=send[1])

    async def _wait_and_enter_otp(self, otp_loc: Any, send_name: str) -> None:
        cfg = self.cfg
        await self.capture("waiting_for_code", "waiting for the founder's code (masked)",
                           "waiting", check=False)
        if cfg.on_waiting_for_otp:
            cfg.on_waiting_for_otp()
        deadline = time.monotonic() + cfg.otp_timeout_s
        code: str | None = None
        while code is None:
            code = cfg.otp.take(cfg.task_id)
            if code is None:
                if time.monotonic() >= deadline:
                    raise Blocked("otp_timeout", "No login code arrived within "
                                  f"{int(cfg.otp_timeout_s // 60)} minutes, so the run stopped.")
                await asyncio.sleep(0.5)
        self.san.add_secret(code)
        self.cfg.say("login code received; entering it (not logged)")
        try:
            await otp_loc.first.click(timeout=5000)
            await self.page.keyboard.type(code, delay=cfg.rng.uniform(50, 130))
        finally:
            code = ""  # noqa: F841 - drop our reference; the channel already wiped its copy
        verify = await self.find("verify_otp", timeout_s=3)
        vname = ""
        if verify is not None:
            vname = verify[1]
            await self._click(verify[0])
        await self._settle()
        confirmed = await self._confirm_logged_in()
        await self.capture("logged_in" if confirmed else "login_not_confirmed",
                           "login confirmed" if confirmed else "login could not be confirmed",
                           "ok" if confirmed else "failed",
                           matched={"verify_otp": vname, "send_otp": send_name}, check=confirmed)
        self.san.clear_secrets()
        if not confirmed:
            raise Blocked("login_not_confirmed",
                          "The login did not complete (code wrong or expired, or the site wants "
                          "another check). The run stopped.")
        self.login_phase = False
        self.state["logged_in"] = True
        await self._trace_start_chunk(2)

    async def _confirm_logged_in(self) -> bool:
        deadline = time.monotonic() + self.cfg.login_confirm_s
        while time.monotonic() < deadline:
            if await self.absent("login_open") and await self.absent("otp_input") \
                    and await self.absent("phone_input"):
                await asyncio.sleep(1.0)  # let late renders settle, then look again
                if await self.absent("login_open") and await self.absent("otp_input"):
                    return True
            await asyncio.sleep(0.5)
        return False

    async def s_add_item(self) -> None:
        item = self.cfg.add_item or ""
        if self.state["observe_only"]:
            raise self._missing("add_item", "the menu (observe-only mode)")
        if self.page.url != self.restaurant_url:
            self.last_status = None
            await self.page.goto(self.restaurant_url, wait_until="domcontentloaded",
                                 timeout=45000)
            await self._settle()
            await self._pace()
        rows = await self.find("menu_rows", timeout_s=6)
        row = rows[0].filter(has_text=re.compile(re.escape(item), re.I)).first if rows else None
        if rows is None or not await row.count():
            await self.capture("add_item", f"item '{item}' not found", "failed", check=False)
            raise self._missing("add_item", f"the menu item '{item}'")
        add = await self.find("row_add", timeout_s=3, scope=row)
        if add is None:
            await self.capture("add_item", "no Add button on the row", "failed", check=False)
            raise self._missing("add_item", f"an Add button for '{item}'")
        await self._click(add[0])
        await self._settle()
        await self._pace()
        await self.capture("item_added", f"added one '{item}' (requested with --add-item)",
                           matched={"row_add": add[1]})
        cart = await self.find("cart_open", timeout_s=6)
        if cart is None:
            raise self._missing("cart", "the cart link")
        await self._click(cart[0])
        await self._settle()
        await self._pace()
        await self.capture("cart_summary", "cart summary (stop point for the cart)",
                           matched={"cart_open": cart[1]})
        pay = await self.find("checkout", timeout_s=6)
        if pay is None:
            raise self._missing("checkout", "the button that leads to the payment screen")
        await self._click(pay[0])
        await self._settle()
        await self._pace()
        qr = await self.find("qr_image", timeout_s=4)
        upi = await self.find("upi_link", timeout_s=2)
        self.state["handoff"] = {"qr_image_seen": qr is not None, "upi_link_seen": upi is not None}
        await self.capture("payment_handoff", "payment hand-off screen; NOTHING was paid or "
                           "placed", matched={"checkout": pay[1]})

    # ------------------------------------------------------------ driver
    async def run(self) -> dict[str, Any]:
        try:
            await self._launch()
            await self.s_open_home()
            await self.s_location()
            await self.s_search()
            await self.s_open_restaurant()
            await self.s_menu()
            if not self.cfg.probe:
                await self.s_login()
                if self.cfg.add_item:
                    await self.s_add_item()
            self.state["status"] = "done"
        except Blocked as b:
            self.state["status"] = "blocked"
            self.state["blocked_reason"] = {"code": b.code, "explanation": b.explanation,
                                            "step": len(self.state["steps"])}
            self.cfg.say(f"BLOCKED ({b.code}): {b.explanation}")
        except Exception as e:  # noqa: BLE001 - never echo page text or values
            self.state["status"] = "failed"
            self.state["blocked_reason"] = {
                "code": "unexpected_error", "step": len(self.state["steps"]),
                "explanation": f"The run hit an unexpected error ({type(e).__name__}); "
                               "see the last screenshot."}
            with contextlib.suppress(Exception):
                await self.capture("error", "unexpected error", "failed", check=False)
        finally:
            self.san.clear_secrets()
            self.login_phase = False
            await self._trace_stop_chunk()
            self.state["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            self.rec.finish({"status": self.state["status"]})
            self.flush()
            self._write(self.cfg.out / "report.html",
                        render_report(self.rec, "Friday: Zomato explore run"))
            await self._close()
        return self.state

    # ------------------------------------------------------------ browser
    async def _launch(self) -> None:
        if not playwright_installed():
            raise Blocked("no_playwright", "Playwright is not installed (uv sync --extra browser).")
        exe = find_chromium()
        if exe is None:
            raise Blocked("no_chromium", f"No Chromium found; set {CHROMIUM_ENV} or run "
                          "'playwright install chromium'.")
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        args = ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
        self._browser = await self._pw.chromium.launch(
            executable_path=exe, headless=not self.cfg.headed, args=args)
        self.context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900}, locale="en-IN")
        self.context.set_default_timeout(15000)
        hosts = self.cfg.allowed_hosts
        if hosts is not None:
            async def guard(route: Any) -> None:
                url = route.request.url
                host = url.split("/")[2].split(":")[0] if "//" in url else ""
                if url.startswith(("data:", "about:")) or host in hosts:
                    await route.continue_()
                else:
                    await route.abort()

            await self.context.route("**/*", guard)
        await self.context.tracing.start(screenshots=True, snapshots=True)
        self._trace_chunk = 1
        self.page = await self.context.new_page()
        self._watch(self.page)

    async def _close(self) -> None:
        if self.context is None:
            return
        for closer in (self.context.close, self._browser.close, self._pw.stop):
            with contextlib.suppress(Exception):
                await closer()


async def run_explore(cfg: ExploreConfig, recorder: StepRecorder | None = None) -> dict[str, Any]:
    """Run the explore flow; returns the final state dict (also in cfg.out/state.json)."""
    return await Explorer(cfg, recorder or StepRecorder()).run()
