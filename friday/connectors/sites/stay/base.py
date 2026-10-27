# ruff: noqa: E501
"""Shared base for the STAY use cases (hotel + flight) and, via ``ScriptedSiteBase``, the bus sites.

!! Every selector here is generated from a per-site ``Dialect`` plus a few per-site overrides and
!! targets the FAKE sites in sites/fakes/stay_site.py and bus_site.py. The real sites are UNVERIFIED:
!! markup, login, result lists and payment screens must be recorded and tuned before any real use.

What a site module supplies: a ``SiteConfig`` (dialect, overrides, paths, allow-listed hosts). What
this file does once for all sites: money in INR only (a foreign currency is a hand-over, not a guess),
the cancellation terms read back, the total cap including taxes and fees, the add-ons off by default,
passenger names only from the user, re-ask on any price rise or worse cancellation terms, the one
irreversible click armed only after approval, and the QR / UPI hand-off. Nothing here pays.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.catalog import policy_hosts
from friday.connectors.catalog import site as catalog_site
from friday.connectors.contract import (
    Charge,
    ConnectorError,
    ItemQty,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    PaymentHandoff,
    TotalsMismatch,
    format_rupees,
    rupees_to_paise,
)
from friday.connectors.gate import ActionGate, Grant, Verdict
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.scrub import scrub_text
from friday.connectors.sites.adapters import (
    APPROVAL_TTL,
    ExecResult,
    Prepared,
    Problem,
    Proposal,
)
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.injection import strip_injection
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import SiteSafety
from friday.connectors.sites.stay.contract import (
    ForeignCurrency,
    Option,
    Policy,
    Quote,
    QuoteLine,
    Variant,
    is_inr,
)
from friday.connectors.sites.verifier import Expect, Verifier

if TYPE_CHECKING:
    from friday.connectors.sites.adapters import RunCtx

FAKE_HOSTS = frozenset({"fake.invalid", "127.0.0.1", "localhost"})
IRREVERSIBLE = frozenset({"proceed_to_pay"})
ALT_KEYS = ("reserve_button", "hold_button", "proceed_to_pay")
ATTR_FIELDS = frozenset({
    "item_id", "variant_id", "seat_id", "point_id", "addon_id", "currency", "free_until",
    "nonrefundable", "sold_out", "checked", "available", "seconds", "kind", "pct"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
Sleep = Callable[[float], Awaitable[None]]


# ------------------------------------------------------------------ per-site selector dialect
def _case(word: str, case: str) -> str:
    parts = word.split("_")
    if case == "dash":
        return "-".join(parts)
    if case == "camel":
        return parts[0] + "".join(p.title() for p in parts[1:])
    return "_".join(parts)


@dataclass(frozen=True)
class Dialect:
    """How one site spells its hooks: ``sel`` for elements, ``fld`` for sub-elements of a row,
    ``attr`` for attributes (``{d}`` is the key in the site's case style)."""

    sel: str
    fld: str
    attr: str
    case: str  # dash | camel | snake

    def selector(self, key: str) -> str:
        return self.sel.format(d=_case(key, self.case))

    def param(self, key: str, p: str) -> str:
        return self.selector(key) + f"[{self.attr.format(d=_case(p, self.case))}='{{{p}}}']"

    def field(self, name: str) -> str:
        if name in ATTR_FIELDS:
            return "@" + self.attr.format(d=_case(name, self.case))
        return self.fld.format(d=_case(name, self.case))


STAY_PLAIN = (
    "account_name", "phone_input", "send_otp_button", "otp_input", "submit_otp_button",
    "result_card", "variant_row", "reserve_button", "review_line", "review_fee_row",
    "review_tax_row", "review_total", "review_policy", "guest_name_input", "proceed_to_pay",
    "addon_row", "pay_amount", "pay_merchant", "pay_order_ref", "pay_qr", "pay_upi_link",
)
STAY_PARAM = {"variant_pick": "variant_id", "addon_toggle": "addon_id",
              "passenger_name_input": "n"}
STAY_ROWS = {
    "result_card": ("item_id", "name", "price", "currency", "rating"),
    "variant_row": ("variant_id", "name", "base", "fees", "taxes", "currency", "sold_out",
                    "free_until", "nonrefundable"),
    "review_line": ("variant_id", "name", "price"),
    "charge_row": ("name", "amount"),
    "review_total": ("currency",),
    "review_policy": ("free_until", "nonrefundable"),
    "addon_row": ("addon_id", "name", "price", "checked"),
}


@dataclass(frozen=True)
class SiteConfig:
    key: str  # catalog site key
    name: str
    dialect: Dialect
    paths: dict[str, str]
    overrides: dict[str, str] = field(default_factory=dict)  # key -> selector, the site's quirks
    plain: tuple[str, ...] = STAY_PLAIN
    params: dict[str, str] = field(default_factory=lambda: dict(STAY_PARAM))
    rows: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(STAY_ROWS))
    hold_s: int = 0  # bus: seconds the site holds a seat

    @property
    def sel(self) -> dict[str, str]:
        d = self.dialect
        out = {k: self.overrides.get(k) or d.selector(k) for k in self.plain}
        out.update({k: self.overrides.get(k) or d.param(k, p) for k, p in self.params.items()})
        return out

    @property
    def fields(self) -> dict[str, dict[str, str]]:
        return {row: {f: self.dialect.field(f) for f in names} for row, names in self.rows.items()}

    @property
    def alternates(self) -> dict[str, list[str]]:
        return {k: [self.dialect.selector(k + "_alt")] for k in ALT_KEYS if k in self.sel}

    @property
    def hosts(self) -> frozenset[str]:
        """The network allow-list: catalog.policy_hosts(key), wildcards reduced to the domain."""
        return frozenset(h.removeprefix("*.").removeprefix("www.") for h in policy_hosts(self.key))

    @property
    def home(self) -> str:
        s = catalog_site(self.key)
        return s.home if s else ""


