# ruff: noqa: E501
"""The shopping assistant in the chat: proactive comparison first, the delivery-place question last.

    "atta" -> progress line -> the grocery site agents (PM, A2A, parallel) -> headline with ONE pick ->
    product image cards (web chat only, cited images only) -> comparison + freshness + sources + ONE
    question: "Home or PG?" (buttons from the saved places; no pincode question while a place is saved).

The recommendation never waits for the place. The place only refines price and availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, ReplyButton, User
from friday.planner import signals as sg
from friday.shopping import catalog, places
from friday.shopping import wording as w
from friday.shopping.agent import ShoppingAgent
from friday.shopping.compare import Product, ShoppingInput, ShoppingOutput

log = get_logger(__name__)
_IST = timezone(timedelta(hours=5, minutes=30))
BTN = "shop:place:"
PENDING_TTL = timedelta(minutes=30)
_BTN_KEY = {"home": "btn_home", "pg": "btn_pg", "office": "btn_office"}
_LABEL_KEY = {"home": "label_home", "pg": "label_pg", "office": "label_office"}


@dataclass
class Pending:
    inp: ShoppingInput
    cat: catalog.Category
    at: datetime
    awaiting: str  # "tap" (buttons shown) | "text" (asked for the area once)
    office: bool = False
    kind_hint: str | None = None
    last_pick: str | None = None


def unit_label(out: ShoppingOutput) -> str:
    return "kg" if out.unit == "kg" else "L"


def product_line(p: Product, unit: str, lang: str) -> str:
    """Price, per kg/L, rating, delivery time: only values the pages printed."""
    if p.price_inr is None:
        return w.line("price_hidden", lang)
    bits = [f"Rs {p.price_inr:g} ({p.store})" if p.store else f"Rs {p.price_inr:g}"]
    if p.price_per_unit:
        bits.append(f"Rs {p.price_per_unit:g}/{unit}")
    if p.rating:
        bits.append(f"{p.rating:g}*")
    if p.delivery_time:
        bits.append(p.delivery_time)
    return ", ".join(bits)


def row(i: int, p: Product, unit: str, lang: str) -> str:
    text = f"{i}. {p.title}: {product_line(p, unit, lang)}"
    others = [f"{o.store} Rs {o.price_inr:g}" for o in p.offers if o.store != p.store and o.price_inr is not None][:2]
    return text + (f" ({w.line('also', lang)} {', '.join(others)})" if others else "")


class ShoppingAssistant:
    def __init__(self, pipeline: Any, agent: ShoppingAgent, *, image_cards: bool | None = None) -> None:
        self.p, self.agent = pipeline, agent
        self._image_cards = image_cards  # None: detect (web chat only)
        self._pending: dict[str, Pending] = {}

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.p.clock.now()

    def image_cards(self) -> bool:
        if self._image_cards is not None:
            return self._image_cards
        return bool(getattr(getattr(self.p.notifier, "messaging", None), "is_web", False))

    async def _say(self, user: User, text: str, buttons: list[ReplyButton] | None = None) -> None:
        await self.p.reply(user, text, buttons or [])

    def matches(self, text: str) -> catalog.Category | None:
        return catalog.is_shopping_request(text)

    # ------------------------------------------------------------------ entry
    async def handle(self, user: User, msg: InboundMessage, lang: str) -> bool:
        pend = self._pending.get(user.id)
        if pend is not None and self._now() - pend.at > PENDING_TTL:
            self._pending.pop(user.id, None)
            pend = None
        if msg.kind == MessageKind.BUTTON_REPLY:
            bid = msg.button_id or ""
            if not bid.startswith(BTN) or pend is None:
                return False
            return await self._choose(user, pend, bid[len(BTN):], None, lang)
        text = (msg.text or "").strip()
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE) or not text:
            return False
        cat = self.matches(text)
        if cat is not None:
            self._pending.pop(user.id, None)
            await self.start(user, cat, text, lang)
            return True
        if pend is not None:
            ans = places.parse_answer(text)
            if ans is None:
                self._pending.pop(user.id, None)  # something else: let the normal flow have it
                return False
            if pend.kind_hint and places.kind_of(text) is None:
                ans = ans.model_copy(update={"kind": pend.kind_hint})
            return await self._choose(user, pend, ans.kind, ans, lang)
        return False

    # ------------------------------------------------------------------ the comparison
    async def start(self, user: User, cat: catalog.Category, text: str, lang: str) -> None:
        inp = ShoppingInput(query=text, category_id=cat.id, retailer=sg.retailer_in(text), pincode=sg.pincode_in(text), lang=lang)
        await self._say(user, w.line("progress", lang, sites=", ".join(self.agent.site_names()), cat=cat.id))
        out = await self.agent.run(inp)
        await self._deliver(user, out, inp, cat, lang, text)

    def _soft_fail(self, out: ShoppingOutput, cat: catalog.Category, lang: str) -> str:
        names = ", ".join(cat.popular[:3])
        key = "soft_fail_down" if out.status == "unavailable" else "soft_fail"
        return w.line(key, lang, cat=cat.id, names=names)

    def _stamp(self, out: ShoppingOutput) -> str:
        return out.as_of.astimezone(_IST).strftime("%d %b %H:%M")

    def _comparison(self, out: ShoppingOutput, lang: str, *, header: str | None = None) -> str:
        unit = unit_label(out)
        lines = [header] if header else []
        lines += [row(i, p, unit, lang) for i, p in enumerate(out.products, 1)]
        lines.append(w.line("fresh", lang, time=self._stamp(out)))
        if out.retailer_price_hidden and out.retailer:
            lines.append(w.line("store_hidden", lang, store=out.retailer.title()))
        tried = [s for s in out.sites if s.status != "skipped"]  # extras that were not needed are not "unread"
        unread = [s.display for s in tried if s.status != "ok"]
        if tried:
            ok = sum(1 for s in tried if s.status == "ok")
            lines.append(w.line("sites_read", lang, ok=str(ok), n=str(len(tried))))
        if unread:
            lines.append(w.line("sites_unread", lang, names=", ".join(unread)))
        if out.sources:
            lines.append(f"{w.line('sources', lang)} " + " ".join(s.url for s in out.sources[:3]))
        return "\n".join(lines)

    def _headline(self, out: ShoppingOutput, cat: catalog.Category, lang: str) -> str:
        if out.recommendation is None:
            return w.line("pick_none", lang, cat=cat.id)
        rec = out.recommendation
        return w.line("pick", lang, n=str(len(out.products)), cat=cat.id, name=rec.product.title, reason=rec.reason)

    async def _send_cards(self, user: User, out: ShoppingOutput, lang: str) -> None:
        if not self.image_cards():
            return
        unit = unit_label(out)
        for p in out.products[:4]:
            if not p.image_url:
                continue
            caption = w.line("card_caption", lang, name=p.title, line=product_line(p, unit, lang))
            try:
                await self.p.notifier.notify_user(user.id, caption, media_url=p.image_url, media_mime="image/jpeg")
            except Exception:  # noqa: BLE001 - a card is a nicety; the text comparison follows anyway
                log.info("shopping: image card failed")

    async def _deliver(self, user: User, out: ShoppingOutput, inp: ShoppingInput, cat: catalog.Category, lang: str, text: str) -> None:
        if out.status != "ok":
            await self._say(user, self._soft_fail(out, cat, lang))
            return
        await self._say(user, self._headline(out, cat, lang))
        await self._send_cards(user, out, lang)
        body = self._comparison(out, lang)
        if inp.pincode:  # the user already gave a place: nothing to ask
            await self._say(user, body)
            return
        office = catalog.wants_office(text)
        saved = await places.saved_places(self.p.repos, user.id, include_office=office)
        pend = Pending(inp=inp, cat=cat, at=self._now(), awaiting="tap" if saved else "text", office=office,
                       last_pick=out.recommendation.product.title if out.recommendation else None)
        self._pending[user.id] = pend
        if saved:
            buttons = [ReplyButton(id=BTN + d.kind, title=w.line(_BTN_KEY[d.kind], lang)) for d in saved]
            await self._say(user, f"{body}\n\n{w.line('place_ask_saved', lang)}", buttons)
        else:
            await self._say(user, f"{body}\n\n{w.line('place_ask_new', lang)}")

    # ------------------------------------------------------------------ the place refines the answer
    async def _choose(self, user: User, pend: Pending, kind: str, answer: places.DeliveryPlace | None, lang: str) -> bool:
        if kind not in places.KINDS:
            return False
        lines: list[str] = []
        if answer is None:
            saved = await places.saved_places(self.p.repos, user.id, include_office=True)
            dp = next((d for d in saved if d.kind == kind), None)
            if dp is None:
                return False
            if not dp.where:  # a saved place without an address: ask once for the area
                pend.awaiting, pend.kind_hint, pend.at = "text", kind, self._now()
                await self._say(user, w.line("place_ask_new", lang))
                return True
        else:
            dp = await places.save_place(self.p.repos, user.id, answer)
            lines.append(w.line("place_saved", lang, label=w.line(_LABEL_KEY[dp.kind], lang), where=dp.where))
        self._pending.pop(user.id, None)
        label = w.line(_LABEL_KEY[dp.kind], lang)
        inp = pend.inp.model_copy(update={"pincode": dp.pincode, "area": None if dp.pincode else dp.area})
        out = await self.agent.run(inp)
        if out.status != "ok":
            lines.append(w.line("refine_fail", lang))
            await self._say(user, "\n".join(lines))
            return True
        rec = out.recommendation
        if rec is None:
            header = w.line("place_checking", lang, label=label, where=dp.where)
        elif pend.last_pick and rec.product.title == pend.last_pick:
            header = w.line("refined_same", lang, label=label, name=rec.product.title)
        else:
            header = w.line("refined_new", lang, label=label, name=rec.product.title, reason=rec.reason)
        lines.append(self._comparison(out, lang, header=header))
        await self._say(user, "\n".join(lines))
        return True

