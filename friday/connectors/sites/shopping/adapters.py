# ruff: noqa: E501
"""Shopping adapters: ``amazon.shopping`` and ``flipkart.shopping``.

Buy: search -> shortlist of at most 5 (price, rating count, seller / fulfilment) -> the USER picks ->
variant asked, never guessed -> delivery address confirmed -> return policy read back -> approval
card with a total cap (delivery and fees included) -> login -> price re-check -> add to cart ->
extras unticked -> checkout address check -> total check (a rise means ask again) -> ONE armed
click -> QR / UPI hand-off. Friday never pays.
Track (``slots["intent"] == "track"``): read-only order status. Cancel (``"cancel"``): irreversible,
its own approval, its own armed click.
"""

from __future__ import annotations

from typing import Any

from friday.connectors.contract import ItemQty, format_rupees
from friday.connectors.sites.adapters import ExecResult, Prepared, Problem, Proposal
from friday.connectors.sites.errors import OutOfStock
from friday.connectors.sites.shopping.connector import ShopConnector, make_kit
from friday.connectors.sites.shopping.contract import OrderRow, Product, ProductPage, Variant
from friday.connectors.sites.shopping.gate import ShopGate
from friday.connectors.sites.train.base import ScriptedAdapter
from friday.connectors.sites.train.common import AddOnStuck, clean, norm

SHORTLIST = 5
FEE_MARGIN = 10000  # paise above price + the delivery fee shown: fees only visible at checkout (an assumption)


def product_line(i: int, p: Product) -> str:
    rating = f"{p.rating} stars, {p.rating_count:,} ratings" if p.rating is not None else f"{p.rating_count:,} ratings"
    return f"{i}. {p.title}: {format_rupees(p.price_paise)}, {rating}, sold by {p.seller or 'unknown seller'}, {p.fulfilment or 'fulfilment not shown'}"


def pick_product(shortlist: list[Product], want: Any) -> Product | None:
    """Only from the shortlist the user saw: a number, a product id or words of the title."""
    w = str(want or "").strip()
    if not w:
        return None
    if w.isdigit() and 1 <= int(w) <= len(shortlist):
        return shortlist[int(w) - 1]
    hit = [p for p in shortlist if w == p.product_id or (norm(w) and norm(w) in norm(p.title))]
    return hit[0] if len(hit) == 1 else None


def match_variants(variants: list[Variant], want: Any) -> list[Variant]:
    """Variants whose label contains every word the user said (so "black" with two sizes stays ambiguous)."""
    words = [norm(x) for x in str(want or "").replace(",", " ").split() if norm(x)]
    if not words:
        return []
    return [v for v in variants if all(w in norm(v.label) for w in words)]