def build_kit(inner: BrowserSession, cfg: SiteConfig, *, task_id: str,
              repairer: SelectorRepairer | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    safety = SiteSafety(cfg.hosts | FAKE_HOSTS | extra_hosts, IRREVERSIBLE)
    log = RepairLog()
    sel = cfg.sel
    loc = ElementLocator(sel, cfg.alternates, repairer=repairer, log=log, task_id=task_id,
                         irreversible=IRREVERSIBLE)
    exp = {sel["proceed_to_pay"]: Expect(present=(sel["pay_amount"],)),
           sel["send_otp_button"]: Expect(present=(sel["otp_input"],))}
    for alt in cfg.alternates.get("proceed_to_pay", []):
        exp[alt] = Expect(present=(sel["pay_amount"],))
    return AgentKit(GuardedSession(inner, safety, loc, PageReader(), Verifier(exp)), safety, loc, log)


# ------------------------------------------------------------------ small helpers
def parse_inr(text: str, currency: str = "") -> int:
    """INR text -> paise. A foreign or unknown currency raises ``ForeignCurrency`` (never guessed).
    (rupees_to_paise alone would read 'Rs. 4,200' as 0.42 because of the dot after 'Rs'.)"""
    if not is_inr(text, currency):
        raise ForeignCurrency("the site shows prices in a currency other than INR")
    bare = re.sub(r"(?i)(₹|\brs\b\.?|\binr\b)", " ", text)
    try:
        return rupees_to_paise(bare)
    except ValueError:
        raise LayoutChanged("a price on the page is not a money amount") from None


def clean_text(kit: AgentKit | None, raw: str, limit: int = 80) -> str:
    """Page text for display: instruction-like sentences removed (and noted), secrets scrubbed."""
    clean, hits = strip_injection(raw or "")
    if hits and kit is not None:
        kit.safety.note_injection(hits)
    return re.sub(r"\s+", " ", scrub_text(clean)).strip()[:limit]


def safe_id(value: str, what: str) -> str:
    if not _SAFE_ID.match(value or ""):
        raise ConnectorError(f"unexpected {what} format")
    return value


@dataclass
class HandoverProblem(Problem):
    """A ``Problem`` the user can act on. kinds: ``foreign_currency`` (hand over the link),
    ``need_info`` (``slot`` names what to ask; ``options`` lists the choices the site offers),
    plus the base kinds ``no_match`` and ``out_of_stock``."""

    link: str = ""
    slot: str = ""
    options: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ the scripted connector base
class ScriptedSiteBase:
    backend = "scripted_browser"
    _kit: AgentKit | None = None  # set by the adapter: page text is injection-stripped when read

    def __init__(self, session: BrowserSession, *, cfg: SiteConfig, base_url: str, task_id: str,
                 otp_channel: OneTimeOtpChannel | None = None, phone: str | None = None,
                 on_code_wait: Callable[[], Awaitable[None]] | None = None,
                 otp_wait_s: float = 120.0, poll_s: float = 0.5, sleep: Sleep = asyncio.sleep,
                 ) -> None:
        self._s, self.cfg, self._base, self._task = session, cfg, base_url.rstrip("/"), task_id
        self._otp, self._phone, self._on_wait = otp_channel, phone, on_code_wait
        self._otp_wait_s, self._poll_s, self._sleep = otp_wait_s, poll_s, sleep
        self.sel, self.fields = cfg.sel, cfg.fields

    def __repr__(self) -> str:
        return f"{type(self).__name__}(site={self.cfg.key!r}, task_id={self._task!r})"

    async def _goto(self, key: str, **params: Any) -> None:
        q = {k: quote(str(v), safe="") for k, v in params.items()}
        await self._s.goto(self._base + self.cfg.paths[key].format(**q))

    async def _text(self, key: str) -> str:
        try:
            return await self._s.text(self.sel[key])
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _rows(self, key: str, row: str | None = None) -> list[dict[str, str]]:
        return await self._s.query_all(self.sel[key], self.fields.get(row or key))

    async def _charges(self, key: str) -> list[Charge]:
        out = []
        for r in await self._rows(key, "charge_row"):
            try:
                out.append(Charge(name=clean_text(None, r["name"], 40),
                                  amount_paise=parse_inr(r["amount"])))
            except (KeyError, ValidationError):
                raise LayoutChanged(f"'{key}' row could not be read") from None
        return out

    # ---- login: the code arrives only through the one-time channel, never through here
    async def ensure_logged_in(self) -> str:
        await self._goto("home")
        if await self._s.query_all(self.sel["account_name"]):
            return "reused"
        if not self._phone or self._otp is None:
            raise LoginRequired("not logged in and no phone / OTP channel available")
        await self._goto("login")
        await self._s.fill(self.sel["phone_input"], self._phone)
        await self._s.click(self.sel["send_otp_button"])
        try:
            await self._s.wait_for(self.sel["otp_input"], 3000)
        except ElementNotFound:
            raise LayoutChanged("selector 'otp_input' not found") from None
        if self._on_wait:
            await self._on_wait()
        code = await self._wait_for_code()
        await self._s.fill(self.sel["otp_input"], code)
        await self._s.click(self.sel["submit_otp_button"])
        try:
            await self._s.wait_for(self.sel["account_name"], 3000)
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

    # ---- the payment page: amount must equal the approved total; ends in QR / UPI link
    async def read_handoff(self, approved_total: int) -> PaymentHandoff:
        row = (await self._rows("pay_amount", "review_total"))[:1]
        try:
            amount = parse_inr(await self._text("pay_amount"), row[0].get("currency", "") if row else "")
        except ForeignCurrency:
            raise TotalsMismatch("the payment page is not in INR") from None
        if amount != approved_total:
            raise TotalsMismatch("payment page amount differs from the approved booking")
        merchant = clean_text(None, await self._text("pay_merchant"), 60) or self.cfg.name
        ref = await self._s.query_all(self.sel["pay_order_ref"])
        qr = None
        for r in await self._s.query_all(self.sel["pay_qr"], {"src": "@src"}):
            if r.get("src", "").startswith("data:image/png;base64,"):
                try:
                    qr = base64.b64decode(r["src"].split(",", 1)[1], validate=True)
                except ValueError:
                    qr = None
        link = None
        for r in await self._s.query_all(self.sel["pay_upi_link"], {"href": "@href"}):
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
                                  merchant=merchant, order_ref=(ref[0]["text"][:40] if ref else None),
                                  qr_png=qr, upi_link=link)
        except ValidationError:
            raise LayoutChanged("payment page data failed validation") from None


