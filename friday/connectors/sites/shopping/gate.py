"""Gate for the shopping tools: ``ExtendedGate`` + ``cancel_order``.

Cancelling is irreversible, so it needs its OWN approval: a ``Grant`` for the same task and
connector whose ``restaurant_id`` is the order id and whose single item is ``cancel`` x 1. A grant
from buying something can never cover it (the ids differ), and anything unknown is still denied.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from friday.connectors.gate import Grant, Verdict
from friday.connectors.sites.safety import ExtendedGate

SHOP_READ_TOOLS = frozenset({"search_products", "get_product", "track_order_status"})


class ShopGate(ExtendedGate):
    def explain(self, tool_name: str, args: Mapping[str, Any], grants: Iterable[Grant]
                ) -> tuple[Verdict, str]:
        if tool_name in SHOP_READ_TOOLS:
            return Verdict.allow, "read-only tool"
        if tool_name == "cancel_order":
            mapped = {**args, "restaurant_id": args.get("order_id"),
                      "items": [{"item_id": "cancel", "qty": 1}]}
            return super().explain("build_cart", mapped, grants)
        return super().explain(tool_name, args, grants)
