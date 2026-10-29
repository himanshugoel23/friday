# ruff: noqa: E501
"""The shopping assistant in the chat: proactive comparison first, the delivery-place question last.

    "atta" -> progress line -> the grocery site agents (PM, A2A, parallel) -> headline with ONE pick ->
    product image cards (web chat only, cited images only) -> comparison + freshness + sources + ONE
    question: "Home or PG?" (buttons from the saved places; no pincode question while a place is saved).

The recommendation never waits for the place. The place only refines price and availability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, ReplyButton, User
from friday.planner import signals as sg
from friday.replywriter import templates as rt
from friday.replywriter.schema import Button, Facts, ProductFact, ReplyInput
from friday.replywriter.service import context_from
from friday.shopping import catalog, places
from friday.shopping import wording as w
from friday.shopping.agent import ShoppingAgent
from friday.shopping.compare import Product, ShoppingInput, ShoppingOutput
from friday.style import StyleLayer

log = get_logger(__name__)
_IST = timezone(timedelta(hours=5, minutes=30))
BTN = "shop:place:"
BTN_CMP = "shop:cmp:"
_YES = re.compile(r"^\s*(yes|y|yeah|yep|haan|han|ha|haa|ok|okay|sure|please|kar\s*do|karo|zaroor|bilkul)\b", re.I)
_NO = re.compile(r"^\s*(no|nope|nah|nahi|nahin|na|not now|mat)\b", re.I)
_COMPARE = re.compile(r"\b(compare|comparison|tulna|sabse sasta|cheapest|kahan sasta|all (?:stores|apps|sites)|saare|sab (?:jagah|apps?|stores?))\b", re.I)
PENDING_TTL = timedelta(minutes=30)
_BTN_KEY = {"home": "btn_home", "pg": "btn_pg", "office": "btn_office"}
_LABEL_KEY = {"home": "label_home", "pg": "label_pg", "office": "label_office"}


@dataclass
class Pending:
    inp: ShoppingInput
    cat: catalog.Category
    at: datetime
    awaiting: str  # "tap" (buttons shown) | "text" (asked for the area once) | "compare" (one store was checked; offered the rest)
    text: str = ""
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
        self._style = StyleLayer.from_pipeline(pipeline)  # FRIDAY_STYLE_LAYER_ENABLED (off: no change)
        self._pending: dict[str, Pending] = {}

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.p.clock.now()

    def image_cards(self) -> bool:
        if self._image_cards is not None:
            return self._image_cards
        return bool(getattr(getattr(self.p.notifier, "messaging", None), "is_web", False))

    async def _say(self, user: User, text: str, buttons: list[ReplyButton] | None = None) -> None:
        parts = self._style.fit(text, source="shopping", kind="result", has_buttons=bool(buttons))
        for i, part in enumerate(parts):  # buttons ride on the last part
            await self.p.reply(user, part, (buttons or []) if i == len(parts) - 1 else [])

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
            if bid.startswith(BTN_CMP) and pend is not None and pend.awaiting == "compare":
                return await self._compare_answer(user, pend, bid[len(BTN_CMP):] == "yes", lang)
            if not bid.startswith(BTN) or pend is None or pend.awaiting == "compare":
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
        if pend is not None and pend.awaiting == "compare":  # one store was checked; the single question was "compare with the others?"
            if _YES.match(text) or _COMPARE.search(text):
                return await self._compare_answer(user, pend, True, lang)
            if _NO.match(text):
                return await self._compare_answer(user, pend, False, lang)
            self._pending.pop(user.id, None)  # something else: let the normal flow have it
            return False
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
        retailer = sg.retailer_in(text)
        scoped = self.agent.scope_site(retailer) is not None and not _COMPARE.search(text)  # one named store: check only it first
        inp = ShoppingInput(query=text, category_id=cat.id, retailer=retailer, pincode=sg.pincode_in(text), lang=lang, user_id=user.id, scoped=scoped)
        await self._progress(user, inp, cat, lang, text)
        out = await self.agent.run(inp)
        await self._deliver(user, out, inp, cat, lang, text)

    # ------------------------------------------------------------------ reply writer hooks (friday/replywriter)
    async def _compose(self, user: User, inp: ReplyInput, legacy: list[str]) -> list[str]:
        """The messages to send. With the reply writer off (or no service) this is exactly ``legacy``."""
        rs = getattr(self.p, "reply_service", None)
        if rs is None:
            return legacy
        out = await rs.respond(user.id, inp, legacy)
        return legacy if out.writer == "legacy" else list(out.messages)

    def _rinput(self, text: str, lang: str, intent: str, facts: Facts, **kw: Any) -> ReplyInput:
        return ReplyInput(intent=intent, facts=facts, **context_from(text, lang), **kw)  # type: ignore[arg-type]

    async def _progress(self, user: User, inp: ShoppingInput, cat: catalog.Category, lang: str, text: str) -> None:
        site = self.agent.scope_site(inp.retailer) if inp.scoped else None
        store = self.agent.pm.display(site) if site else None
        if store:
            legacy = rt.line("ack_one", lang, store=store, cat=cat.id)
            facts = Facts(store=store, category=cat.id)
        else:
            legacy = w.line("progress", lang, sites=", ".join(self.agent.site_names()), cat=cat.id)
            facts = Facts(stores=self.agent.site_names(), category=cat.id)
        for part in await self._compose(user, self._rinput(text, lang, "ack", facts), [legacy]):
            await self._say(user, part)

    def _facts(self, out: ShoppingOutput, cat: catalog.Category) -> Facts:
        def paise(v: float | None) -> int | None:
            return None if v is None else int(round(float(v) * 100))

        def mins(t: str | None) -> int | None:
            m = re.match(r"\s*(\d+)", t or "")
            return int(m.group(1)) if m else None

        unit = "kg" if out.unit == "kg" else "L"
        prods = [
            ProductFact(name=p.title, store=p.store, price_paise=paise(p.price_inr), per_unit_paise=paise(p.price_per_unit),
                        unit=unit if p.price_per_unit else None, pack=p.pack_label, delivery_minutes=mins(p.delivery_time), rating=p.rating)
            for p in out.products[:6]
        ]
        tried = [s for s in out.sites if s.status != "skipped"]
        rec = out.recommendation
        return Facts(
            store=out.scope, stores=[s.display for s in tried if s.status == "ok"],
            stores_unread=[] if out.scope else [s.display for s in tried if s.status != "ok"], stores_offered=list(out.others),
            category=cat.id, products=prods, pick=rec.product.title if rec else None, pick_reason=rec.reason if rec else None,
            as_of=self._stamp(out), links=[s.url for s in out.sources[:3]],
        )

    def _compare_buttons(self, lang: str) -> list[ReplyButton]:
        return [ReplyButton(id=BTN_CMP + "yes", title=w.line("btn_cmp_yes", lang)), ReplyButton(id=BTN_CMP + "no", title=w.line("btn_cmp_no", lang))]

    async def _compare_answer(self, user: User, pend: Pending, yes: bool, lang: str) -> bool:
        """The one closing question after a single-store check: 'compare with the others too?'."""
        self._pending.pop(user.id, None)
        if not yes:
            site = self.agent.scope_site(pend.inp.retailer)
            await self._say(user, w.line("compare_no", lang, store=self.agent.pm.display(site) if site else pend.cat.id))
            return True
        inp = pend.inp.model_copy(update={"scoped": False})
        await self._progress(user, inp, pend.cat, lang, pend.text)
        out = await self.agent.run(inp)
        await self._deliver(user, out, inp, pend.cat, lang, pend.text)
        return True

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
        if tried and not out.scope:
            ok = sum(1 for s in tried if s.status == "ok")
            lines.append(w.line("sites_read", lang, ok=str(ok), n=str(len(tried))))
        if unread and not out.scope:
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

    async def _proof(self, user: User, out: ShoppingOutput, cat: catalog.Category, lang: str) -> None:
        """PROOF card for a finished lookup (style layer only; see friday/evidence/action_proof.py)."""
        from friday.evidence.action_proof import send_card

        ok_sites = [s.display for s in out.sites if s.status == "ok"]
        res = {"status": out.status, "url": out.sources[0].url if out.sources else None, "site": ", ".join(ok_sites[:3] or ([out.scope] if out.scope else []))}  # the card turns a status code into plain words
        await send_card(self.p, user, res, kind="lookup", what=f"{cat.id} prices", lang=lang)

    async def _deliver(self, user: User, out: ShoppingOutput, inp: ShoppingInput, cat: catalog.Category, lang: str, text: str) -> None:
        if out.status != "ok":
            await self._deliver_failed(user, out, inp, cat, lang, text)
            return
        headline = self._headline(out, cat, lang)
        body = self._comparison(out, lang)
        tail, buttons, pending = None, [], None
        last = out.recommendation.product.title if out.recommendation else None
        if out.scope and out.others:  # ONE store was checked: the single closing question offers the rest
            tail, buttons, pending = rt.line("ask_compare", lang, others=rt.join_names(out.others, lang)), self._compare_buttons(lang), "compare_more"
            self._pending[user.id] = Pending(inp=inp, cat=cat, at=self._now(), awaiting="compare", text=text, last_pick=last)
        elif not inp.pincode:  # no place given yet: the one question is Home or PG
            office = catalog.wants_office(text)
            saved = await places.saved_places(self.p.repos, user.id, include_office=office)
            self._pending[user.id] = Pending(inp=inp, cat=cat, at=self._now(), awaiting="tap" if saved else "text", text=text, office=office, last_pick=last)
            tail, pending = w.line("place_ask_saved" if saved else "place_ask_new", lang), "place"
            if saved:
                buttons = [ReplyButton(id=BTN + d.kind, title=w.line(_BTN_KEY[d.kind], lang)) for d in saved]
        legacy = [headline, f"{body}\n\n{tail}" if tail else body]
        rinp = self._rinput(text, lang, "price_compare", self._facts(out, cat), pending=pending, buttons=[Button(id=b.id, title=b.title) for b in buttons])
        parts = await self._compose(user, rinp, legacy)
        await self._say(user, parts[0], buttons if len(parts) == 1 else None)
        await self._send_cards(user, out, lang)
        for k, part in enumerate(parts[1:], 1):
            await self._say(user, part, buttons if k == len(parts) - 1 else None)
        await self._proof(user, out, cat, lang)

    async def _deliver_failed(self, user: User, out: ShoppingOutput, inp: ShoppingInput, cat: catalog.Category, lang: str, text: str) -> None:
        scoped = bool(out.scope and out.others)
        facts = Facts(store=out.scope, category=cat.id, status_codes=[out.status], stores_offered=list(out.others), next_actions=["open_site"] if scoped else ["retry", "open_site"])
        buttons = self._compare_buttons(lang) if scoped else []
        rinp = self._rinput(text, lang, "lookup_failed", facts, pending="compare_more" if scoped else "retry", buttons=[Button(id=b.id, title=b.title) for b in buttons])
        if scoped:  # plain words + the one question "compare with the others?"
            legacy = rt.TemplateWriter().write(rinp).messages
            self._pending[user.id] = Pending(inp=inp, cat=cat, at=self._now(), awaiting="compare", text=text)
        else:
            legacy = [self._soft_fail(out, cat, lang)]
        parts = await self._compose(user, rinp, legacy)
        for k, part in enumerate(parts):
            await self._say(user, part, buttons if k == len(parts) - 1 else None)
        await self._proof(user, out, cat, lang)  # a failed attempt also says what was seen

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
        await self._proof(user, out, pend.cat, lang)
        return True

