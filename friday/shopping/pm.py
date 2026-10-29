# ruff: noqa: E501
"""The shopping PM. It only MANAGES: it activates the grocery site agents IN PARALLEL over A2A (skill
``grocery.search``), checks each result, and hands the merge to ``compare``. It never searches or reads a page.

Wave 1 = the core sites (Zepto, Blinkit, Swiggy Instamart, BigBasket) at once. Wave 2 = the extras (Amazon,
JioMart) only when fewer than two core sites could show prices, to keep cost and time down. One budget
(steps, seconds, cost) covers the whole task; running out stops dispatching and the PM answers with what it has.
A site that fails or hides its prices is reported as such, never filled in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import BudgetExceeded, TaskBudget
from friday.a2a.client import A2AClient
from friday.a2a.server import A2AServer
from friday.a2a.transport import InProcessTransport
from friday.a2a.types import Task, TaskState
from friday.core.logging import get_logger
from friday.shopping.sites import (
    GROCERY_SKILL,
    GroceryProvider,
    GroceryResult,
    GrocerySearch,
    GrocerySiteAgent,
)

log = get_logger(__name__)
OnSite = Callable[[str, str], Awaitable[None] | None]


class ShoppingPM:
    def __init__(self, knowledge: dict[str, dict[str, Any]], providers: dict[str, GroceryProvider], *,
                 audit: A2AAudit | None = None, cost_per_search_inr: float = 1.0, timeout_s: float = 25.0,
                 max_cost_inr: float = 10.0) -> None:
        self.kb = knowledge
        servers = {s: A2AServer(a.card(), a) for s, a in
                   ((s, GrocerySiteAgent(knowledge[s], p, cost_per_search_inr=cost_per_search_inr)) for s, p in providers.items() if s in knowledge)}
        self.transport = InProcessTransport(servers)
        self.client = A2AClient(self.transport, name="shopping_pm", audit=audit or A2AAudit(), per_call_timeout_s=timeout_s)
        self.timeout_s, self.max_cost_inr = timeout_s, max_cost_inr

    def display(self, site: str) -> str:
        return str(self.kb.get(site, {}).get("display", site.title()))

    def _budget(self) -> TaskBudget:
        return TaskBudget(max_steps=len(self.kb) + 2, max_seconds=self.timeout_s, max_cost_inr=self.max_cost_inr)

    async def _ask(self, site: str, req: GrocerySearch, budget: TaskBudget, root: str, on_site: OnSite | None) -> tuple[str, GroceryResult | None, str]:
        try:
            t: Task = await self.client.delegate(site, data=req.model_dump(mode="json"), root_task_id=root, budget=budget)
        except BudgetExceeded:
            return site, None, "skipped"
        data = t.result_data()
        res: GroceryResult | None = None
        status = "failed"
        if t.state == TaskState.COMPLETED and data:
            try:
                res = GroceryResult.model_validate(data)
                status = res.status
            except Exception:  # noqa: BLE001
                res, status = None, "failed"
        if on_site is not None:
            r = on_site(site, status)
            if hasattr(r, "__await__"):
                await r  # type: ignore[misc]
        return site, res, status

    async def run(self, req: GrocerySearch, *, on_site: OnSite | None = None, only: str | None = None) -> dict[str, tuple[GroceryResult | None, str]]:
        """site -> (result or None, status ok | not_visible | failed | skipped). Never raises for agent trouble.
        ``only``: the user named ONE store, so only that site is asked (the rest are offered afterwards)."""
        budget = self._budget()
        root = f"shop-{id(req):x}"
        avail = set(await self.client.agents_with_skill(GROCERY_SKILL))
        if only is not None and only in avail:
            avail = {only}
        core = sorted(s for s in avail if self.kb[s].get("role", "core") == "core")
        extra = sorted(s for s in avail if self.kb[s].get("role") == "extra")
        out: dict[str, tuple[GroceryResult | None, str]] = {}
        for wave in (core, extra):
            if wave is extra and sum(1 for _, st in out.values() if st == "ok") >= 2:
                break
            if not wave:
                continue
            for site, res, status in await asyncio.gather(*(self._ask(s, req, budget, root, on_site) for s in wave)):
                out[site] = (res, status)
        for s in sorted(avail - set(out)):
            out[s] = (None, "skipped")
        log.info("shopping pm: %s", {s: st for s, (_, st) in out.items()})  # statuses only: no query text
        return out
