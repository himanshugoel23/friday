# ruff: noqa: E501
"""Swiggy food adapter (``swiggy.food``): ``FoodAdapter`` reused (search, menu, sold-out check, cart,
price re-check, address check, armed checkout click, QR / UPI hand-off), with Swiggy's own allow-list
and connector, a mandatory delivery address, and unticking of pre-selected extras.
"""

from __future__ import annotations

from typing import Any

from friday.connectors.contract import format_rupees
from friday.connectors.sites.adapters import (
    APPROVAL_TTL,
    ExecResult,
    FoodAdapter,
    Prepared,
    Problem,
    Proposal,
    RunCtx,
)
from friday.connectors.sites.safety import ExtendedGate
from friday.connectors.sites.swiggy.connector import SwiggyConnector, make_kit
from friday.connectors.sites.train.common import AddOnStuck


class SwiggyFoodAdapter(FoodAdapter):
    key = "swiggy.food"
    site, use_case, site_name = "swiggy", "food", "Swiggy"
    required = ("items", "restaurant")

    def __init__(self, ctx: RunCtx, credentials: Any = None) -> None:  # noqa: ARG002 - no password login on Swiggy
        self.ctx, self.gate = ctx, ExtendedGate(now=ctx.now)
        self.pending: dict[str, Any] | None = None
        self.kit = make_kit(ctx.session, task_id=ctx.task_id, repairer=ctx.repairer)
        kw: dict[str, Any] = dict(base_url=ctx.base_url, task_id=ctx.task_id, otp_channel=ctx.otp,
                                  phone=ctx.profile.phone or None, on_code_wait=ctx.on_code_wait,
                                  otp_wait_s=ctx.otp_wait_s, poll_s=ctx.poll_s)
        if ctx.sleep:
            kw["sleep"] = ctx.sleep
        self.conn = SwiggyConnector(self.kit.session, **kw)

    def missing(self, slots: dict[str, Any]) -> str | None:
        for s in self.required:
            if not slots.get(s):
                return s
        return None if (slots.get("address") or self.ctx.profile.address) else "address"

    async def prepare(self, slots: dict[str, Any]) -> Prepared:
        if not (slots.get("address") or self.ctx.profile.address):  # never deliver to a default
            self.pending = {"slot": "address", "kind": "need_detail", "text_key": "q_address", "options": []}
            return Prepared(problem=Problem("need_detail", "delivery address"))  # type: ignore[arg-type]
        return await super().prepare(slots)

    async def execute(self, p: Proposal) -> ExecResult:
        self.conn.unticked.clear()
        try:
            res = await super().execute(p)
        except AddOnStuck as e:  # an extra stayed ticked: show the real total and ask again
            cart = e.quote
            new = p.model_copy(update={
                "lines": [f"{ln.qty} x {ln.name} ({format_rupees(ln.line_total_paise)})" for ln in cart.lines]
                         + [f"Extra on the site: {x}" for x in e.names],
                "subtotal_paise": cart.subtotal_paise, "max_total_paise": cart.grand_total_paise, "exact": True,
                "expires_at": self.ctx.now() + APPROVAL_TTL})
            return ExecResult("reapprove", reason="an extra (" + ", ".join(e.names) + ") could not be removed and is in the total",
                              proposal=new, notes={**self.flags(), "addon_stuck": True})
        if self.conn.unticked:
            res.notes["addon_unticked"] = True
        return res


ADAPTERS = {"swiggy.food": SwiggyFoodAdapter}
__all__ = ["ADAPTERS", "SwiggyFoodAdapter"]