# ------------------------------------------------------------------ STAY connector
class StayConnector(ScriptedSiteBase):
    """Hotel and flight steps on one site. ``kind`` is ``hotel`` or ``flight``."""

    async def search(self, kind: str, **params: Any) -> list[Option]:
        await self._goto(f"search_{kind}", **params)
        out: list[Option] = []
        for r in await self._rows("result_card"):
            if not _SAFE_ID.match(r.get("item_id", "")):
                continue
            try:
                out.append(Option(item_id=r["item_id"], name=clean_text(self._kit, r.get("name", "")) or "Unnamed",
                                  price_paise=parse_inr(r.get("price", ""), r.get("currency", "")),
                                  rating=clean_text(None, r.get("rating", ""), 8)))
            except ValidationError:
                continue
        return out

    async def variants(self, kind: str, item_id: str, **params: Any) -> list[Variant]:
        await self._goto(f"detail_{kind}", item_id=safe_id(item_id, "item id"), **params)
        out: list[Variant] = []
        for r in await self._rows("variant_row"):
            if not _SAFE_ID.match(r.get("variant_id", "")):
                continue
            cur = r.get("currency", "")
            try:
                out.append(Variant(
                    variant_id=r["variant_id"], name=clean_text(self._kit, r.get("name", ""), 60),
                    base_paise=parse_inr(r.get("base", ""), cur),
                    fees_paise=parse_inr(r["fees"], cur) if r.get("fees") else 0,
                    taxes_paise=parse_inr(r["taxes"], cur) if r.get("taxes") else 0,
                    sold_out=r.get("sold_out", "").lower() == "true",
                    free_until=r.get("free_until", "").strip(),
                    nonrefundable=tuple(x.strip()[:40] for x in r.get("nonrefundable", "").split(";")
                                        if x.strip())))
            except ValidationError:
                continue
        return out

    async def begin(self, kind: str, item_id: str, variant_id: str, params: dict[str, Any],
                    names: list[str], guest: str) -> Quote:
        """Pick, reserve, switch add-ons off, type the names the USER gave, read the summary."""
        found = {v.variant_id: v for v in await self.variants(kind, item_id, **params)}
        v = found.get(variant_id)
        if v is None or v.sold_out:
            raise OutOfStock("that option is sold out", [v.name if v else "that option"])
        await self._s.click(self.sel["variant_pick"].format(variant_id=safe_id(variant_id, "variant id")))
        await self._s.click(self.sel["reserve_button"])
        try:
            await self._s.wait_for(self.sel["review_total"], 3000)
        except ElementNotFound:
            raise OutOfStock("nothing is reserved", [v.name]) from None
        for r in await self._rows("addon_row"):  # baggage / meal etc. stay OFF unless the user asks
            if r.get("checked", "").lower() == "true":
                await self._s.click(self.sel["addon_toggle"].format(addon_id=safe_id(r["addon_id"], "add-on id")))
        if any(r.get("checked", "").lower() == "true" for r in await self._rows("addon_row")):
            raise ConnectorError("an add-on could not be switched off")
        if kind == "hotel":
            await self._s.fill(self.sel["guest_name_input"], guest)
        else:
            for i, name in enumerate(names, 1):
                await self._s.fill(self.sel["passenger_name_input"].format(n=i), name)
        return await self.read_quote()

    async def read_quote(self) -> Quote:
        try:
            await self._s.wait_for(self.sel["review_total"], 3000)
        except ElementNotFound:
            raise OutOfStock("no booking summary", []) from None
        lines = []
        for r in await self._rows("review_line"):
            try:
                lines.append(QuoteLine(variant_id=safe_id(r["variant_id"], "variant id"),
                                       name=clean_text(self._kit, r.get("name", ""), 60),
                                       price_paise=parse_inr(r["price"])))
            except (KeyError, ValidationError):
                raise LayoutChanged("summary line could not be read") from None
        tot = (await self._rows("review_total"))[:1]
        total = parse_inr(await self._text("review_total"), tot[0].get("currency", "") if tot else "")
        pol = (await self._rows("review_policy"))[:1]
        policy = Policy(free_until=pol[0].get("free_until", "").strip() if pol else "",
                        nonrefundable=tuple(x.strip()[:40] for x in (pol[0].get("nonrefundable", "")
                                                                     if pol else "").split(";") if x.strip()))
        try:
            return Quote(lines=lines, fees=await self._charges("review_fee_row"),
                         taxes=await self._charges("review_tax_row"), total_paise=total, policy=policy)
        except ValidationError:
            raise TotalsMismatch("booking totals on the page do not add up") from None

    async def finalize(self, approved: Quote) -> PaymentHandoff:
        """Re-read, then the ONE irreversible click (the caller armed it), then the pay page."""
        again = await self.read_quote()
        if again.total_paise != approved.total_paise:
            raise TotalsMismatch("the total changed since the booking was approved")
        await self._s.click(self.sel["proceed_to_pay"])
        return await self.read_handoff(approved.total_paise)


