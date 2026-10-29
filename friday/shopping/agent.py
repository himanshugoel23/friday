# ruff: noqa: E501
"""SHOPPING agent. One job: for a product category, ask the grocery site agents (through the shopping PM, over
A2A, in parallel) for the popular products, merge their answers into ONE comparison per kg/L and pick ONE.

Never invents a number: a price, rating or ingredient is kept only for an item whose page the provider cited
on that site's own domain. Never hangs: one hard deadline. Images come only from cited pages (images.py).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from friday.a2a.audit import A2AAudit
from friday.core.logging import get_logger
from friday.planner.web import WebItem, WebSearchPort
from friday.shopping import catalog
from friday.shopping.compare import (
    Product,
    ShoppingInput,
    ShoppingOutput,
    SiteStatus,
    build_product,
    merge_offers,
    recommend,
)
from friday.shopping.images import ImagePort, NoImages, public_https
from friday.shopping.pm import OnSite, ShoppingPM
from friday.shopping.sites import GroceryProvider, GrocerySearch, WebGroceryProvider, load_knowledge

log = get_logger(__name__)


class ShoppingAgent:
    def __init__(
        self,
        provider: WebSearchPort,
        *,
        images: ImagePort | None = None,
        overrides: dict[str, GroceryProvider] | None = None,
        knowledge: dict[str, dict] | None = None,
        timeout_s: float = 25.0,
        cache_ttl_s: float = 300.0,
        cost_per_search_inr: float = 1.0,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        audit: A2AAudit | None = None,
    ) -> None:
        self.images = images or NoImages()
        self.timeout_s, self.cache_ttl_s = timeout_s, cache_ttl_s
        self._now = now or (lambda: datetime.now(UTC))
        self._mono = monotonic
        self.kb = knowledge or load_knowledge()
        providers: dict[str, GroceryProvider] = {
            s: WebGroceryProvider(kb, provider, timeout_s=min(20.0, timeout_s), now=self._now) for s, kb in self.kb.items()
        }
        providers.update(overrides or {})  # e.g. {"zepto": ZeptoMcpProvider(...)} later
        self.pm = ShoppingPM(self.kb, providers, audit=audit, cost_per_search_inr=cost_per_search_inr, timeout_s=timeout_s)
        self._cache: dict[tuple[str, str, str, str, str], tuple[float, ShoppingOutput]] = {}

    def scope_site(self, retailer: str | None) -> str | None:
        """The grocery site key for a store the user named, or None (unknown store: compare everything)."""
        return self._site_of(retailer)

    def site_names(self) -> list[str]:
        order = ("zepto", "blinkit", "instamart", "bigbasket")
        core = [s for s in self.kb if self.kb[s].get("role", "core") == "core"]
        return [self.pm.display(s) for s in sorted(core, key=lambda s: (order.index(s) if s in order else 99, s))]

    async def run(self, inp: ShoppingInput, *, on_site: OnSite | None = None) -> ShoppingOutput:
        cat = catalog.categories()[inp.category_id]
        only = self._site_of(inp.retailer) if inp.scoped else None
        key = (cat.id, (inp.retailer or "").lower(), inp.pincode or "", (inp.area or "").lower(), inp.lang + ("|only" if only else ""))
        hit = self._cache.get(key)
        if hit and self._mono() - hit[0] < self.cache_ttl_s:
            return hit[1].model_copy(update={"from_cache": True})
        req = GrocerySearch(category=cat.id, products=cat.popular, query=inp.query, pincode=inp.pincode, area=inp.area, user_id=inp.user_id)
        base = {"category_id": cat.id, "retailer": inp.retailer, "as_of": self._now(), "unit": cat.unit}
        if only:
            base["scope"] = self.pm.display(only)
            base["others"] = [n.replace("Swiggy ", "") for n in self.site_names() if n != base["scope"]]  # "Instamart", as people say it
        try:
            results = await asyncio.wait_for(self.pm.run(req, on_site=on_site, only=only), self.timeout_s + 2)
        except TimeoutError:
            return ShoppingOutput(status="timeout", **base)  # type: ignore[arg-type]
        out = await self._merge(inp, cat, results, base)
        if out.status == "ok":
            self._cache[key] = (self._mono(), out)
            if len(self._cache) > 100:
                self._cache.pop(next(iter(self._cache)))
        return out

    async def _merge(self, inp: ShoppingInput, cat: catalog.Category, results: dict, base: dict) -> ShoppingOutput:
        order = ("zepto", "blinkit", "instamart", "bigbasket", "amazon", "jiomart")
        ranked = sorted(results.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0]))
        sites = [SiteStatus(site=s, display=self.pm.display(s), status=st) for s, (_, st) in ranked]
        rows: list[tuple[str, WebItem, Product]] = []
        sources, cited = [], set()
        for site, (res, _) in sorted(results.items()):
            if res is None:
                continue
            for src in res.sources:
                if src.url not in cited:
                    cited.add(src.url)
                    sources.append(src)
            for item in res.items:
                if item.title.strip():
                    rows.append((self.pm.display(site), item, build_product(item, cat)))
        retailer_site = self._site_of(inp.retailer)
        hidden = bool(
            retailer_site
            and not any(r[0] == self.pm.display(retailer_site) and r[2].price_inr is not None for r in rows)
        )
        if not rows:
            failed = bool(sites) and all(s.status in ("failed", "skipped") for s in sites)
            return ShoppingOutput(status="unavailable" if failed else "no_result", sites=sites,
                                  retailer_price_hidden=hidden, **base)  # type: ignore[arg-type]
        products = merge_offers(rows)
        items_by_url = {i.url: i for _, i, _ in rows if i.url}
        await self._attach_images(products, items_by_url, cited)
        return ShoppingOutput(
            status="ok", products=products, recommendation=recommend(products, cat, inp.lang), sources=sources[:6],
            retailer_price_hidden=hidden, sites=sites, **base,
        )  # type: ignore[arg-type]

    def _site_of(self, retailer: str | None) -> str | None:
        r = (retailer or "").lower().strip()
        if not r:
            return None
        for s, kb in self.kb.items():
            if r == s or r in str(kb["display"]).lower() or s in r:
                return s
        return None

    async def _attach_images(self, products: list[Product], items: dict[str, WebItem], cited: set[str]) -> None:
        async def one(p: Product) -> None:
            for offer in p.offers:  # cheapest offer first
                direct = getattr(items.get(offer.url or ""), "image_url", None)
                if direct and direct in cited and public_https(direct):
                    p.image_url = direct  # the provider cited this very image
                    return
                if offer.url and offer.url in cited:
                    try:
                        img = await asyncio.wait_for(self.images.image_for(offer.url), 5.0)
                    except Exception:  # noqa: BLE001 - fail soft to a text card
                        img = None
                    if public_https(img):
                        p.image_url = img
                        return

        await asyncio.gather(*(one(p) for p in products))
