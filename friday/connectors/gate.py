"""ActionGate: one deterministic allow / deny / ask decision in front of every connector tool.

Read tools are allowed. State-changing tools need a ``Grant`` the USER approved, scoped to one
task, one connector, one restaurant, the exact item list and a ceiling on the total, with an
expiry. There is no pay tool, so payment can never be allowed; anything unknown is denied.
The model is not a security boundary: this runs in code after the model proposes a call.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from friday.connectors.contract import ItemQty

READ_TOOLS = frozenset({"search_restaurants", "get_menu", "track_order"})
STATE_TOOLS = frozenset({"build_cart", "get_payment_handoff"})
# Names that must never become allowed, even if someone adds such a tool by mistake.
PAYMENT_TOOLS = frozenset(
    {"pay", "make_payment", "execute_payment", "place_order", "confirm_payment"}
)


class Verdict(StrEnum):
    allow = "allow"
    deny = "deny"
    ask = "ask"


class Grant(BaseModel):
    task_id: str
    connector: str  # "zomato.food"
    restaurant_id: str
    items: list[ItemQty]
    max_total_paise: int = Field(strict=True, gt=0)
    expires_at: datetime
    one_time: bool = True
    used_tools: set[str] = set()  # for one_time grants: each state tool may run once

    def mark_used(self, tool_name: str) -> None:
        self.used_tools.add(tool_name)


def _items_key(items: Iterable[Any]) -> dict[str, int] | None:
    """{item_id: qty}, or None if the list is malformed or repeats an id."""
    out: dict[str, int] = {}
    try:
        for it in items:
            item_id = it["item_id"] if isinstance(it, Mapping) else it.item_id
            qty = it["qty"] if isinstance(it, Mapping) else it.qty
            if item_id in out or not isinstance(qty, int):
                return None
            out[item_id] = qty
    except (KeyError, AttributeError, TypeError):
        return None
    return out


class ActionGate:
    def __init__(self, now=None) -> None:  # noqa: ANN001 - injectable clock for tests
        self._now = now or (lambda: datetime.now(UTC))

    def decide(
        self, tool_name: str, args: Mapping[str, Any], grants: Iterable[Grant]
    ) -> Verdict:
        return self.explain(tool_name, args, grants)[0]

    def explain(
        self, tool_name: str, args: Mapping[str, Any], grants: Iterable[Grant]
    ) -> tuple[Verdict, str]:
        if tool_name in PAYMENT_TOOLS:
            return Verdict.deny, "Friday never executes a payment"
        if tool_name in READ_TOOLS:
            return Verdict.allow, "read-only tool"
        if tool_name not in STATE_TOOLS:
            return Verdict.deny, "unknown tool"

        task_id, connector = args.get("task_id"), args.get("connector")
        if not task_id or not connector:
            return Verdict.deny, "task_id and connector are required"
        mine = [g for g in grants if g.task_id == task_id and g.connector == connector]
        if not mine:
            return Verdict.ask, "no approval for this task yet"

        now = self._now()
        reason = "approval does not match this action"
        expired = False
        for g in mine:
            if g.expires_at <= now:
                expired = True
                continue
            if g.one_time and tool_name in g.used_tools:
                expired = True
                continue
            mismatch = self._mismatch(g, tool_name, args)
            if mismatch is None:
                return Verdict.allow, "covered by an approval"
            reason = mismatch
        if expired and reason == "approval does not match this action":
            return Verdict.ask, "approval expired or already used"
        return Verdict.deny, reason

    @staticmethod
    def _mismatch(g: Grant, tool_name: str, args: Mapping[str, Any]) -> str | None:
        if args.get("restaurant_id") != g.restaurant_id:
            return "restaurant differs from the approval"
        if _items_key(args.get("items") or []) != _items_key(g.items):
            return "items differ from the approval"
        if tool_name == "get_payment_handoff":
            total = args.get("total_paise")
            if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
                return "cart total missing"
            if total > g.max_total_paise:
                return "total is above the approved maximum"
        return None
