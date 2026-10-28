# ruff: noqa: E501
"""One site server: the nine generic tools, driven entirely by the site's knowledge file (urls, selectors, markers).

Every tool returns a dict with ``status``. A block / challenge / robots refusal returns ``blocked`` and puts the
(user, site) on a cooldown so nothing retries in a loop. There is no pay / place-order tool and the guard refuses
payment-looking clicks anyway. Page text is untrusted data: it is parsed into short fields, never passed on as instructions.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit

from friday.connectors.browser.port import BrowserError, ElementNotFound
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry
from friday.sitemcp.guard import PaymentBlocked, PoolBusy, RateLimited, SafeSession, SiteBlocked
from friday.sitemcp.protocol import McpServer
from friday.sitemcp.runtime import SessionPool, SiteSession
from friday.sitemcp.tools import TOOL_SPECS, assert_no_payment_tools

MAX_ITEMS = 10
_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def parse_price(text: str) -> float | None:
    m = _NUM.search((text or "").replace("₹", " ").replace("Rs.", " ").replace("Rs", " ").replace("INR", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _clip(s: str, n: int = 160) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:n]


class SiteServer:
    def __init__(self, kb: dict[str, Any], pool: SessionPool, *, otp: OneTimeOtpChannel | None = None,
                 tokens: OtpTokenRegistry | None = None, otp_url: Callable[[str], str] | None = None,
                 on_login_started: Callable[[str, str, str], None] | None = None) -> None:
        self.kb, self.pool, self.site = kb, pool, kb["site"]
        self.otp, self.tokens, self.otp_url, self.on_login_started = otp, tokens, otp_url, on_login_started
        self._handlers: dict[str, Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "set_location": self.set_location, "search_products": self.search_products, "get_product": self.get_product,
            "add_to_cart": self.add_to_cart, "view_cart": self.view_cart, "checkout_preview": self.checkout_preview,
            "login_start": self.login_start, "login_status": self.login_status, "logout": self.logout,
        }
        assert_no_payment_tools(self._handlers)

    def mcp(self) -> McpServer:
        return McpServer(f"friday-sitemcp-{self.site}", str(self.kb["version"]), dict(TOOL_SPECS), dict(self._handlers))

    # ------------------------------------------------------------------ plumbing
    def url(self, name: str, **kw: str) -> str:
        return self.kb["base_url"].rstrip("/") + self.kb["urls"][name].format(**kw)

    async def _run(self, user: str, fn: Callable[[SiteSession], Awaitable[dict[str, Any]]], *, touches_site: bool = True) -> dict[str, Any]:
        try:
            async with self.pool.session(user, self.kb) as s:
                now = self.pool._clock()
                if touches_site and s.cooldown_until > now:
                    return self._blocked(s.block_reason or "cooldown", cooldown=True)
                try:
                    return await fn(s)
                except SiteBlocked as e:
                    s.cooldown_until = now + float(self.kb["blocked"].get("cooldown_s", 1800))
                    s.block_reason = e.reason
                    return self._blocked(e.reason)
        except PoolBusy as e:
            return {"status": "busy", "reason": e.reason}
        except RateLimited:
            return {"status": "rate_limited", "advice": "too many requests to this site; try again later"}
        except PaymentBlocked:
            return {"status": "error", "error": "payment_refused"}
        except ElementNotFound as e:
            return {"status": "unavailable", "reason": "page_changed", "detail": _clip(str(e), 100)}
        except BrowserError as e:
            return {"status": "unavailable", "reason": type(e).__name__}

    def _blocked(self, reason: str, cooldown: bool = False) -> dict[str, Any]:
        return {"status": "blocked", "reason": reason, "cooldown": cooldown,
                "advice": "the site refused or showed a challenge; Friday does not get around it. Use web sources or a deep link and tell the user plainly."}

    async def _body(self, s: SiteSession) -> str:
        try:
            return (await s.safe.text("body")).lower()
        except ElementNotFound:
            return ""

    async def _any_marker(self, s: SiteSession, markers: list[str]) -> bool:
        body = await self._body(s)
        return any(m in body for m in markers)

    async def _text(self, s: SiteSession, sel: str) -> str:
        if not sel:
            return ""
        try:
            return _clip(await s.safe.text(sel))
        except ElementNotFound:
            return ""

    def _row_item(self, row: dict[str, str]) -> dict[str, Any]:
        raw = row.get("url", "")
        path = urlsplit(raw).path + (("?" + urlsplit(raw).query) if urlsplit(raw).query else "") if raw else ""
        host = urlsplit(raw).hostname
        if host and host not in self.kb["domains"]:
            path = ""  # never hand out links to other hosts
        price = _clip(row.get("price", ""), 40)
        return {"id": path, "title": _clip(row.get("title", "")), "price_text": price, "price_inr": parse_price(price),
                "pack": _clip(row.get("pack", ""), 40), "rating": _clip(row.get("rating", ""), 20),
                "out_of_stock": bool(row.get("stock", "").strip()) or any(m in row.get("text", "").lower() for m in self.kb["product"]["oos_markers"]),
                "url": self.kb["base_url"].rstrip("/") + path if path else ""}

    async def snapshot(self, user: str) -> bytes | None:
        """PNG of the page the session is on, ONLY for an anonymous session (public pages; never a logged-in page)."""
        if (user, self.site) not in self.pool._sessions:
            return None
        try:
            async with self.pool.session(user, self.kb) as s:
                return None if s.safe.logged_in else await s.safe.screenshot()
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ tools
    async def set_location(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        value = (args.get("pincode") or args.get("place") or "").strip()
        if not value or (args.get("pincode") and args.get("place")):
            return {"status": "error", "error": "give exactly one of place or pincode"}
        loc = self.kb["location"]

        async def go(s: SiteSession) -> dict[str, Any]:
            await s.safe.goto(self.url("home"))
            if loc.get("open") and await s.safe.exists(loc["open"]):
                await s.safe.click(loc["open"])
            await s.safe.fill(loc["input"], value)
            if loc.get("suggestion") and await s.safe.exists(loc["suggestion"]):
                await s.safe.click(loc["suggestion"])
            elif loc.get("submit"):
                await s.safe.click(loc["submit"])
            if await self._any_marker(s, loc["not_found_markers"]):
                s.location = ""
                return {"status": "location_not_found", "advice": "the site does not serve this place; tell the user plainly"}
            label = await self._text(s, loc["current"])
            if not label:
                return {"status": "unavailable", "reason": "page_changed", "detail": "location not confirmed"}
            s.location = value
            return {"status": "ok", "location_label": label}

        return await self._run(user, go)

    async def search_products(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        q = args["query"].strip()
        sr = self.kb["search"]

        async def go(s: SiteSession) -> dict[str, Any]:
            if not s.location:
                return {"status": "needs_location"}
            await s.safe.goto(self.url("search", query=quote(q)))
            rows = await s.safe.query_all(sr["row"], {k: v for k, v in sr["fields"].items() if v})
            items = [self._row_item(r) for r in rows[:MAX_ITEMS] if r.get("title", "").strip()]
            if not items:
                if await self._any_marker(s, self.kb["location"]["not_found_markers"]):
                    return {"status": "location_not_found"}
                return {"status": "ok", "items": [], "note": "no_results"}
            return {"status": "ok", "items": items, "as_of_url": self.url("search", query=quote(q))}

        return await self._run(user, go)

    def _product_url(self, pid: str) -> str | None:
        if not pid.startswith("/") or pid.startswith("//") or "\\" in pid or ".." in pid:
            return None
        return self.kb["base_url"].rstrip("/") + pid

    async def _open_product(self, s: SiteSession, pid: str) -> dict[str, Any] | None:
        url = self._product_url(pid)
        if url is None:
            return {"status": "error", "error": "bad product id (use the id from search_products)"}
        await s.safe.goto(url)
        if not await self._text(s, self.kb["product"]["title"]):
            return {"status": "not_found"}
        return None

    async def get_product(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        pr = self.kb["product"]

        async def go(s: SiteSession) -> dict[str, Any]:
            bad = await self._open_product(s, args["id"])
            if bad:
                return bad
            body = await self._body(s)
            return {"status": "ok", "id": args["id"], "title": await self._text(s, pr["title"]),
                    "price_text": await self._text(s, pr["price"]), "price_inr": parse_price(await self._text(s, pr["price"])),
                    "mrp_text": await self._text(s, pr.get("mrp", "")), "pack": await self._text(s, pr.get("pack", "")),
                    "rating": await self._text(s, pr.get("rating", "")),
                    "out_of_stock": any(m in body for m in pr["oos_markers"]) or bool(await self._text(s, pr.get("stock", ""))),
                    "url": self._product_url(args["id"])}

        return await self._run(user, go)

    async def add_to_cart(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        qty = int(args.get("qty", 1))
        pr = self.kb["product"]

        async def go(s: SiteSession) -> dict[str, Any]:
            if not s.location:
                return {"status": "needs_location"}
            bad = await self._open_product(s, args["id"])
            if bad:
                return bad
            body = await self._body(s)
            if any(m in body for m in pr["oos_markers"]):
                return {"status": "unavailable", "reason": "out_of_stock"}
            await s.safe.click(pr["add"])
            for _ in range(qty - 1):
                await s.safe.click(pr["qty_plus"])
            return {"status": "ok", "staged": True, "qty": qty, "note": "added to the cart only; nothing is bought and Friday never pays"}

        return await self._run(user, go)

    async def _read_cart(self, s: SiteSession) -> list[dict[str, Any]]:
        c = self.kb["cart"]
        rows = await s.safe.query_all(c["row"], {k: v for k, v in c["fields"].items() if v})
        return [{"name": _clip(r.get("name", "")), "qty": _clip(r.get("qty", ""), 10), "price_text": _clip(r.get("price", ""), 40),
                 "price_inr": parse_price(r.get("price", ""))} for r in rows[:30]]

    async def view_cart(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        async def go(s: SiteSession) -> dict[str, Any]:
            await s.safe.goto(self.url("cart"))
            items = await self._read_cart(s)
            return {"status": "ok", "items": items, "empty": not items}

        return await self._run(user, go)

    async def _bill(self, s: SiteSession) -> dict[str, Any]:
        co = self.kb["checkout"]
        rows = await s.safe.query_all(co["fee_row"], {k: v for k, v in co["fee_fields"].items() if v}) if co.get("fee_row") else []
        fees = [{"label": _clip(r.get("label", ""), 60), "amount_text": _clip(r.get("amount", ""), 30), "amount_inr": parse_price(r.get("amount", ""))} for r in rows[:15]]
        total = await self._text(s, co["total"])
        return {"fees": fees, "total_text": total, "total_inr": parse_price(total)}

    async def checkout_preview(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        co, lg = self.kb["checkout"], self.kb["login"]

        async def go(s: SiteSession) -> dict[str, Any]:
            await s.safe.goto(self.url("cart"))
            items = await self._read_cart(s)
            if not items:
                return {"status": "ok", "items": [], "empty": True, "payment_step_reached": "empty_cart", "stopped_before_payment": True}
            step, clicked = "cart_summary", False
            # We click ONE knowledge-named button (the 'proceed to checkout' step) and only when a live run has verified it
            # does not charge or place an order. Otherwise we only read the cart bill. We never click anything after it.
            if co.get("proceed_verified") and co.get("proceed") and await s.safe.exists(co["proceed"]):
                await s.safe.click(co["proceed"])
                clicked = True
                if lg.get("phone") and await s.safe.exists(lg["phone"]) and not s.safe.logged_in:
                    return {"status": "needs_login"}
                step = "payment_options" if await s.safe.exists(co["payment_marker"]) else "address_or_slot"
            bill = await self._bill(s)
            return {"status": "ok", "items": items, **bill, "payment_step_reached": step, "proceed_clicked": clicked,
                    "stopped_before_payment": True, "note": "Friday stops here; the user pays in the app themselves"}

        return await self._run(user, go)

    # ------------------------------------------------------------------ login (OTP only on Friday's secure page)
    async def login_start(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        lg = self.kb["login"]
        phone = re.sub(r"[^0-9]", "", args["phone"])[-10:]
        if self.otp is None or self.tokens is None:
            return {"status": "unavailable", "reason": "secure_otp_page_not_configured"}

        async def go(s: SiteSession) -> dict[str, Any]:
            await s.safe.goto(self.url("home"))
            if lg.get("open") and await s.safe.exists(lg["open"]):
                await s.safe.click(lg["open"])
            await s.safe.fill(lg["phone"], phone)
            await s.safe.click(lg["send_otp"])
            await s.safe.wait_for(lg["otp"], 5000)  # ElementNotFound -> unavailable (the site did not ask for a code)
            task_id = f"sitemcp-{self.site}-{secrets.token_hex(6)}"
            s.otp_task_id = task_id
            token = self.tokens.create(task_id, phone[-2:])  # type: ignore[union-attr]
            if self.on_login_started:
                self.on_login_started(user, self.site, task_id)  # guardrails: a login code typed in chat is accepted now
            return {"status": "otp_required", "secure_page": self.otp_url(token) if self.otp_url else token,
                    "advice": "tell the user to type the code on this secure page, not in chat logs; then call login_status"}

        return await self._run(user, go)

    async def login_status(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        lg = self.kb["login"]

        async def go(s: SiteSession) -> dict[str, Any]:
            if s.safe.logged_in and not s.otp_task_id:
                return {"status": "logged_in"}
            if not s.otp_task_id or self.otp is None:
                return {"status": "needs_login"}
            code = self.otp.take(s.otp_task_id)
            if code is None:
                return {"status": "otp_required", "pending": True}
            task = s.otp_task_id
            await s.safe.fill(lg["otp"], code)
            await s.safe.click(lg["verify"])
            del code
            if await self._any_marker(s, lg.get("wrong_otp_markers", [])):
                s.otp_task_id = ""
                return {"status": "needs_login", "reason": "wrong_code", "advice": "start the login again"}
            if not await s.safe.exists(lg["logged_in_marker"]):
                return {"status": "unavailable", "reason": "login_not_confirmed"}
            s.safe.logged_in, s.otp_task_id = True, ""
            if self.tokens:
                self.tokens.revoke_task(task)
            if self.pool.vault:
                self.pool.vault.save(user, self.site, await s.safe.storage_state())  # encrypted at rest by StorageVault
            return {"status": "logged_in"}

        return await self._run(user, go)

    async def logout(self, user: str, args: dict[str, Any]) -> dict[str, Any]:
        lg = self.kb["login"]

        async def go(s: SiteSession) -> dict[str, Any]:
            if s.safe.logged_in and lg.get("logout") and await s.safe.exists(lg["logout"]):
                await s.safe.click(lg["logout"])
            return {"status": "logged_out"}

        # do not start a browser just to log out: only touch the site when a session is already open
        res = await self._run(user, go, touches_site=False) if (user, self.site) in self.pool._sessions else {"status": "logged_out"}
        await self.pool.close_site(user, self.site)
        if self.pool.vault:
            self.pool.vault.disconnect(user, self.site)
        return {"status": "logged_out", "stored_session_erased": True} if res.get("status") in ("logged_out", "blocked", "unavailable", "busy") else res


__all__ = ["SafeSession", "SiteServer", "parse_price"]
