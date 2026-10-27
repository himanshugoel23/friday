# ruff: noqa: E501
"""BookMyShow-style movie connector on a scripted browser.

!! Selectors target the FAKE movie site (sites/fakes/movie_site.py). The real BookMyShow is
!! UNVERIFIED: markup, login, seat map and payment screen must be recorded and tuned first.
!! Real tuning touches only PATHS / SELECTORS / FIELDS / ALTERNATES here.
Rules: seats are held (time-limited, reversible) only after approval; the proceed-to-pay click needs
an armed approval; the connector ends at the QR / UPI link and never pays.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.contract import (
    Charge,
    ConnectorError,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    PaymentHandoff,
    TotalsMismatch,
    rupees_to_paise,
)
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.movies.contract import Seat, SeatHold, SeatLine, Show
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import SiteSafety
from friday.connectors.sites.verifier import Expect, Verifier

PATHS = {
    "home": "/", "login": "/login", "search": "/search?q={q}&area={area}",
    "show": "/show/{show_id}", "summary": "/summary", "booking": "/booking/{ref}",
}
SELECTORS = {
    "account_name": "[data-testid=account-name]",
    "phone_input": "[data-testid=phone-input]",
    "send_otp_button": "[data-testid=send-otp-button]",
    "otp_input": "[data-testid=otp-input]",
    "submit_otp_button": "[data-testid=submit-otp-button]",
    "show_card": "[data-testid=show-card]",
    "seat": "[data-testid=seat]",
    "seat_pick": "[data-testid=seat][data-seat-id='{seat_id}']",
    "hold_button": "[data-testid=hold-button]",
    "summary_line": "[data-testid=summary-line]",
    "summary_fee_row": "[data-testid=fee-row]",
    "summary_tax_row": "[data-testid=tax-row]",
    "summary_total": "[data-testid=summary-total]",
    "proceed_to_pay": "[data-testid=proceed-to-pay]",
    "pay_amount": "[data-testid=pay-amount]",
    "pay_merchant": "[data-testid=pay-merchant]",
    "pay_order_ref": "[data-testid=pay-order-ref]",
    "pay_qr": "[data-testid=pay-qr]",
    "pay_upi_link": "[data-testid=pay-upi-link]",
    "booking_state": "[data-testid=booking-state]",
}
FIELDS = {
    "show_card": {"show_id": "@data-show-id", "movie": "[data-testid=movie-name]",
                  "cinema": "[data-testid=cinema-name]", "area": "[data-testid=cinema-area]",
                  "time": "[data-testid=show-time]", "price": "[data-testid=show-price]"},
    "seat": {"seat_id": "@data-seat-id", "label": "@data-label", "price": "@data-price",
             "available": "@data-available"},
    "summary_line": {"seat_id": "@data-seat-id", "label": "[data-testid=line-label]",
                     "price": "[data-testid=line-price]"},
    "charge_row": {"name": "[data-testid=charge-name]", "amount": "[data-testid=charge-amount]"},
}
ALTERNATES = {
    "hold_button": ["[data-testid=continue-button]"],
    "proceed_to_pay": ["[data-testid=go-to-pay]"],
}
EXTRA = {"banner": "[data-testid=banner]"}
IRREVERSIBLE = frozenset({"proceed_to_pay"})
ALLOWED_HOSTS = frozenset({"bookmyshow.com", "fake.invalid", "127.0.0.1", "localhost"})

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TIME = re.compile(r"(\d{1,2}):(\d{2})")
Sleep = Callable[[float], Awaitable[None]]


def _sid(value: str, what: str) -> str:
    if not _SAFE_ID.match(value or ""):
        raise ConnectorError(f"unexpected {what} format")
    return value


def build_kit(inner: BrowserSession, *, task_id: str, repairer: SelectorRepairer | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    safety = SiteSafety(ALLOWED_HOSTS | extra_hosts, IRREVERSIBLE)
    log = RepairLog()
    loc = ElementLocator({**SELECTORS, **EXTRA}, ALTERNATES, repairer=repairer, log=log,
                         task_id=task_id, irreversible=IRREVERSIBLE)
    ver = Verifier({
        SELECTORS["proceed_to_pay"]: Expect(present=(SELECTORS["pay_amount"],)),
        ALTERNATES["proceed_to_pay"][0]: Expect(present=(SELECTORS["pay_amount"],)),
        SELECTORS["send_otp_button"]: Expect(present=(SELECTORS["otp_input"],)),
    })
    return AgentKit(GuardedSession(inner, safety, loc, PageReader(), ver), safety, loc, log)


class BookMyShowConnector:
    site = "bookmyshow"
    use_case = "movie"
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
        return f"BookMyShowConnector(task_id={self._task!r})"

    async def _goto(self, key: str, **params: str) -> None:
        await self._s.goto(self._base + PATHS[key].format(
            **{k: quote(v, safe="") for k, v in params.items()}))

    async def _text(self, key: str) -> str:
        try:
            return await self._s.text(SELECTORS[key])
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _money(self, key: str) -> int:
        try:
            return rupees_to_paise(await self._text(key))
        except ValueError:
            raise LayoutChanged(f"'{key}' is not a money amount") from None

    # ---- login (same secure-page rule as food: code comes only from the one-time channel)
    async def ensure_logged_in(self) -> str:
        await self._goto("home")
        if await self._s.query_all(SELECTORS["account_name"]):
            return "reused"
        if not self._phone or self._otp is None:
            raise LoginRequired("not logged in and no phone / OTP channel available")
        await self._goto("login")
        await self._s.fill(SELECTORS["phone_input"], self._phone)
        await self._s.click(SELECTORS["send_otp_button"])
        try:
            await self._s.wait_for(SELECTORS["otp_input"], 3000)
        except ElementNotFound:
            raise LayoutChanged("selector 'otp_input' not found") from None
        if self._on_wait:
            await self._on_wait()
        code = await self._wait_for_code()
        await self._s.fill(SELECTORS["otp_input"], code)
        await self._s.click(SELECTORS["submit_otp_button"])
        try:
            await self._s.wait_for(SELECTORS["account_name"], 3000)
        except ElementNotFound:
            raise LoginFailed("the site did not accept the login code") from None
        return "logged_in"

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

    # ---- the contract
    async def search_shows(self, query: str, area: str) -> list[Show]:
        await self._goto("search", q=query, area=area)
        out: list[Show] = []
        for r in await self._s.query_all(SELECTORS["show_card"], FIELDS["show_card"]):
            m = _TIME.search(r.get("time", ""))
            if not m or not _SAFE_ID.match(r.get("show_id", "")):
                continue
            try:
                price = rupees_to_paise(r["price"]) if r.get("price") else 0
                out.append(Show(show_id=r["show_id"], movie=r.get("movie", ""),
                                cinema=r.get("cinema", ""), area=r.get("area", ""),
                                starts_at=f"{int(m.group(1)):02d}:{m.group(2)}",
                                minutes=int(m.group(1)) * 60 + int(m.group(2)), from_paise=price))
            except (ValueError, ValidationError):
                continue
        return out

    async def get_seats(self, show_id: str) -> list[Seat]:
        await self._goto("show", show_id=_sid(show_id, "show id"))
        seats: list[Seat] = []
        for r in await self._s.query_all(SELECTORS["seat"], FIELDS["seat"]):
            try:
                seats.append(Seat(seat_id=_sid(r["seat_id"], "seat id"), label=r.get("label", ""),
                                  price_paise=rupees_to_paise(r["price"]),
                                  available=r.get("available", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError, ConnectorError):
                continue
        if not seats:
            raise LayoutChanged("no seats found")
        return seats

    async def hold_seats(self, show_id: str, seat_ids: list[str]) -> SeatHold:
        await self.ensure_logged_in()
        seats = {s.seat_id: s for s in await self.get_seats(show_id)}
        gone = [s for s in seat_ids if s not in seats or not seats[s].available]
        if gone:
            raise OutOfStock("a seat is taken", gone)
        for sid in seat_ids:
            await self._s.click(SELECTORS["seat_pick"].format(seat_id=_sid(sid, "seat id")))
        await self._s.click(SELECTORS["hold_button"])
        await self._goto("summary")
        hold = await self._read_summary(show_id)
        if sorted(hold.seat_ids()) != sorted(seat_ids):
            raise OutOfStock("the held seats differ from the request", [])
        return hold

    async def _read_summary(self, show_id: str) -> SeatHold:
        try:
            await self._s.wait_for(SELECTORS["summary_total"], 3000)
        except ElementNotFound:
            raise OutOfStock("no seats are held", []) from None
        lines = []
        for r in await self._s.query_all(SELECTORS["summary_line"], FIELDS["summary_line"]):
            try:
                lines.append(SeatLine(seat_id=_sid(r["seat_id"], "seat id"),
                                      label=r.get("label", ""), price_paise=rupees_to_paise(r["price"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("summary line could not be read") from None
        fees, taxes = await self._charges("summary_fee_row"), await self._charges("summary_tax_row")
        try:
            return SeatHold(show_id=show_id, lines=lines, fees=fees, taxes=taxes,
                            subtotal_paise=sum(x.price_paise for x in lines),
                            total_paise=await self._money("summary_total"))
        except ValidationError:
            raise TotalsMismatch("booking totals on the page do not add up") from None

    async def _charges(self, key: str) -> list[Charge]:
        out = []
        for r in await self._s.query_all(SELECTORS[key], FIELDS["charge_row"]):
            try:
                out.append(Charge(name=r["name"], amount_paise=rupees_to_paise(r["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged(f"'{key}' row could not be read") from None
        return out

    async def get_payment_handoff(self, hold: SeatHold) -> PaymentHandoff:
        await self._goto("summary")
        again = await self._read_summary(hold.show_id)
        if again.total_paise != hold.total_paise:
            raise TotalsMismatch("the total changed since the booking was approved")
        await self._s.click(SELECTORS["proceed_to_pay"])
        amount = await self._money("pay_amount")
        if amount != hold.total_paise:
            raise TotalsMismatch("payment page amount differs from the approved booking")
        merchant = await self._text("pay_merchant")
        ref = await self._s.query_all(SELECTORS["pay_order_ref"])
        qr = None
        for r in await self._s.query_all(SELECTORS["pay_qr"], {"src": "@src"}):
            if r.get("src", "").startswith("data:image/png;base64,"):
                try:
                    qr = base64.b64decode(r["src"].split(",", 1)[1], validate=True)
                except ValueError:
                    qr = None
        link = None
        for r in await self._s.query_all(SELECTORS["pay_upi_link"], {"href": "@href"}):
            href = r.get("href", "")
            if href.startswith("upi://pay"):
                am = parse_qs(urlsplit(href).query).get("am")
                if am and rupees_to_paise(am[0]) != amount:
                    raise TotalsMismatch("UPI link amount differs from the approved booking")
                link = href
        if qr is None and link is None:
            raise LayoutChanged("no QR or UPI link on the payment page")
        try:
            return PaymentHandoff(kind="qr" if qr else "upi_intent", amount_paise=amount,
                                  merchant=merchant, order_ref=(ref[0]["text"] if ref else None),
                                  qr_png=qr, upi_link=link)
        except ValidationError:
            raise LayoutChanged("payment page data failed validation") from None

    async def track_booking(self, ref: str) -> str:
        await self._goto("booking", ref=_sid(ref, "booking ref"))
        return await self._text("booking_state")
