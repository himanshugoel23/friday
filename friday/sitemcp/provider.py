# ruff: noqa: E501
"""GroceryProvider implementations backed by the site MCP hub, plugged into the shopping PM through the existing port
(friday/shopping/sites.py). The comparison / recommendation flow above is unchanged.

``BrowserMcpGroceryProvider``: set_location + search_products per popular product, anonymous (no login). Any block, challenge,
robots refusal, 'location not found' or trouble makes a non-ok result; ``FallbackGroceryProvider`` then asks the web search
provider instead, so a blocked site is never an error and never a retry loop.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from friday.core.logging import get_logger
from friday.planner.web import WebItem, WebSource
from friday.shopping.sites import GroceryProvider, GroceryResult, GrocerySearch, _on_site
from friday.sitemcp.hub import SiteMcpHub

log = get_logger(__name__)
MAX_PRODUCTS = 3  # polite: at most this many searches per site per comparison


class BrowserMcpGroceryProvider:
    def __init__(self, hub: SiteMcpHub, shopping_kb: dict[str, Any], *, allow_http: bool = False, max_products: int = MAX_PRODUCTS,
                 now: Callable[[], datetime] | None = None) -> None:
        self.hub, self.kb, self.site = hub, shopping_kb, shopping_kb["site"]
        self.allow_http, self.max_products = allow_http, max_products
        self._now = now or (lambda: datetime.now(UTC))

    def _res(self, status: str, note: str = "", items: list[WebItem] | None = None, sources: list[WebSource] | None = None) -> GroceryResult:
        return GroceryResult(site=self.site, status=status, items=items or [], sources=sources or [],  # type: ignore[arg-type]
                             kb_version=int(self.kb["version"]), as_of=self._now().isoformat(timespec="minutes"), note=note)

    def _url_ok(self, url: str | None) -> bool:
        if self.allow_http:
            return bool(url)
        return _on_site(url, self.kb)

    async def search(self, req: GrocerySearch) -> GroceryResult:
        place = req.pincode or req.area
        if not place:
            return self._res("not_visible", "no_location")  # prices need a delivery place; the PM asks the user for one
        user = req.user_id or f"guest-{req.pincode or 'area'}"
        loc_args = {"pincode": req.pincode} if req.pincode else {"place": (req.area or "")[:80]}
        loc = await self.hub.call(self.site, "set_location", loc_args, user_id=user)
        bad = self._bad(loc)
        if bad:
            return bad
        items: list[WebItem] = []
        sources: list[WebSource] = []
        seen: set[str] = set()
        for q in (req.products or [req.query or req.category])[: self.max_products]:
            r = await self.hub.call(self.site, "search_products", {"query": q[:80]}, user_id=user)
            bad = self._bad(r)
            if bad:
                if items:
                    break  # keep what we already read
                return bad
            for it in r.get("items", []):
                if it["id"] in seen or not self._url_ok(it.get("url")):
                    continue
                seen.add(it["id"])
                items.append(WebItem(title=it["title"], price_text=it["price_text"] or None, price_inr=it["price_inr"], store=self.kb["display"],
                                     url=it["url"], pack_text=it["pack"] or None, rating=it["rating"] or None,
                                     offer="Out of stock" if it["out_of_stock"] else None))
            if r.get("as_of_url") and self._url_ok(r["as_of_url"]):
                sources.append(WebSource(url=r["as_of_url"], title=f"{self.kb['display']} search: {q}"[:80]))
        if not any(i.price_inr is not None for i in items):
            return self._res("not_visible", "price not visible", sources=sources[:3])
        return self._res("ok", items=items[:6], sources=sources[:4])

    def _bad(self, r: dict[str, Any]) -> GroceryResult | None:
        st = r.get("status")
        if st == "ok":
            return None
        if st == "location_not_found":
            return self._res("not_visible", "location_not_found")
        # blocked / busy / rate_limited / unavailable / error / needs_*: failed -> the web provider takes over
        log.info("site mcp not ok", extra={"site": self.site, "status": st, "reason": r.get("reason", "")})
        return self._res("failed", f"browser:{st}:{r.get('reason', '')}"[:60])


class FallbackGroceryProvider:
    """Browser first; when it is not ok (blocked, busy, no location, changed page ...) use the web search provider."""

    def __init__(self, primary: GroceryProvider, fallback: GroceryProvider) -> None:
        self.primary, self.fallback, self.site = primary, fallback, primary.site

    async def search(self, req: GrocerySearch) -> GroceryResult:
        try:
            res = await self.primary.search(req)
        except Exception as e:  # noqa: BLE001
            res = GroceryResult(site=self.site, status="failed", note=f"browser:{type(e).__name__}")
        if res.status == "ok":
            return res
        alt = await self.fallback.search(req)
        if alt.status != "ok":
            alt = alt.model_copy(update={"note": (alt.note + f" (browser: {res.note})").strip()[:120]})
        return alt
