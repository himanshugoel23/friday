# ruff: noqa: E501
"""compare_and_suggest: REUSES the shopping assistant's pieces as they are (ShoppingAgent for the popular brands,
``recommend`` for the ONE pick and its reason). Nothing is re-implemented here; this only adapts the step's data."""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.planner import signals as sg
from friday.shopping import catalog
from friday.shopping.agent import ShoppingAgent
from friday.shopping.compare import Product, ShoppingInput, dedupe, parse_pack, recommend


@dataclass
class Suggested:
    lines: list[str] = field(default_factory=list)  # other popular brands, one line each (printed values only)
    pick: str = ""
    reason: str = ""


def _own(p: dict[str, str], store: str) -> Product:
    qty, label = parse_pack(p.get("pack"), p.get("title"))
    price = float(p["price"])
    return Product(title=p["title"], store=store or None, price_inr=price, pack_qty=qty, pack_label=label or (p.get("pack") or None),
                   price_per_unit=round(price / qty, 1) if qty else None)


class ShoppingSuggester:
    def __init__(self, agent: ShoppingAgent, *, store: str = "") -> None:
        self.agent, self.store = agent, store

    async def suggest(self, *, user_id: str, category: str, area: str, lang: str, own: list[dict[str, str]]) -> Suggested | None:
        cat = catalog.categories().get(category)
        if cat is None:
            return None
        pin = sg.pincode_in(area or "")
        out = await self.agent.run(ShoppingInput(query=cat.id, category_id=cat.id, pincode=pin, area=None if pin else (area or None), lang=lang, user_id=user_id))
        mine = [_own(p, self.store) for p in own]
        theirs = out.products if out.status == "ok" else []
        merged = dedupe([*mine, *theirs])
        if not merged:
            return None
        rec = recommend(merged, cat, lang)
        unit = "kg" if cat.unit == "kg" else "L"
        mine_titles = {p.title.lower() for p in mine}
        lines = []
        for p in merged:
            if p.title.lower() in mine_titles or p.price_inr is None:
                continue
            bit = f"Rs {p.price_inr:g}" + (f", Rs {p.price_per_unit:g}/{unit}" if p.price_per_unit else "") + (f" ({p.store})" if p.store else "")
            lines.append(f"{p.title}: {bit}")
        return Suggested(lines=lines[:3], pick=rec.product.title if rec else "", reason=rec.reason if rec else "")
