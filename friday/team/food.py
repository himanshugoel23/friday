# ruff: noqa: E501
"""Food-ordering request parsing and the SITE AGENTS (Zomato, Swiggy) as A2A handlers.

A site agent knows ONE website, completely, from its versioned knowledge file (data, not code). It searches
through the WEB_LOOKUP port (OpenAI Responses web_search) and returns options with sources and deep links.
It NEVER orders and NEVER pays: the user opens the link and pays in their own app (orders stay behind the
browser connector and its stop-at-payment rule).

Grounding rules enforced here in code: an option must carry a URL the provider actually cited on the site's own
domain; a price is shown only if the provider returned one (a price that disagrees with its printed text is
dropped); a price cap filters only options whose price is known; nothing is invented.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

from friday.a2a.server import AgentReply, IncomingCall
from friday.a2a.types import AgentCard, Skill, TaskState
from friday.planner.web import WebItem, WebSearchPort
from friday.team.knowledge import KnowledgeStore

FOOD_SKILL = "food.search"
SITES = ("zomato", "swiggy")
_I = re.IGNORECASE
CAP_RE = re.compile(
    r"(?:\b(?:under|below|within|upto|up\s*to|less\s+than|max(?:imum)?|budget(?:\s+of)?)\b|<=?)\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*)"
    r"|(?:rs\.?|inr|₹)\s*(\d[\d,]*)\s*(?:ke\s+andar|tak|se\s+kam)"
    r"|(\d[\d,]*)\s*(?:rs|rupees?|₹)?\s*(?:ke\s+andar|tak|se\s+kam)", _I)
NEAR_ME = re.compile(r"\b(?:near\s*me|nearby|near\s+by|around\s+me|mere\s+paas|aas\s*paas|paas\s+mein)\b", _I)
AREA_LEAD = re.compile(r"\b(?:near|in|at|around|ke\s+paas)\s+", _I)
AREA_STOP = frozenset({
    "me", "my", "here", "home", "under", "below", "within", "upto", "up", "less", "max", "budget", "on", "for", "with", "and", "or",
    "zomato", "swiggy", "rs", "inr", "please", "plz", "se", "tak", "ke", "ka", "ki", "the", "a", "order", "delivery", "now", "today", "tonight",
})  # fmt: skip
SITE_RE = re.compile(r"\b(zomato|swiggy)\b", _I)
DISH_WORDS = (
    "butter chicken", "chicken", "paneer", "biryani", "dosa", "pizza", "burger", "momos", "thali", "naan", "roti", "dal",
    "chole", "rolls", "roll", "noodles", "pasta", "sandwich", "ice cream", "cake", "chai", "coffee", "kebab", "tikka",
    "shawarma", "idli", "vada", "samosa", "paratha", "fried rice", "manchurian", "pav bhaji", "chaat", "dessert", "lassi",
)  # fmt: skip
DISH_RE = re.compile(r"\b(" + "|".join(re.escape(d) for d in DISH_WORDS) + r")\b", _I)
FOOD_CONTEXT = re.compile(
    r"\b(zomato|swiggy|restaurants?|dhaba|cafe|order|delivery|deliver|near\s*me|nearby|menu|khana|food|eat|eating|hungry|options|under|below|ke\s+andar)\b",
    _I)
_STRIP = re.compile(
    r"\b(please|plz|find|show|get|give|search|look\s*for|order|want|need|chahiye|dikhao|batao|me|for\s+me|mujhe|best|good|top|cheap|"
    r"options?|restaurants?|on|from|at|in|near|nearby|the|a|some|any|food|zomato|swiggy|delivery|deliver|and)\b", _I)


@dataclass
class FoodRequest:
    dish: str
    area: str | None
    max_price_inr: int | None
    site: str | None

    def data(self) -> dict[str, Any]:
        return {"dish": self.dish, "area": self.area, "max_price_inr": self.max_price_inr}


def is_food_clause(text: str) -> bool:
    """A dish (or a food app) AND a food-search context. 'order pizza' counts; plain 'pizza' does not."""
    return bool((DISH_RE.search(text) or SITE_RE.search(text)) and FOOD_CONTEXT.search(text))


def _area_after(text: str) -> str | None:
    for m in AREA_LEAD.finditer(text):
        words: list[str] = []
        for w in text[m.end():].split():
            w = w.strip(",.;:!?")
            if not w or w.lower() in AREA_STOP or w[0].isdigit() or w.startswith(("₹", "<")):
                break
            words.append(w)
            if len(words) == 3:
                break
        if words:
            return " ".join(words)
    return None


def parse_food(text: str, default_area: str | None = None) -> FoodRequest:
    cap = None
    m = CAP_RE.search(text)
    if m:
        raw = next(g for g in m.groups() if g)
        cap = int(raw.replace(",", ""))
    site_m = SITE_RE.search(text)
    area = None
    if not NEAR_ME.search(text):
        area = _area_after(text)
    if area is None and (NEAR_ME.search(text) or default_area):
        area = default_area
    dish_src = CAP_RE.sub(" ", text)
    dish_src = NEAR_ME.sub(" ", dish_src)
    if area:
        dish_src = re.sub(re.escape(area), " ", dish_src, flags=_I)
    dm = DISH_RE.findall(dish_src)
    dish = " ".join(_STRIP.sub(" ", dish_src).split()).strip(" ,.-")
    if not dish and dm:
        dish = dm[0]
    return FoodRequest(dish=dish[:60], area=area, max_price_inr=cap, site=site_m.group(1).lower() if site_m else None)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _price_consistent(item: WebItem) -> float | None:
    """price_inr is kept only if the printed price_text (when there is one) shows the same number."""
    if item.price_inr is None:
        return None
    if item.price_text:
        nums = [float(n.replace(",", "")) for n in _NUM.findall(item.price_text)]
        if not nums or all(abs(n - item.price_inr) > 0.5 for n in nums):
            return None
    return float(item.price_inr)


def _on_domain(url: str | None, domains: list[str]) -> bool:
    try:
        return bool(url) and (urlsplit(url or "").hostname or "") in domains
    except ValueError:
        return False


HINT = (
    "This is a food search on ONE site. For each item return title (restaurant or dish), price_text exactly as printed, "
    "price_inr only if printed, store, url (a page on that site), and when printed: rating, delivery_time, offer. "
    "Only values printed on the page. Never invent."
)


class SiteAgent:
    """One site, one knowledge file. A2A skill ``food.search``."""

    def __init__(self, site: str, store: KnowledgeStore, provider: WebSearchPort, *, timeout_s: float = 20.0,
                 cost_per_search_inr: float = 1.0, now: Callable[[], datetime] | None = None) -> None:
        self.site, self.store, self.provider = site, store, provider
        self.timeout_s, self.cost, self._now = timeout_s, cost_per_search_inr, now or (lambda: datetime.now(UTC))

    def card(self, url: str | None = None) -> AgentCard:
        kb = self.store.get(self.site)
        return AgentCard(
            name=self.site, url=url or f"inproc://{self.site}", version=str(kb["version"]),
            description=f"Knows the {self.site.title()} website (knowledge v{kb['version']}, {kb['status']}). Finds restaurant options with sources and links. Never orders, never pays.",
            skills=[Skill(id=FOOD_SKILL, name=f"{self.site.title()} food search", description="dish + area (+ price cap) -> options with sources and deep links",
                          tags=["food", self.site], examples=["butter chicken near Sonipat under 400"])],
        )

    def deep_link(self, kb: dict[str, Any], req: dict[str, Any]) -> tuple[str, str]:
        pats = kb["url_patterns"]
        slug = re.sub(r"[^a-z0-9]+", "-", (req.get("area") or "").lower()).strip("-")
        if "search" in pats:
            return pats["search"].replace("{query}", quote(req.get("dish") or "")), "search"
        if slug and "city_delivery" in pats:
            return pats["city_delivery"].replace("{city_slug}", slug), "city"
        return pats["home"], "home"

    async def handle(self, call: IncomingCall) -> AgentReply:
        req = {**call.data}
        if not req.get("dish") and call.text:
            p = parse_food(call.text, req.get("area"))
            req = {"dish": p.dish, "area": p.area, "max_price_inr": p.max_price_inr}
        # a follow-up on an input-required task: the text is the missing area
        if not req.get("area") and len(call.history) > 1 and call.text:
            req["area"] = call.text.strip()[:40]
            first = next((m.data() for m in call.history if m.data()), {})
            req = {**first, **{k: v for k, v in req.items() if v}}
        if not req.get("dish"):
            return AgentReply(TaskState.INPUT_REQUIRED, "what_dish")
        if not req.get("area"):
            return AgentReply(TaskState.INPUT_REQUIRED, "which_area")
        kb = self.store.get(self.site)
        domains = list(kb["domains"])
        templates = kb["search_query_templates"]
        query = templates[0].format(dish=req["dish"], area=req["area"])
        try:
            raw = await self.provider.search(query, timeout_s=self.timeout_s, hint=HINT)
        except Exception as e:  # noqa: BLE001
            return AgentReply(TaskState.FAILED, f"lookup_failed:{type(e).__name__}", cost_inr=self.cost)
        sources = [{"url": s.url, "title": s.title} for s in raw.sources if _on_domain(s.url, domains)]
        link, link_kind = self.deep_link(kb, req)
        base: dict[str, Any] = {"site": self.site, "kb_version": kb["version"], "kb_status": kb["status"],
                                "as_of": self._now().isoformat(timespec="minutes"), "search_link": link,
                                "search_link_kind": link_kind, "query": req["dish"], "area": req["area"],
                                "max_price_inr": req.get("max_price_inr")}
        cap = req.get("max_price_inr")
        priced, unpriced, over = [], [], 0
        for it in raw.items:
            if not _on_domain(it.url, domains):
                continue  # no cited page on the site's own domain: not an option
            price = _price_consistent(it)
            opt = {"name": it.title, "price_text": it.price_text if price is not None or it.price_text else None,
                   "price_inr": price, "rating": it.rating, "delivery_time": it.delivery_time, "offer": it.offer,
                   "url": it.url, "deep_link": it.url}
            if price is None:
                unpriced.append(opt)
            elif cap is not None and price > cap:
                over += 1
            else:
                priced.append(opt)
        options = (sorted(priced, key=lambda o: o["price_inr"]) + unpriced)[:4]
        status = "ok" if options and sources else "no_result"
        return AgentReply(TaskState.COMPLETED, "", {**base, "status": status, "options": options, "sources": sources[:4],
                                                    "over_cap": over, "summary": raw.summary[:300]}, cost_inr=self.cost)