# ------------------------------------------------------------------ the adapter base
def _day(value: Any) -> date | None:
    s = str(value or "")
    if not _ISO_DAY.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def clean_names(raw: Any) -> list[str]:
    """Names exactly as the user gave them (trimmed, plain letters). Anything else is dropped,
    so an empty result means "ask the user": a name is NEVER made up."""
    items = [raw] if isinstance(raw, str) else list(raw or [])
    out = []
    for x in items:
        n = re.sub(r"\s+", " ", str(x or "")).strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,59}", n):
            out.append(n)
    return out


class StayAdapter:
    """Protocol of FoodAdapter / MovieAdapter. Subclasses set ``cfg``, ``key``, ``site``,
    ``site_name`` and ``kind``; the rest is shared."""

    cfg: SiteConfig
    key: str
    site: str
    site_name: str
    kind: str  # hotel | flight
    use_case: str
    required: tuple[str, ...] = ()

    def __init__(self, ctx: RunCtx) -> None:
        self.ctx, self.gate = ctx, ActionGate(now=ctx.now)
        self.kit = build_kit(ctx.session, self.cfg, task_id=ctx.task_id, repairer=ctx.repairer)
        kw: dict[str, Any] = dict(cfg=self.cfg, base_url=ctx.base_url, task_id=ctx.task_id,
                                  otp_channel=ctx.otp, phone=ctx.profile.phone or None,
                                  on_code_wait=ctx.on_code_wait, otp_wait_s=ctx.otp_wait_s,
                                  poll_s=ctx.poll_s)
        if ctx.sleep:
            kw["sleep"] = ctx.sleep
        self.conn = StayConnector(self.kit.session, **kw)
        self.conn._kit = self.kit  # noqa: SLF001 - so page text is injection-stripped when read

    @property
    def link(self) -> str:
        return self.cfg.home

    def flags(self) -> dict[str, bool]:
        return {"injection": self.kit.safety.injection_count > 0, "repaired": bool(self.kit.repairs.records)}

    # ---- slots
    def _need(self, slot: str, what: str = "") -> Prepared:
        return Prepared(problem=HandoverProblem("need_info", what or slot, slot=slot, link=self.link))

    def _validate(self, slots: dict[str, Any]) -> tuple[dict[str, Any] | None, Prepared | None]:
        today = self.ctx.now().date()
        if self.kind == "hotel":
            if not str(slots.get("destination", "")).strip():
                return None, self._need("destination")
            cin, cout = _day(slots.get("checkin")), _day(slots.get("checkout"))
            if cin is None or cin < today:
                return None, self._need("checkin")
            if cout is None or cout <= cin:
                return None, self._need("checkout")
            if not clean_names(slots.get("guest_name")):
                return None, self._need("guest_name")
            rooms, guests = _int(slots.get("rooms"), 1, 8), _int(slots.get("guests"), 2, 20)
            params = {"destination": str(slots["destination"]).strip()[:60], "checkin": cin.isoformat(),
                      "checkout": cout.isoformat(), "rooms": rooms, "guests": guests}
            return {"params": params, "qty": rooms, "guest": clean_names(slots["guest_name"])[0],
                    "names": [], "when": f"{cin.isoformat()} to {cout.isoformat()}",
                    "nights": (cout - cin).days}, None
        if not str(slots.get("origin", "")).strip():
            return None, self._need("origin")
        if not str(slots.get("destination", "")).strip():
            return None, self._need("destination")
        dep = _day(slots.get("depart_date"))
        if dep is None or dep < today:
            return None, self._need("depart_date")
        trip = "return" if str(slots.get("trip", "")).lower().startswith("ret") else "one_way"
        back = _day(slots.get("return_date"))
        if trip == "return" and (back is None or back < dep):
            return None, self._need("return_date")
        names = clean_names(slots.get("passengers"))
        want = _int(slots.get("passenger_count"), len(names) or 1, 9)
        if not names or len(names) != want:  # never invent, never pad: the user names every traveller
            return None, self._need("passengers", f"{want} passenger name(s) as on the ID")
        params = {"origin": str(slots["origin"]).strip()[:60], "destination": str(slots["destination"]).strip()[:60],
                  "depart": dep.isoformat(), "return_date": back.isoformat() if back else "",
                  "trip": trip, "adults": len(names)}
        return {"params": params, "qty": len(names), "guest": "", "names": names,
                "when": dep.isoformat() + (f" / return {back.isoformat()}" if back else ""),
                "nights": 0}, None

    # ---- prepare (read-only)
    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        v, problem = self._validate(slots)
        if problem:
            return problem
        assert v is not None
        params = v["params"]
        budget = _paise(slots.get("budget"))
        try:
            options = await self.conn.search(self.kind, **params)
            if not options:
                return Prepared(problem=Problem("no_match", str(params["destination"])))
            shortlist = sorted(options, key=lambda o: o.price_paise)[:5]
            choice = _int(slots.get("choice"), 0, 5)
            order = [shortlist[choice - 1]] if 1 <= choice <= len(shortlist) else shortlist
            picked, sold, over = None, False, False
            for opt in order:
                found = await self.conn.variants(self.kind, opt.item_id, **params)
                live = [x for x in found if not x.sold_out]
                sold = sold or (bool(found) and not live)
                fit = [x for x in live if (budget is None or x.total_paise <= budget)
                       and (not slots.get("free_cancellation") or x.free_until)]
                over = over or (bool(live) and not fit)
                if fit:
                    picked = (opt, min(fit, key=lambda x: x.total_paise))
                    break
        except ForeignCurrency:
            return Prepared(problem=HandoverProblem("foreign_currency", self.site_name, link=self.link))
        if picked is None:
            if over:
                return Prepared(problem=Problem("no_match", "an option within your budget"))
            return Prepared(problem=Problem("out_of_stock" if sold else "no_match", str(params["destination"])))
        opt, var = picked
        pol = Policy(free_until=var.free_until, nonrefundable=var.nonrefundable)
        lines = [f"{opt.name} - {var.name} ({format_rupees(var.total_paise)} incl. taxes and fees)"]
        lines += _policy_lines(pol)
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=opt.name,
            area=str(params["destination"]), lines=lines, subtotal_paise=var.total_paise,
            max_total_paise=var.total_paise, when=v["when"],
            details={"kind": self.kind, "item_id": opt.item_id, "variant_id": var.variant_id,
                     "variant": var.name, "qty": v["qty"], "params": params, "guest": v["guest"],
                     "names": v["names"], "nights": v["nights"], "currency": "INR",
                     "free_until": var.free_until, "nonrefundable": list(var.nonrefundable),
                     "shortlist": [{"n": i, "name": o.name, "from_paise": o.price_paise}
                                   for i, o in enumerate(shortlist, 1)]},
            expires_at=self.ctx.now() + APPROVAL_TTL))

    # ---- execute (after approval)
    async def execute(self, p: Proposal) -> ExecResult:
        d = p.details
        item, var, qty = d["item_id"], d["variant_id"], int(d["qty"])
        grant = Grant(task_id=self.ctx.task_id, connector=self.key, restaurant_id=item,
                      items=[ItemQty(item_id=var, qty=qty)], max_total_paise=p.max_total_paise,
                      expires_at=self.ctx.now() + APPROVAL_TTL)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "restaurant_id": item,
                "items": [{"item_id": var, "qty": qty}]}
        if self.gate.decide("build_cart", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        await self.conn.ensure_logged_in()
        try:
            quote_ = await self.conn.begin(self.kind, item, var, d["params"], list(d["names"]), d["guest"])
        except OutOfStock as e:
            return ExecResult("out_of_stock", names=", ".join(e.names) or "that option", notes=self.flags())
        grant.mark_used("build_cart")
        approved = Policy(free_until=d.get("free_until", ""), nonrefundable=tuple(d.get("nonrefundable", [])))
        if quote_.total_paise > p.max_total_paise or quote_.policy.worse_than(approved):
            reason = ("the price on the site went up" if quote_.total_paise > p.max_total_paise
                      else "the cancellation terms on the site got worse")
            return ExecResult("reapprove", reason=reason, proposal=_rebuilt(p, quote_, self.ctx.now() + APPROVAL_TTL),
                              notes=self.flags())
        pay = {**args, "total_paise": quote_.total_paise}
        if self.gate.decide("get_payment_handoff", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        with self.kit.safety.approved("proceed_to_pay"):
            handoff = await self.conn.finalize(quote_)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=quote_.total_paise, notes=self.flags())


def _rebuilt(p: Proposal, q: Quote, expires_at: Any) -> Proposal:
    lines = [f"{x.name} ({format_rupees(x.price_paise)})" for x in q.lines]
    lines.append(f"Total {format_rupees(q.total_paise)} incl. taxes and fees")
    lines += _policy_lines(q.policy)
    return p.model_copy(update={
        "lines": lines, "subtotal_paise": q.total_paise, "max_total_paise": q.total_paise,
        "exact": True, "expires_at": expires_at,
        "details": {**p.details, "free_until": q.policy.free_until,
                    "nonrefundable": list(q.policy.nonrefundable)}})


def _policy_lines(pol: Policy) -> list[str]:
    out = [f"Free cancellation until {pol.free_until}" if pol.free_until else "No free cancellation"]
    if pol.nonrefundable:
        out.append("Non-refundable: " + ", ".join(pol.nonrefundable))
    return out


def _int(v: Any, default: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if 0 <= n <= hi else default


def _paise(v: Any) -> int | None:
    """A budget in rupees from the user (int, '5000' or '₹5,000') -> paise, or None."""
    if v in (None, "", 0):
        return None
    try:
        return int(float(re.sub(r"[^\d.]", "", str(v))) * 100)
    except ValueError:
        return None


__all__ = ["HotelAdapter", "FlightAdapter", "Dialect", "SiteConfig", "ScriptedSiteBase", "StayConnector", "StayAdapter",
           "HandoverProblem", "build_kit", "parse_inr", "clean_text", "clean_names"]


class HotelAdapter(StayAdapter):
    kind = use_case = "hotel"
    required = ("destination", "checkin", "checkout", "guest_name")


class FlightAdapter(StayAdapter):
    kind = use_case = "flight"
    required = ("origin", "destination", "depart_date", "passengers")
