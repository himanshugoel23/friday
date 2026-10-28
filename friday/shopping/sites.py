# ruff: noqa: E501
"""Grocery SITE agents: one specialist per site (Zepto, Blinkit, Swiggy Instamart, BigBasket, Amazon, JioMart),
each over A2A with skill ``grocery.search``, each driven by its versioned knowledge file (data, not code).

The clean port: a site agent is a thin A2A wrapper around a ``GroceryProvider``. Today every site uses
``WebGroceryProvider`` (public pages via the web lookup port). An official Zepto MCP client can later be
registered as the provider for the site ``zepto`` and nothing above it changes (see docs/ZEPTO_MCP_PLAN.md).

A site agent returns only what that site shows: items whose cited page is on the site's own domain, with the
price exactly as printed, or status ``not_visible`` ("price not visible"). It never orders and never pays.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from friday.a2a.server import AgentReply, IncomingCall
from friday.a2a.types import AgentCard, Skill, TaskState
from friday.planner.web import WebItem, WebSearchPort, WebSource

GROCERY_SKILL = "grocery.search"
SEED_DIR = Path(__file__).parent / "knowledge"
HINT = (
    "This is a grocery price check on ONE site; only use pages on that site's domains. Each item in `items` must also "
    "carry, when the page prints them: pack_text (pack size), rating (out of 5), rating_count (integer), ingredients "
    "(as printed), image_url (an image url that appears on that page), delivery_time (as printed), and put 'Out of "
    "stock' in offer if the page says so. Use null for anything the page does not show. Never invent or estimate. "
    "If the site's pages do not show prices (many quick-commerce apps hide them from the web) return no items and "
    "say so in summary."
)


# ------------------------------------------------------------------ the port (what an MCP client will implement)
class GrocerySearch(BaseModel):
    category: str  # "atta"
    products: list[str]  # popular product names to look up
    query: str = ""  # what the user typed
    pincode: str | None = None
    area: str | None = None


class GroceryResult(BaseModel):
    site: str
    status: Literal["ok", "not_visible", "failed"]
    items: list[WebItem] = Field(default_factory=list)
    sources: list[WebSource] = Field(default_factory=list)
    kb_version: int = 1
    as_of: str = ""
    note: str = ""


class GroceryProvider(Protocol):
    """One site's product search. ``WebGroceryProvider`` = public pages; a future ``ZeptoMcpProvider`` =
    the official MCP server (OAuth per user). Same input, same output, so the PM never changes."""

    site: str

    async def search(self, req: GrocerySearch) -> GroceryResult: ...


# ------------------------------------------------------------------ knowledge (data)
def load_knowledge(directory: Path = SEED_DIR) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(directory.glob("*.v*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("schema") == 1 and doc.get("site") and doc.get("domains"):
            out[doc["site"]] = doc
    return out


def _on_site(url: str | None, kb: dict[str, Any]) -> bool:
    try:
        u = urlsplit(url or "")
    except ValueError:
        return False
    if u.scheme != "https" or (u.hostname or "") not in kb["domains"]:
        return False
    return not (kb["site"] == "instamart" and "/instamart" not in u.path)


class WebGroceryProvider:
    def __init__(self, kb: dict[str, Any], provider: WebSearchPort, *, timeout_s: float = 20.0,
                 now: Callable[[], datetime] | None = None) -> None:
        self.kb, self.site, self.provider, self.timeout_s = kb, kb["site"], provider, timeout_s
        self._now = now or (lambda: datetime.now(UTC))

    def query(self, req: GrocerySearch) -> str:
        where = f"pincode {req.pincode}" if req.pincode else (req.area or "India")
        tpl = self.kb["search_query_templates"][0]
        return tpl.format(products="; ".join(req.products), category=req.category, site=self.site, location=where)

    async def search(self, req: GrocerySearch) -> GroceryResult:
        base = {"site": self.site, "kb_version": int(self.kb["version"]), "as_of": self._now().isoformat(timespec="minutes")}
        domains = ", ".join(self.kb["domains"])
        try:
            raw = await self.provider.search(self.query(req), timeout_s=self.timeout_s, hint=f"{HINT} Domains: {domains}.")
        except Exception as e:  # noqa: BLE001
            return GroceryResult(status="failed", note=type(e).__name__, **base)
        sources = [s for s in raw.sources if _on_site(s.url, self.kb)]
        items = [i for i in raw.items if _on_site(i.url, self.kb)]  # the cited page must be on THIS site
        if not sources or not items or not any(i.price_inr is not None or i.price_text for i in items):
            return GroceryResult(status="not_visible", sources=sources[:3], note="price not visible", **base)
        return GroceryResult(status="ok", items=items[:6], sources=sources[:4], **base)


class GrocerySiteAgent:
    """A2A handler for one site. The provider is swappable; the card carries the knowledge version."""

    def __init__(self, kb: dict[str, Any], provider: GroceryProvider, *, cost_per_search_inr: float = 1.0) -> None:
        self.kb, self.provider, self.cost = kb, provider, cost_per_search_inr
        self.name = kb["site"]

    def card(self, url: str | None = None) -> AgentCard:
        return AgentCard(
            name=self.name, url=url or f"inproc://{self.name}", version=str(self.kb["version"]),
            description=f"Knows the {self.kb['display']} website (knowledge v{self.kb['version']}, {self.kb['status']}). Returns only what the site shows, else 'price not visible'. Never orders, never pays.",
            skills=[Skill(id=GROCERY_SKILL, name=f"{self.kb['display']} grocery search", description="category + popular products (+ pincode) -> items with sources",
                          tags=["grocery", self.name, self.kb.get("role", "core")], examples=["atta 5 kg price near 560034"])],
        )

    async def handle(self, call: IncomingCall) -> AgentReply:
        try:
            req = GrocerySearch.model_validate(call.data)
        except Exception:  # noqa: BLE001
            return AgentReply(TaskState.INPUT_REQUIRED, "what_category")
        res = await self.provider.search(req)
        if res.status == "failed":
            return AgentReply(TaskState.FAILED, f"lookup_failed:{res.note}"[:60], res.model_dump(mode="json"), cost_inr=self.cost)
        return AgentReply(TaskState.COMPLETED, "", res.model_dump(mode="json"), cost_inr=self.cost)

