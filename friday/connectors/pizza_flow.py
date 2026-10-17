"""The first use case end to end: "order a Domino's pizza" up to (never including) payment.

search -> choose restaurant -> menu -> pick items -> ASK (gate) -> user's Grant -> build_cart ->
gate -> payment handoff. Returns a structured, scrubbed-safe ``FlowResult``. If the connector is
killed, degraded or only a link exists, the result is "finish in the app" with a deep link.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from friday.connectors.contract import (
    Cart,
    CartMismatch,
    DeepLinkResult,
    ItemQty,
    LayoutChanged,
    LoginFailed,
    LoginRequired,
    PaymentHandoff,
    Restaurant,
    TotalsMismatch,
)
from friday.connectors.gate import ActionGate, Grant, Verdict
from friday.connectors.recorder import StepRecorder, TracedConnector
from friday.connectors.registry import BackendKind, ConnectorRegistry, Status
from friday.connectors.scrub import scrub

FlowStatus = Literal[
    "payment_ready", "needs_approval", "denied", "finish_in_app", "no_restaurant",
    "item_not_found", "login_required", "error",
]


@dataclass
class WantedItem:
    query: str  # matched against menu item names, e.g. "margherita"
    qty: int = 1


class Proposal(BaseModel):
    """What the user is asked to approve (shown as WhatsApp buttons in the real product)."""

    task_id: str
    connector: str
    restaurant_id: str
    restaurant_name: str
    items: list[ItemQty]
    estimated_subtotal_paise: int


class FlowResult(BaseModel):
    status: FlowStatus
    message: str
    restaurant: Restaurant | None = None
    items: list[ItemQty] = []
    cart: Cart | None = None
    handoff: PaymentHandoff | None = None
    deep_link: DeepLinkResult | None = None


Approver = Callable[[Proposal], Awaitable[Grant | None]]
Chooser = Callable[[list[Restaurant]], Restaurant | None]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def default_chooser(results: list[Restaurant]) -> Restaurant | None:
    """First hit whose name contains 'domino' (kept simple on purpose)."""
    return next((r for r in results if "domino" in _norm(r.name)), None)


def _args(task_id: str, connector: str, rid: str, items: list[ItemQty], **extra: int) -> dict:
    return {"task_id": task_id, "connector": connector, "restaurant_id": rid,
            "items": [i.model_dump() for i in items], **extra}


async def run_pizza_flow(
    registry: ConnectorRegistry,
    gate: ActionGate,
    *,
    task_id: str,
    area: str,
    wanted: list[WantedItem],
    approve: Approver,
    query: str = "Domino's",
    site: str = "zomato",
    use_case: str = "food",
    choose: Chooser = default_chooser,
    recorder: StepRecorder | None = None,
) -> FlowResult:
    result = await _run(registry, gate, task_id, area, wanted, approve, query, site, use_case,
                        choose, recorder)
    if recorder is not None:
        recorder.finish(scrub(result.model_dump()))
    return result


async def _run(registry, gate, task_id, area, wanted, approve, query, site, use_case,  # noqa: ANN001
               choose, recorder) -> FlowResult:
    key = f"{site}.{use_case}"

    def in_app(why: str) -> FlowResult:
        url = registry.fallback_url(site, use_case) or ""
        return FlowResult(status="finish_in_app", message=why,
                          deep_link=DeepLinkResult(
                              url=url, message=f"Finish this in the app: {why}"))

    sel = registry.select(site, use_case, fulfils=True)
    if sel is None:
        return in_app("this connector is switched off or not working right now")
    if sel.connector is None or sel.backend == BackendKind.deep_link:
        return in_app("only a link is available for this site")
    conn = TracedConnector(sel.connector, recorder) if recorder else sel.connector

    try:
        if gate.decide("search_restaurants", {"task_id": task_id, "connector": key}, []) \
                != Verdict.allow:
            return FlowResult(status="denied", message="search was not allowed")
        results = await conn.search_restaurants(query, area)
        chosen = choose(results)
        if chosen is None:
            return FlowResult(status="no_restaurant", message=f"No match for {query}")
        menu = await conn.get_menu(chosen.restaurant_id)

        items: list[ItemQty] = []
        subtotal = 0
        for w in wanted:
            hit = next((m for m in menu.items if _norm(w.query) in _norm(m.name)), None)
            if hit is None:
                return FlowResult(status="item_not_found", restaurant=chosen,
                                  message=f"'{w.query}' is not on the menu")
            items.append(ItemQty(item_id=hit.item_id, qty=w.qty))
            subtotal += hit.price_paise * w.qty

        args = _args(task_id, key, chosen.restaurant_id, items)
        verdict, reason = gate.explain("build_cart", args, [])
        if verdict == Verdict.deny:
            return FlowResult(status="denied", restaurant=chosen, items=items, message=reason)
        grant = await approve(Proposal(
            task_id=task_id, connector=key, restaurant_id=chosen.restaurant_id,
            restaurant_name=chosen.name, items=items, estimated_subtotal_paise=subtotal))
        if grant is None:
            return FlowResult(status="needs_approval", restaurant=chosen, items=items,
                              message="Waiting for your OK before I add anything to a cart")
        verdict, reason = gate.explain("build_cart", args, [grant])
        if verdict != Verdict.allow:
            return FlowResult(status="denied", restaurant=chosen, items=items, message=reason)

        cart = await conn.build_cart(chosen.restaurant_id, items)
        grant.mark_used("build_cart")

        pay_args = _args(task_id, key, chosen.restaurant_id, cart.items(),
                         total_paise=cart.grand_total_paise)
        verdict, reason = gate.explain("get_payment_handoff", pay_args, [grant])
        if verdict != Verdict.allow:
            return FlowResult(status="denied", restaurant=chosen, items=items, cart=cart,
                              message=reason)
        handoff = await conn.get_payment_handoff(cart)
        grant.mark_used("get_payment_handoff")
        return FlowResult(status="payment_ready", restaurant=chosen, items=items, cart=cart,
                          handoff=handoff, message="Cart is ready. Pay in your own UPI app.")
    except LayoutChanged:
        registry.set_status(site, use_case, sel.backend, Status.degraded)
        return in_app("the site changed and I can't read it reliably")
    except (LoginRequired, LoginFailed):
        return FlowResult(status="login_required", message="I need you to log in to continue")
    except (TotalsMismatch, CartMismatch) as e:
        return FlowResult(status="error", message=f"Stopped: {e}")


__all__ = ["FlowResult", "Proposal", "WantedItem", "run_pizza_flow", "default_chooser"]
