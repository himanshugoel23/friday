# ruff: noqa: E501
"""Shared grocery connector and adapter. Each site (sites.py) is a profile of selectors and quirks.

Rules kept here for every grocery site:
* ``prepare`` is read-only: search, stock, fees, ETA / slots, address. Nothing is added to a cart.
* Substitutions stay OFF. A sold-out item stops the run and ASKS for a substitute (the options are
  returned in ``problem.options``); this code never swaps an item by itself.
* After approval: cart built, prices / fees / address / slot re-checked. Any rise above what the
  user approved means a NEW approval card (never a silent go-ahead), then the one irreversible
  click (``checkout_button``) is armed, then payment is handed over as QR / UPI link. Never pays.
* Page text is untrusted: names go through the injection guard; a bot check stops the run for good.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import ValidationError

from friday.connectors.browser.port import BrowserSession, ElementNotFound
from friday.connectors.contract import (
    Cart,
    CartLine,
    Charge,
    ConnectorError,
    ItemQty,
    LayoutChanged,
    LoginRequired,
    PaymentHandoff,
    TotalsMismatch,
    format_rupees,
    rupees_to_paise,
)
from friday.connectors.gate import Grant, Verdict
from friday.connectors.scrub import scrub_text
from friday.connectors.sites.adapters import (
    APPROVAL_TTL,
    ExecResult,
    Prepared,
    Problem,
    Proposal,
    RunCtx,
    norm,
)
from friday.connectors.sites.errors import OutOfStock, SiteBlocked
from friday.connectors.sites.executor import AgentKit, GuardedSession
from friday.connectors.sites.grocery.contract import CartView, Product, Slot, StoreInfo
from friday.connectors.sites.grocery.profiles import IRREVERSIBLE, SiteProfile
from friday.connectors.sites.injection import strip_injection
from friday.connectors.sites.locator import ElementLocator, RepairLog, SelectorRepairer
from friday.connectors.sites.reader import PageReader
from friday.connectors.sites.safety import ExtendedGate, SiteSafety
from friday.connectors.sites.verifier import Expect, Verifier

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
TAX_BUFFER_PCT = 5  # headroom over the expected bill for rounding and small tax moves


@dataclass
class SiteProblem(Problem):
    """``Problem`` plus the kinds this package adds. The flow maps kinds it does not know to its
    generic 'could not find' wording, so see docs/BROWSER_GROCERY_RIDE.md for the mapping needed:
    needs_login, closed, below_minimum, no_slot (and ``options`` = substitutes to ask about)."""

    options: tuple[str, ...] = ()


def _sid(value: str, what: str) -> str:
    if not _SAFE_ID.match(value or ""):
        raise ConnectorError(f"unexpected {what} format")
    return value


def clean(text: str, kit: AgentKit | None = None, limit: int = 80) -> str:
    """A page label made safe: instruction-like sentences removed (and reported), short."""
    out, hits = strip_injection(text or "")
    if hits and kit is not None:
        kit.safety.note_injection([scrub_text(h) for h in hits])
    return re.sub(r"\s+", " ", out).strip()[:limit]


def build_kit(inner: BrowserSession, profile: SiteProfile, *, task_id: str,
              repairer: SelectorRepairer | None = None,
              extra_hosts: frozenset[str] = frozenset()) -> AgentKit:
    safety = SiteSafety(profile.hosts() | extra_hosts, IRREVERSIBLE)
    log = RepairLog()
    loc = ElementLocator(profile.selectors, profile.alternates, repairer=repairer, log=log,
                         task_id=task_id, irreversible=IRREVERSIBLE)
    pay = (profile.selectors["pay_amount"],)
    exp = {profile.selectors["checkout_button"]: Expect(present=pay)}
    for alt in profile.alternates.get("checkout_button", []):
        exp[alt] = Expect(present=pay)
    return AgentKit(GuardedSession(inner, safety, loc, PageReader(), Verifier(exp)), safety, loc, log)


class GroceryConnector:
    use_case = "grocery"
    backend = "scripted_browser"

    def __init__(self, session: BrowserSession, profile: SiteProfile, *, base_url: str,
                 task_id: str, kit: AgentKit | None = None) -> None:
        self._s, self.p, self._base, self._task = session, profile, base_url.rstrip("/"), task_id
        self._kit = kit
        self.blocked = False  # once a bot check was seen nothing else is sent to the site

    @property
    def site(self) -> str:
        return self.p.key

    def __repr__(self) -> str:
        return f"GroceryConnector({self.p.key!r}, task_id={self._task!r})"

    # ---- plumbing
    def _sel(self, key: str) -> str:
        return self.p.selectors[key]

    async def _goto(self, key: str, **params: str) -> None:
        if self.blocked:
            raise SiteBlocked("a bot check was shown earlier; not trying again")
        try:
            await self._s.goto(self._base + self.p.paths[key].format(
                **{k: quote(v, safe="") for k, v in params.items()}))
        except SiteBlocked:
            self.blocked = True
            raise

    async def _click(self, key: str, **params: str) -> None:
        try:
            await self._s.click(self._sel(key).format(**params))
        except SiteBlocked:
            self.blocked = True
            raise

    async def _text(self, key: str) -> str:
        try:
            return await self._s.text(self._sel(key))
        except ElementNotFound:
            raise LayoutChanged(f"selector '{key}' not found") from None

    async def _money(self, key: str) -> int:
        try:
            return rupees_to_paise(await self._text(key))
        except ValueError:
            raise LayoutChanged(f"'{key}' is not a money amount") from None

    async def _rows(self, key: str, fields: str | None = None) -> list[dict[str, str]]:
        return await self._s.query_all(self._sel(key), self.p.fields[fields or key])

    # ---- read-only
    async def store_info(self) -> StoreInfo:
        await self._goto("home")
        closed = bool(await self._s.query_all(self._sel("store_closed")))
        logged_in = bool(await self._s.query_all(self._sel("account_name")))
        addr = await self._s.query_all(self._sel("address_badge"))
        eta = await self._s.query_all(self._sel("eta_badge"))
        return StoreInfo(logged_in=logged_in, closed=closed,
                         address=clean(addr[0]["text"], self._kit, 120) if addr else "",
                         eta=clean(eta[0]["text"], self._kit, 30) if eta else "")

    def _products(self, rows: list[dict[str, str]]) -> list[Product]:
        out: list[Product] = []
        for r in rows:
            name = clean(r.get("name", ""), self._kit)
            if not name or not _SAFE_ID.match(r.get("item_id", "")):
                continue  # a label that was only an instruction, or an odd id: not trusted
            try:
                out.append(Product(item_id=r["item_id"], name=name,
                                   brand=clean(r.get("brand", ""), self._kit, 40),
                                   size=clean(r.get("size", ""), self._kit, 20),
                                   price_paise=rupees_to_paise(r["price"]),
                                   in_stock=r.get("stock", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError):
                continue
        return out

    async def search(self, query: str) -> list[Product]:
        await self._goto("search", q=query)
        return self._products(await self._rows("product_card"))

    async def product(self, item_id: str) -> Product | None:
        await self._goto("item", item_id=_sid(item_id, "item id"))
        found = self._products(await self._rows("product_card"))
        return found[0] if found else None

    async def slots(self) -> list[Slot]:
        await self._goto("slots")
        out: list[Slot] = []
        for r in await self._rows("slot_option"):
            try:
                out.append(Slot(slot_id=_sid(r["slot_id"], "slot id"),
                                label=clean(r.get("label", ""), self._kit, 40),
                                fee_paise=rupees_to_paise(r["fee"]) if r.get("fee") else 0,
                                available=r.get("available", "").lower() == "true"))
            except (KeyError, ValueError, ValidationError, ConnectorError):
                continue
        return out

    # ---- after approval
    async def ensure_logged_in(self) -> StoreInfo:
        info = await self.store_info()
        if not info.logged_in:
            raise LoginRequired("not logged in; the user must log in through the secure page")
        return info

    async def _substitutions(self) -> bool:
        rows = await self._rows("subs_toggle")
        if not rows:
            return False
        return rows[0].get("on", "").lower() == "true"

    async def _existing(self) -> dict[str, int]:
        await self._goto("cart")
        have: dict[str, int] = {}
        for r in await self._rows("cart_line"):
            try:
                have[_sid(r["item_id"], "item id")] = int(r["qty"])
            except (KeyError, ValueError):
                raise LayoutChanged("cart line could not be read") from None
        return have

    async def build_cart(self, items: list[tuple[str, int]], slot_id: str = "") -> CartView:
        await self.ensure_logged_in()
        have = await self._existing()  # a re-run after a re-ask finds our own earlier adds
        want = dict(items)
        if any(i not in want or n > want[i] for i, n in have.items()):
            raise ConnectorError("the cart already holds other items; not touching it")
        for item_id, qty in items:
            prod = await self.product(item_id)
            if prod is None or not prod.in_stock:
                raise OutOfStock("an item is sold out", [prod.name if prod else item_id])
            for _ in range(qty - have.get(item_id, 0)):
                try:
                    await self._click("add_button", item_id=item_id)
                except ElementNotFound:
                    raise OutOfStock("an item is sold out", [prod.name]) from None
        if self.p.kind == "scheduled" and slot_id:
            await self._goto("slots")
            try:
                await self._click("slot_pick", slot_id=_sid(slot_id, "slot id"))
            except ElementNotFound:
                raise OutOfStock("the delivery slot is taken", ["the delivery slot"]) from None
        await self._goto("cart")
        if await self._substitutions():  # quirk: some sites switch it on by themselves
            await self._click("subs_toggle")
            if await self._substitutions():
                raise ConnectorError("could not switch substitutions off")
        view = await self._read_cart(slot_id)
        if {ln.item_id for ln in view.cart.lines} != {i for i, _ in items}:
            raise ConnectorError("the cart holds other items than the approved ones")
        return view

    async def _read_cart(self, slot_id: str) -> CartView:
        try:
            await self._s.wait_for(self._sel("cart_total"), 3000)
        except ElementNotFound:
            raise OutOfStock("the cart is empty", []) from None
        lines: list[CartLine] = []
        for r in await self._rows("cart_line"):
            try:
                qty, unit, tot = int(r["qty"]), rupees_to_paise(r["unit"]), rupees_to_paise(r["total"])
                lines.append(CartLine(item_id=_sid(r["item_id"], "item id"),
                                      name=clean(r.get("name", ""), self._kit) or r["item_id"],
                                      qty=qty, unit_price_paise=unit, line_total_paise=tot))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged("cart line could not be read") from None
        fees, taxes = await self._charges("fee_row"), await self._charges("tax_row")
        try:
            cart = Cart(restaurant_id=self.p.key, lines=lines,
                        subtotal_paise=sum(x.line_total_paise for x in lines), fees=fees,
                        taxes=taxes, grand_total_paise=await self._money("cart_total"))
        except ValidationError:
            raise TotalsMismatch("cart totals on the page do not add up") from None
        addr = await self._s.query_all(self._sel("cart_address"))
        eta = await self._s.query_all(self._sel("cart_eta"))
        return CartView(cart=cart, address=clean(addr[0]["text"], self._kit, 120) if addr else "",
                        eta=clean(eta[0]["text"], self._kit, 30) if eta else "",
                        slot_id=slot_id, substitutions_on=await self._substitutions())

    async def _charges(self, key: str) -> list[Charge]:
        out = []
        for r in await self._rows(key, "charge_row"):
            try:
                out.append(Charge(name=clean(r["name"], self._kit, 40), amount_paise=rupees_to_paise(r["amount"])))
            except (KeyError, ValueError, ValidationError):
                raise LayoutChanged(f"'{key}' row could not be read") from None
        return out

    async def get_payment_handoff(self, view: CartView) -> PaymentHandoff:
        await self._goto("cart")
        again = await self._read_cart(view.slot_id)
        if again.cart.grand_total_paise != view.cart.grand_total_paise:
            raise TotalsMismatch("the total changed since the order was approved")
        await self._click("checkout_button")
        amount = await self._money("pay_amount")
        if amount != view.cart.grand_total_paise:
            raise TotalsMismatch("payment page amount differs from the approved order")
        merchant = clean(await self._text("pay_merchant"), self._kit, 60)
        ref = await self._s.query_all(self._sel("pay_order_ref"))
        qr = None
        for r in await self._s.query_all(self._sel("pay_qr"), {"src": "@src"}):
            if r.get("src", "").startswith("data:image/png;base64,"):
                try:
                    qr = base64.b64decode(r["src"].split(",", 1)[1], validate=True)
                except ValueError:
                    qr = None
        link = None
        for r in await self._s.query_all(self._sel("pay_upi_link"), {"href": "@href"}):
            href = r.get("href", "")
            if href.startswith("upi://pay"):
                am = parse_qs(urlsplit(href).query).get("am")
                if am and rupees_to_paise(am[0]) != amount:
                    raise TotalsMismatch("UPI link amount differs from the approved order")
                link = href
        if qr is None and link is None:
            raise LayoutChanged("no QR or UPI link on the payment page")
        try:
            return PaymentHandoff(kind="qr" if qr else "upi_intent", amount_paise=amount,
                                  merchant=merchant or self.p.name,
                                  order_ref=(clean(ref[0]["text"], self._kit, 30) if ref else None),
                                  qr_png=qr, upi_link=link)
        except ValidationError:
            raise LayoutChanged("payment page data failed validation") from None


def _line(qty: int, p: Product, unit: int) -> str:
    label = p.name
    if p.brand and p.brand.lower() not in label.lower():
        label = f"{p.brand} {label}"
    if p.size and p.size.lower() not in label.lower():
        label = f"{label} {p.size}"
    return f"{qty} x {label} ({format_rupees(unit * qty)})"


class GroceryAdapter:
    """What BrowserFlow drives. One subclass per site key sets ``key`` / ``site`` / ``profile``."""

    use_case = "grocery"
    required = ("items",)
    key = ""
    site = ""
    site_name = ""
    profile: SiteProfile

    def __init__(self, ctx: RunCtx) -> None:
        self.ctx = ctx
        self.gate = ExtendedGate(now=ctx.now)
        self.kit = build_kit(ctx.session, self.profile, task_id=ctx.task_id, repairer=ctx.repairer)
        self.conn = GroceryConnector(self.kit.session, self.profile, base_url=ctx.base_url,
                                     task_id=ctx.task_id, kit=self.kit)

    def flags(self) -> dict[str, bool]:
        return {"injection": self.kit.safety.injection_count > 0, "repaired": bool(self.kit.repairs.records)}

    def _problem(self, kind: str, what: str, options: tuple[str, ...] = ()) -> Prepared:
        return Prepared(problem=SiteProblem(kind, what, options))  # type: ignore[arg-type]

    # ------------------------------------------------------------ prepare (read-only)
    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        p, conn = self.profile, self.conn
        info = await conn.store_info()
        if not info.logged_in:
            return self._problem("needs_login", self.site_name)
        if info.closed:
            return self._problem("closed", self.site_name)
        picks: list[tuple[Product, int]] = []
        for w in slots["items"]:
            found = await conn.search(w["query"])
            hit = self._match(found, w)
            if not hit:
                return self._problem("no_match", w["query"])
            ok = [x for x in hit if x.in_stock]
            if not ok:  # sold out: never swap; offer what is in stock so the flow can ASK
                same = {x.item_id for x in hit}
                alts = tuple(f"{x.brand} {x.name} {x.size}".strip() for x in found
                             if x.in_stock and x.item_id not in same and self._similar(x, w))
                return self._problem("out_of_stock", hit[0].name, alts[:3])
            best, q = min(ok, key=lambda x: x.price_paise), max(1, int(w.get("qty", 1)))
            if any(b.item_id == best.item_id for b, _ in picks):  # same product named twice
                picks = [(b, n + q if b.item_id == best.item_id else n) for b, n in picks]
            else:
                picks.append((best, q))
        sub = sum(x.price_paise * q for x, q in picks)
        if p.hard_min and sub < p.min_cart_paise:
            return self._problem("below_minimum", f"{format_rupees(p.min_cart_paise - sub)} more "
                                 f"(minimum {format_rupees(p.min_cart_paise)})")
        slot_id, when, slot_fee = "", info.eta or p.default_eta, 0
        if p.kind == "scheduled":
            avail = [s for s in await conn.slots() if s.available]
            if not avail:
                return self._problem("no_slot", self.site_name)
            want = norm(str(slots.get("slot", "")))
            chosen = next((s for s in avail if want and want in norm(s.label)), avail[0])
            slot_id, when, slot_fee = chosen.slot_id, chosen.label, chosen.fee_paise
        fees = p.fees_for(sub, slot_fee)
        cap = (sub + fees + fees * 18 // 100) * (100 + TAX_BUFFER_PCT) // 100  # GST on fees + headroom
        address = slots.get("address") or self.ctx.profile.address or info.address
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=p.name,
            area=slots.get("area") or self.ctx.profile.area, lines=[_line(q, x, x.price_paise) for x, q in picks],
            subtotal_paise=sub, max_total_paise=cap, address=address, when=when,
            details={"store_id": p.key, "slot_id": slot_id, "substitutions": "off",
                     "expected_fees_paise": fees, "min_cart_paise": p.min_cart_paise,
                     "items": [{"item_id": x.item_id, "qty": q, "unit": x.price_paise,
                                "name": x.name} for x, q in picks]},
            expires_at=self.ctx.now() + APPROVAL_TTL))

    @staticmethod
    def _match(found: list[Product], w: dict[str, Any]) -> list[Product]:
        q = norm(w["query"])
        out = [x for x in found if q and q in norm(f"{x.brand}{x.name}")]
        if w.get("brand"):
            out = [x for x in out if norm(w["brand"]) in norm(x.brand + x.name)]
        if w.get("size"):
            out = [x for x in out if norm(w["size"]) == norm(x.size)]
        return out

    @staticmethod
    def _similar(x: Product, w: dict[str, Any]) -> bool:
        return norm(w["query"]) in norm(f"{x.brand}{x.name}")

    # ------------------------------------------------------------ execute (after approval)
    def _grant(self, p: Proposal) -> tuple[Grant, list[ItemQty]]:
        qty = [ItemQty(item_id=i["item_id"], qty=i["qty"]) for i in p.details["items"]]
        return Grant(task_id=self.ctx.task_id, connector=self.key, restaurant_id=p.details["store_id"],
                     items=qty, max_total_paise=p.max_total_paise,
                     expires_at=self.ctx.now() + APPROVAL_TTL), qty

    async def execute(self, p: Proposal) -> ExecResult:
        if self.conn.blocked:
            raise SiteBlocked("a bot check was shown earlier; not trying again")
        grant, qty = self._grant(p)
        args = {"task_id": self.ctx.task_id, "connector": self.key,
                "restaurant_id": p.details["store_id"], "items": [q.model_dump() for q in qty]}
        if self.gate.decide("build_cart", args, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        try:
            view = await self.conn.build_cart([(q.item_id, q.qty) for q in qty], p.details["slot_id"])
        except OutOfStock as e:
            return ExecResult("out_of_stock", names=", ".join(e.names) or "an item", notes=self.flags())
        grant.mark_used("build_cart")
        cart = view.cart
        unit = {i["item_id"]: i["unit"] for i in p.details["items"]}
        rose = [ln for ln in cart.lines if ln.unit_price_paise > unit.get(ln.item_id, 0)]
        addr = view.address
        wrong_addr = bool(addr and p.address and norm(p.address) not in norm(addr)
                          and norm(addr) not in norm(p.address))
        if rose or cart.grand_total_paise > p.max_total_paise or wrong_addr:
            reason = ("the delivery address on the site is different" if wrong_addr
                      else "prices or fees on the site went up")
            new = p.model_copy(update={
                "lines": [f"{ln.qty} x {ln.name} ({format_rupees(ln.line_total_paise)})" for ln in cart.lines],
                "subtotal_paise": cart.subtotal_paise, "max_total_paise": cart.grand_total_paise,
                "exact": True, "address": addr or p.address, "expires_at": self.ctx.now() + APPROVAL_TTL,
                "details": {**p.details, "items": [
                    {"item_id": ln.item_id, "qty": ln.qty, "unit": ln.unit_price_paise, "name": ln.name}
                    for ln in cart.lines], "fees_paise": sum(f.amount_paise for f in cart.fees)}})
            return ExecResult("reapprove", reason=reason, proposal=new, notes=self.flags())
        pay = {**args, "items": [q.model_dump() for q in cart.items()], "total_paise": cart.grand_total_paise}
        if self.gate.decide("get_payment_handoff", pay, [grant]) != Verdict.allow:
            return ExecResult("reapprove", reason="approval no longer matches", proposal=p)
        with self.kit.safety.approved("checkout_button"):
            handoff = await self.conn.get_payment_handoff(view)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=cart.grand_total_paise,
                          notes=self.flags())