class _ShopAdapter(ScriptedAdapter):
    use_case = "shopping"
    required = ("query",)
    gate_cls = ShopGate

    def make_kit(self):  # noqa: ANN201
        return make_kit(self.ctx.session, self.site, task_id=self.ctx.task_id, repairer=self.ctx.repairer)

    def make_conn(self) -> ShopConnector:
        return ShopConnector(self.kit.session, site=self.site, **self._kw())

    def missing(self, slots: dict[str, Any]) -> str | None:
        if not slots.get("query") and not slots.get("order_id"):
            return "query"
        return None

    def _intent(self, slots: dict[str, Any]) -> str:
        v = str(slots.get("intent") or "buy").lower()
        return v if v in {"track", "cancel"} else "buy"

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        if self.missing(slots):
            return self._need("need_detail", "query", "q_shop_query", "what to buy")
        intent = self._intent(slots)
        if intent == "buy":
            return await self._prepare_buy(slots)
        return await self._prepare_order(slots, intent)

    # ---------------------------------------------------------------- buy
    async def _prepare_buy(self, slots: dict[str, Any]) -> Prepared:
        found = (await self.conn.search(str(slots["query"])))[:SHORTLIST]
        if not found:
            return Prepared(problem=Problem("no_match", str(slots["query"])[:60]))
        pick = pick_product(found, slots.get("pick"))
        if pick is None:  # the user chooses: we never choose a product for them
            return self._need("need_choice", "pick", "q_shop_pick", "which product",
                              [product_line(i, p) for i, p in enumerate(found, 1)])
        page = await self.conn.product(pick.product_id)
        if not page.in_stock:
            return Prepared(problem=Problem("out_of_stock", page.title))
        chosen, unit = None, page.price_paise
        if page.variants:
            hits = match_variants(page.variants, slots.get("variant"))
            if len(hits) != 1:  # none said, none matches, or still ambiguous: ask, never guess
                opts = [v.label + ("" if v.available else " (not available)") for v in (hits or page.variants)]
                return self._need("need_detail", "variant", "q_shop_variant", "which size or colour", opts)
            chosen = hits[0]
            if not chosen.available:
                return Prepared(problem=Problem("out_of_stock", f"{page.title} ({chosen.label})"))
            unit = chosen.price_paise
        address = str(slots.get("address") or self.ctx.profile.address or "")
        if not address:
            return self._need("need_detail", "address", "q_address", "delivery address")
        qty = max(1, min(int(slots.get("qty") or 1), 10))
        est = unit * qty + page.delivery_fee_paise
        budget = int(slots.get("budget_paise") or 0)
        if budget and est > budget:
            return Prepared(problem=Problem("over_budget", f"{page.title} is {format_rupees(est)} with delivery"))
        cap = budget or est + FEE_MARGIN
        label = f" ({chosen.label})" if chosen else ""
        lines = [f"{qty} x {page.title}{label} ({format_rupees(unit * qty)})",
                 f"Seller: {pick.seller or 'unknown'}; {pick.fulfilment or 'fulfilment not shown'}; "
                 f"{pick.rating_count:,} ratings",
                 f"Delivery: {format_rupees(page.delivery_fee_paise) if page.delivery_fee_paise else 'free'}"
                 + (f", {page.delivery_estimate}" if page.delivery_estimate else ""),
                 f"Returns: {page.return_policy or 'the site shows no return policy'}"]
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name, lines=lines,
            subtotal_paise=unit * qty, max_total_paise=cap, address=address,
            details={"mode": "buy", "product_id": pick.product_id, "variant_id": chosen.variant_id if chosen else "",
                     "title": page.title, "qty": qty, "unit": unit, "return_policy": page.return_policy,
                     "delivery_fee": page.delivery_fee_paise, "shortlist": [product_line(i, p) for i, p in enumerate(found, 1)]},
            expires_at=self._expires()))

    async def execute(self, p: Proposal) -> ExecResult:
        mode = p.details.get("mode")
        if mode == "track":
            return ExecResult("info", reason="\n".join(p.lines), notes=self.flags())
        if mode == "cancel":
            return await self._execute_cancel(p)
        return await self._execute_buy(p)

    async def _execute_buy(self, p: Proposal) -> ExecResult:
        d = p.details
        group = f"{d['product_id']}|{d['variant_id']}"
        items = [ItemQty(item_id=group, qty=d["qty"])]
        grant, args = self._grant(group, items, p.max_total_paise), self._args(group, items)
        if not self._allowed("build_cart", args, grant):
            return self._reask(p, "approval no longer matches")
        await self.conn.ensure_logged_in()
        page: ProductPage = await self.conn.product(d["product_id"])
        var = next((v for v in page.variants if v.variant_id == d["variant_id"]), None)
        if not page.in_stock or (d["variant_id"] and (var is None or not var.available)):
            return ExecResult("out_of_stock", names=d["title"], notes=self.flags())
        now_unit = var.price_paise if var else page.price_paise
        if now_unit > d["unit"]:
            return self._rise(p, now_unit, d["qty"], page.delivery_fee_paise, "the price on the site went up")
        await self.conn.add_to_cart(d["product_id"], d["variant_id"], d["qty"])
        grant.mark_used("build_cart")
        notes = self.flags()
        try:
            quote = await self._clean_quote(self.conn.cart, d, notes)
            site_address = await self.conn.go_checkout()
            if not self._same_address(site_address, p.address):
                return self._reask(p, "the delivery address on the site is different", address=site_address, notes=notes)
            quote = await self._clean_quote(self.conn.read_quote, d, notes)
        except AddOnStuck as e:
            return self._stuck(p, e, notes)
        line = quote.lines[0]
        if line.unit_paise > d["unit"] or quote.total_paise > p.max_total_paise:
            return self._rise(p, line.unit_paise, d["qty"], quote.total_paise - line.total_paise, "the price on the site went up", total=quote.total_paise, notes=notes)
        pay = {**args, "total_paise": quote.total_paise}
        if not self._allowed("get_payment_handoff", pay, grant):
            return self._reask(p, "approval no longer matches")
        with self.kit.safety.approved("order_confirm_button"):
            handoff = await self.conn.confirm_order(quote.total_paise)
        return ExecResult("payment_ready", handoff=handoff, amount_paise=quote.total_paise, notes=notes)

    async def _clean_quote(self, read, d: dict[str, Any], notes: dict[str, bool]):  # noqa: ANN001, ANN202
        """Read cart or checkout, make sure it holds exactly the approved item, untick extras."""
        from friday.connectors.contract import CartMismatch

        q = await read()
        if len(q.lines) != 1 or q.lines[0].product_id != d["product_id"] or q.lines[0].qty != d["qty"] \
                or (d["variant_id"] and q.lines[0].variant_id != d["variant_id"]):
            raise CartMismatch("the cart holds something other than the approved item")
        if q.ticked():
            q = await self.conn.untick_addons()
            notes["addon_unticked"] = True
        return q

    def _same_address(self, site: str, mine: str) -> bool:
        a, b = norm(site), norm(mine)
        return bool(a and b and (a in b or b in a))

    def _rise(self, p: Proposal, unit: int, qty: int, extra: int, reason: str, *, total: int | None = None,
              notes: dict[str, bool] | None = None) -> ExecResult:
        d = p.details
        sub = unit * qty
        new_total = total if total is not None else sub + extra + FEE_MARGIN
        lines = [f"{qty} x {d['title']} ({format_rupees(sub)})", *p.lines[1:]]
        return self._reask(p, reason, subtotal_paise=sub, max_total_paise=max(new_total, sub), lines=lines,
                           details={**d, "unit": unit}, notes=notes)

    def _stuck(self, p: Proposal, e: AddOnStuck, notes: dict[str, bool]) -> ExecResult:
        q = e.quote
        notes["addon_stuck"] = True
        extras = [f"Extra on the site: {a.label} ({format_rupees(a.amount_paise)})" for a in q.ticked()]
        return self._reask(p, "an extra (" + ", ".join(e.names) + ") could not be removed and is in the total",
                           subtotal_paise=q.subtotal_paise, max_total_paise=q.total_paise,
                           lines=[*p.lines, *extras], notes=notes)

    # ---------------------------------------------------------------- track / cancel
    async def _find_order(self, slots: dict[str, Any]) -> tuple[OrderRow | None, Prepared | None]:
        await self.conn.ensure_logged_in()
        rows = await self.conn.orders()
        oid, q = str(slots.get("order_id") or ""), norm(str(slots.get("query") or ""))
        hits = [r for r in rows if (oid and r.order_id == oid) or (not oid and q and q in norm(r.title))]
        if not hits:
            return None, Prepared(problem=Problem("no_match", "that order"))
        if len(hits) > 1:
            return None, self._need("need_choice", "order_id", "q_shop_order", "which order",
                                    [f"{r.order_id}: {r.title}, {r.status}" for r in hits])
        return hits[0], None

    async def _prepare_order(self, slots: dict[str, Any], intent: str) -> Prepared:
        row, stop = await self._find_order(slots)
        if row is None:
            return stop  # type: ignore[return-value]
        if intent == "track":
            return Prepared(proposal=Proposal(
                task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name,
                lines=[f"Order {row.order_id}: {row.title} is {row.status}"], subtotal_paise=0, max_total_paise=0,
                details={"mode": "track", "read_only": True, "order_id": row.order_id, "status": row.status},
                expires_at=self._expires()))
        if not row.cancellable:
            return Prepared(problem=Problem("not_allowed", f"{row.title} can no longer be cancelled ({row.status})"))
        amount = max(row.amount_paise, 1)
        return Prepared(proposal=Proposal(
            task_id=self.ctx.task_id, connector=self.key, merchant=self.site_name,
            lines=[f"CANCEL order {row.order_id}: {row.title} ({format_rupees(row.amount_paise)}). This cannot be undone."],
            subtotal_paise=amount, max_total_paise=amount,
            details={"mode": "cancel", "order_id": row.order_id, "title": row.title},
            expires_at=self._expires()))

    async def _execute_cancel(self, p: Proposal) -> ExecResult:
        oid = p.details["order_id"]
        grant = self._grant(oid, [ItemQty(item_id="cancel", qty=1)], p.max_total_paise)
        args = {"task_id": self.ctx.task_id, "connector": self.key, "order_id": oid}
        if not self._allowed("cancel_order", args, grant):
            return self._reask(p, "approval no longer matches")
        await self.conn.ensure_logged_in()
        row = next((r for r in await self.conn.orders() if r.order_id == oid), None)
        if row is None or not row.cancellable:
            return ExecResult("no_match", names=p.details.get("title", "the order"), notes=self.flags())
        with self.kit.safety.approved("cancel_confirm_button"):
            state = await self.conn.cancel_order(oid)
        return ExecResult("done", reason=f"Order {oid}: {state}", names=p.details.get("title", ""), notes=self.flags())

    async def track(self, slots: dict[str, Any]) -> str:
        """Convenience: read-only status line of an existing order (login may be needed)."""
        prep = await self._prepare_order({**slots, "intent": "track"}, "track")
        return prep.proposal.lines[0] if prep.proposal else (prep.problem.what if prep.problem else "")


class AmazonShoppingAdapter(_ShopAdapter):
    key, site, site_name = "amazon.shopping", "amazon", "Amazon India"


class FlipkartShoppingAdapter(_ShopAdapter):
    key, site, site_name = "flipkart.shopping", "flipkart", "Flipkart"


ADAPTERS = {"amazon.shopping": AmazonShoppingAdapter, "flipkart.shopping": FlipkartShoppingAdapter}
__all__ = ["ADAPTERS", "AmazonShoppingAdapter", "FlipkartShoppingAdapter", "OutOfStock", "clean"]
