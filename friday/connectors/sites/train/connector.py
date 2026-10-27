# ruff: noqa: E501
"""Train connectors on a scripted browser: IRCTC (password login) and ixigo (phone + code) for
booking, eRail for read-only timetable and seat information.

!! Every selector below targets the FAKE site (sites/fakes/train_site.py). The real IRCTC, ixigo
!! and eRail are UNVERIFIED: markup, login, captcha, booking window and payment screens must be
!! recorded and tuned first. Real tuning touches only PATHS / SELECTORS / FIELDS / ALTERNATES.
Rules: the login PASSWORD is only ever filled by ``CredentialService.autofill`` (the adapter never
sees it); the one-time code comes only from the one-time channel; a captcha or a closed booking
window is a ``HandOver`` (stop, never solve, never retry); the connector ends at the QR / UPI link.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession
from friday.connectors.contract import (
    CartMismatch,
    Charge,
    ConnectorError,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    PaymentHandoff,
    TotalsMismatch,
    rupees_to_paise,
)
from friday.connectors.sites.train.common import (
    AddOnStuck,
    HandOver,
    ScriptedConnector,
    build_kit,
    clean,
    safe_id,
)
from friday.connectors.sites.train.contract import (
    CLASSES,
    QUOTAS,
    AddOn,
    FareLine,
    FareQuote,
    Passenger,
    TrainOption,
)

PATHS = {
    "home": "/", "login": "/login", "book": "/book",
    "search": "/search?from={frm}&to={to}&date={date}&cls={cls}&quota={quota}",
    "fare": "/fare", "booking": "/booking/{ref}",
    "timetable": "/trains?from={frm}&to={to}&date={date}",
    "seats": "/seats?train={train_no}&date={date}&cls={cls}",
}
BASE_SELECTORS = {
    "account_name": "[data-testid=account-name]",
    "username_input": "[data-testid=username-input]",
    "password_input": "[data-testid=password-input]",
    "login_submit": "[data-testid=login-submit]",
    "captcha_image": "[data-testid=captcha-image]",
    "phone_input": "[data-testid=phone-input]",
    "send_otp_button": "[data-testid=send-otp-button]",
    "otp_input": "[data-testid=otp-input]",
    "submit_otp_button": "[data-testid=submit-otp-button]",
    "login_error": "[data-testid=login-error]",
    "window_notice": "[data-testid=booking-window-notice]",
    "train_row": "[data-testid=train-row]",
    "train_class_pick": "[data-testid=train-row][data-train-no='{train_no}'] [data-testid=class-pick][data-cls='{cls}']",
    "avail_now": "[data-testid=availability-now]",
    "passenger_name": "[data-testid=passenger-name-{i}]",
    "passenger_age": "[data-testid=passenger-age-{i}]",
    "passenger_gender": "[data-testid=passenger-gender-{i}]",
    "passenger_berth": "[data-testid=passenger-berth-{i}]",
    "continue_button": "[data-testid=continue-button]",
    "passenger_row": "[data-testid=passenger-row]",
    "fare_line": "[data-testid=fare-line]",
    "fare_fee_row": "[data-testid=fee-row]",
    "addon_row": "[data-testid=addon-row]",
    "addon_toggle": "[data-testid=addon-toggle-{addon_id}]",
    "fare_total": "[data-testid=fare-total]",
    "book_confirm": "[data-testid=confirm-booking]",
    "pay_amount": "[data-testid=pay-amount]",
    "pay_merchant": "[data-testid=pay-merchant]",
    "pay_order_ref": "[data-testid=pay-order-ref]",
    "pay_qr": "[data-testid=pay-qr]",
    "pay_upi_link": "[data-testid=pay-upi-link]",
    "booking_state": "[data-testid=booking-state]",
}
# ixigo: same shape, its own (guessed) test ids where the layout differs.
IXIGO_SELECTORS = {**BASE_SELECTORS,
                   "train_row": "[data-testid=train-card]",
                   "train_class_pick": "[data-testid=train-card][data-train-no='{train_no}'] [data-testid=class-chip][data-cls='{cls}']",
                   "continue_button": "[data-testid=proceed-passengers]",
                   "book_confirm": "[data-testid=confirm-booking-ix]"}
ERAIL_SELECTORS = {
    "train_row": "[data-testid=train-row]",
    "avail_now": "[data-testid=availability-now]",
    "window_notice": "[data-testid=booking-window-notice]",
}
SELECTORS = {"irctc": BASE_SELECTORS, "ixigo": IXIGO_SELECTORS, "erail": ERAIL_SELECTORS}
FIELDS = {
    "train_row": {"train_no": "@data-train-no", "name": "[data-testid=train-name]",
                  "depart": "[data-testid=depart]", "arrive": "[data-testid=arrive]",
                  "fare": "[data-testid=fare]", "status": "@data-status",
                  "avail": "[data-testid=availability]", "cls": "@data-cls"},
    "avail_now": {"status": "@data-status", "avail": "[data-testid=availability]", "fare": "[data-testid=fare]"},
    "passenger_row": {"name": "[data-testid=p-name]", "age": "[data-testid=p-age]",
                      "gender": "[data-testid=p-gender]", "berth": "[data-testid=p-berth]"},
    "fare_line": {"name": "[data-testid=line-name]", "amount": "[data-testid=line-amount]"},
    "charge_row": {"name": "[data-testid=charge-name]", "amount": "[data-testid=charge-amount]"},
    "addon_row": {"addon_id": "@data-addon-id", "label": "[data-testid=addon-label]",
                  "amount": "[data-testid=addon-amount]", "checked": "@data-checked"},
}
ALTERNATES = {"continue_button": ["[data-testid=next-step]"]}
IRREVERSIBLE = frozenset({"book_confirm"})
EXPECT = {"book_confirm": ("pay_amount",), "send_otp_button": ("otp_input",)}
STATUSES = {"confirmed", "waitlist", "rac", "regret"}


def make_kit(session: BrowserSession, site_key: str, *, task_id: str, repairer: Any = None):  # noqa: ANN201
    sel = SELECTORS[site_key]
    irreversible = IRREVERSIBLE if site_key != "erail" else frozenset()
    expect = {k: v for k, v in EXPECT.items() if k in sel}
    return build_kit(session, site_key=site_key, selectors=sel, alternates={
        k: v for k, v in ALTERNATES.items() if k in sel}, irreversible=irreversible,
        task_id=task_id, repairer=repairer, expect=expect)


def _option(r: Mapping[str, str], cls: str) -> TrainOption | None:
    no = r.get("train_no", "")
    status = r.get("status", "").lower()
    try:
        fare = rupees_to_paise(r["fare"]) if r.get("fare") else 0
        return TrainOption(train_no=safe_id(no, "train number"), name=clean(r.get("name", ""), 60),
                           depart=clean(r.get("depart", ""), 8), arrive=clean(r.get("arrive", ""), 8),
                           cls=r.get("cls") or cls, fare_paise=fare,
                           status=status if status in STATUSES else "unknown",  # type: ignore[arg-type]
                           availability=clean(r.get("avail", ""), 40))
    except (ValueError, ValidationError, ConnectorError):
        return None


class TrainConnector(ScriptedConnector):
    """IRCTC / ixigo booking on the scripted browser."""

    use_case = "train"
    P, F = PATHS, FIELDS

    def __init__(self, session: BrowserSession, *, site: str, credentials: Any = None,
                 raw_session: Any = None, **kw: Any) -> None:
        super().__init__(session, **kw)
        self.site, self.S = site, SELECTORS[site]
        self._creds, self._raw = credentials, raw_session
        self.login_mode = "password" if site == "irctc" else "phone"

    # ---- login: password only through autofill, code only through the one-time channel
    async def ensure_logged_in(self) -> str:
        await self._goto("home")
        if await self._present("account_name"):
            return "reused"
        if self.login_mode == "phone":
            await self._phone_login()
            return "logged_in"
        await self._goto("login")
        if await self._present("captcha_image"):
            raise HandOver("captcha")  # never solved, never retried
        if self._creds is None or self._raw is None:
            raise LoginRequired("no saved login available for this site")
        ok = await self._creds.autofill(
            self._raw, username_selector=self.S["username_input"],
            password_selector=self.S["password_input"], submit_selector=self.S["login_submit"])
        if not ok:
            raise LoginRequired("no saved login for this site")
        if await self._present("captcha_image"):
            raise HandOver("captcha")
        if await self._present("login_error"):
            raise LoginFailed("the site did not accept the saved login")
        await self._otp_step()
        return "logged_in"

    async def _no_login_form(self) -> None:
        if await self._present("username_input" if self.login_mode == "password" else "phone_input"):
            raise LoginRequired("the site logged the session out")

    # ---- read
    async def search(self, frm: str, to: str, date: str, cls: str, quota: str) -> list[TrainOption]:
        if cls not in CLASSES or quota not in QUOTAS:
            raise ConnectorError("unsupported class or quota")
        await self._goto("search", frm=frm, to=to, date=date, cls=cls, quota=quota)
        if await self._present("window_notice"):
            raise HandOver("booking_window")
        return [o for r in await self._rows("train_row") if (o := _option(r, cls))]

    async def availability(self, train_no: str, cls: str) -> TrainOption:
        """Open the class for this train (reversible) and read what the site says NOW."""
        await self._s.click(self.S["train_class_pick"].format(train_no=safe_id(train_no, "train"), cls=cls))
        rows = await self._rows("avail_now")
        if not rows:
            raise LayoutChanged("selector 'avail_now' not found")
        o = _option({**rows[0], "train_no": train_no}, cls)
        if o is None:
            raise LayoutChanged("availability could not be read")
        return o

    # ---- the booking steps (called only after approval)
    async def fill_passengers(self, passengers: list[Passenger]) -> None:
        """Exactly what the user gave; there is no default for any field."""
        for i, p in enumerate(passengers, 1):
            await self._s.fill(self.S["passenger_name"].format(i=i), p.name)
            await self._s.fill(self.S["passenger_age"].format(i=i), str(p.age))
            await self._s.fill(self.S["passenger_gender"].format(i=i), p.gender)
            await self._s.fill(self.S["passenger_berth"].format(i=i), p.berth)
        await self._s.click(self.S["continue_button"])
        await self._no_login_form()
        await self._wait("fare_total")

    async def read_fare(self, passengers: list[Passenger]) -> FareQuote:
        rows = await self._rows("passenger_row")
        got = [(" ".join(r.get("name", "").split()).lower(), r.get("age", ""), r.get("gender", ""), r.get("berth", "")) for r in rows]
        want = [(p.name.lower(), str(p.age), p.gender, p.berth) for p in passengers]
        if got != want:
            raise CartMismatch("passenger details on the page differ from what the user gave")
        fares = []
        for r in await self._rows("fare_line"):
            try:
                fares.append(FareLine(name=clean(r["name"], 60), amount_paise=rupees_to_paise(r["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("fare line could not be read") from None
        addons = []
        for r in await self._rows("addon_row"):
            try:
                addons.append(AddOn(addon_id=safe_id(r["addon_id"], "extra"), label=clean(r["label"], 60),
                                    amount_paise=rupees_to_paise(r["amount"]),
                                    checked=r.get("checked", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError, ConnectorError):
                raise LayoutChanged("extra could not be read") from None
        fees = []
        for r in await self._rows("fare_fee_row", "charge_row"):
            try:
                fees.append(Charge(name=clean(r["name"], 60), amount_paise=rupees_to_paise(r["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("fee row could not be read") from None
        try:
            return FareQuote(fares=fares, fees=fees, addons=addons, total_paise=await self._money("fare_total"))
        except ValidationError:
            raise TotalsMismatch("fare totals on the page do not add up") from None

    async def untick_addons(self, quote: FareQuote, passengers: list[Passenger]) -> FareQuote:
        """Untick every pre-ticked extra (insurance etc.). Raises ``AddOnStuck`` if one stays."""
        for a in quote.ticked():
            await self._s.click(self.S["addon_toggle"].format(addon_id=a.addon_id))
        fresh = await self.read_fare(passengers)
        stuck = fresh.ticked()
        if stuck:
            raise AddOnStuck([a.label for a in stuck], sum(a.amount_paise for a in stuck), fresh)
        return fresh

    async def confirm_booking(self, total_paise: int) -> PaymentHandoff:
        """The ONE irreversible click (armed by the adapter after approval); ends at the pay page."""
        await self._s.click(self.S["book_confirm"])
        return await self._read_payment(total_paise)

    async def booking_state(self, ref: str) -> str:
        await self._goto("booking", ref=safe_id(ref, "booking ref"))
        return clean(await self._text("booking_state"), 60)


class ERailConnector(ScriptedConnector):
    """eRail: read-only timetable and seat availability. No login, no booking, nothing to click."""

    use_case = "train_info"
    P, S, F = PATHS, ERAIL_SELECTORS, FIELDS

    async def timetable(self, frm: str, to: str, date: str) -> list[TrainOption]:
        await self._goto("timetable", frm=frm, to=to, date=date)
        if await self._present("window_notice"):
            raise HandOver("booking_window")
        return [o for r in await self._rows("train_row") if (o := _option(r, ""))]

    async def seats(self, train_no: str, date: str, cls: str) -> TrainOption | None:
        await self._goto("seats", train_no=safe_id(train_no, "train"), date=date, cls=cls)
        rows = await self._rows("avail_now")
        return _option({**rows[0], "train_no": train_no}, cls) if rows else None


__all__ = ["TrainConnector", "ERailConnector", "make_kit", "SELECTORS"]
