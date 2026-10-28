"""Typed contracts and the pure comparison: price per kg/L from the printed pack size, ONE pick, a reason
built only from facts that are on the page. No network, no model: everything here is deterministic."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from friday.planner.web import WebItem, WebSource
from friday.shopping.catalog import Category

_PACK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|gram|grams|l|ltr|litre|litres|liter|liters|ml)\b", re.I)
_MULT_RE = re.compile(r"(\d+)\s*(?:x|×|pack of)\s*$", re.I)
_PRICE_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)", re.I)
_BASE = {"kg": 1.0, "kgs": 1.0, "g": 0.001, "gm": 0.001, "gms": 0.001, "gram": 0.001, "grams": 0.001,
         "l": 1.0, "ltr": 1.0, "litre": 1.0, "litres": 1.0, "liter": 1.0, "liters": 1.0, "ml": 0.001}  # fmt: skip


class ShoppingInput(BaseModel):
    query: str
    category_id: str
    retailer: str | None = None
    pincode: str | None = None
    area: str | None = None
    lang: str = "hinglish"


class Product(BaseModel):
    title: str
    store: str | None = None
    url: str | None = None  # a cited product page
    price_inr: float | None = None
    pack_qty: float | None = None  # kg or litres
    pack_label: str | None = None
    price_per_unit: float | None = None  # Rs per kg / L
    rating: float | None = None
    rating_count: int | None = None
    ingredients: str | None = None
    image_url: str | None = None  # https only, from a cited product page
    ingredient_hits: list[str] = Field(default_factory=list)
    ingredient_flags: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    product: Product
    reason: str  # one line; every clause is a fact shown on the page


class ShoppingOutput(BaseModel):
    status: Literal["ok", "no_result", "timeout", "unavailable"]
    category_id: str
    retailer: str | None = None
    products: list[Product] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    sources: list[WebSource] = Field(default_factory=list)
    as_of: datetime
    retailer_price_hidden: bool = False
    unit: str = "kg"
    from_cache: bool = False


def parse_pack(*texts: str | None) -> tuple[float | None, str | None]:
    """'2 x 500 g' -> (1.0, '2 x 500 g'); '5 kg' -> (5.0, '5 kg'). None when no pack size is printed."""
    for text in texts:
        if not text:
            continue
        m = _PACK_RE.search(text)
        if not m:
            continue
        qty = float(m.group(1)) * _BASE[m.group(2).lower()]
        mult = _MULT_RE.search(text[: m.start()])
        if mult:
            qty *= int(mult.group(1))
        if qty > 0:
            return qty, text[(mult.start() if mult else m.start()) : m.end()].strip()
    return None, None


def price_of(item: WebItem) -> float | None:
    if item.price_inr is not None and item.price_inr > 0:
        return float(item.price_inr)
    if item.price_text:
        m = _PRICE_RE.search(item.price_text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                return None
    return None


def build_product(item: WebItem, cat: Category) -> Product:
    """A WebItem -> Product. A number is kept ONLY when the item's page is a cited source (the web port
    already drops uncited urls); an item without one shows its name and nothing else."""
    cited = item.url is not None
    price = price_of(item) if cited else None
    qty, label = parse_pack(item.pack_text, item.title)
    ppu = round(price / qty, 1) if (price is not None and qty) else None
    ing = (item.ingredients or "").lower()
    hits = [t for t in cat.positive if t.lower() in ing] if cited else []
    flags = [t for t in cat.negative if re.search(rf"(?<![a-z]){re.escape(t.lower())}(?![a-z])", ing)] if cited else []
    return Product(
        title=item.title, store=item.store, url=item.url, price_inr=price, pack_qty=qty, pack_label=label,
        price_per_unit=ppu, rating=item.rating if cited else None, rating_count=item.rating_count if cited else None,
        ingredients=item.ingredients if cited else None, image_url=None,
        ingredient_hits=hits, ingredient_flags=flags,
    )  # fmt: skip


def dedupe(products: list[Product]) -> list[Product]:
    """One row per product title (cheapest price per unit wins), keeping the first four distinct titles."""
    best: dict[str, Product] = {}
    for p in products:
        key = " ".join(re.findall(r"[a-z0-9]+", p.title.lower()))
        cur = best.get(key)
        if cur is None or (p.price_per_unit or 1e9) < (cur.price_per_unit or 1e9):
            best[key] = p
    return list(best.values())[:4]


def _score(p: Product, cat: Category, min_ppu: float | None) -> float:
    w = cat.weights
    s = 0.0
    if p.price_per_unit and min_ppu:
        s += w.get("price", 1.0) * (min_ppu / p.price_per_unit)
    if p.rating:
        s += w.get("rating", 0.5) * max(0.0, min(1.0, (p.rating - 3.0) / 2.0))
    s += w.get("ingredients", 0.5) * (min(1, len(p.ingredient_hits)) - min(1, len(p.ingredient_flags)))
    return s


def recommend(products: list[Product], cat: Category, lang: str = "hinglish") -> Recommendation | None:
    """ONE pick with a one-line reason. Needs at least one product with a visible price; every clause of
    the reason is a fact present on the page (cheapest per kg/L, ingredient phrase, rating)."""
    priced = [p for p in products if p.price_inr is not None]
    if not priced:
        return None
    ppus = [p.price_per_unit for p in priced if p.price_per_unit]
    min_ppu = min(ppus) if ppus else None
    top = max(priced, key=lambda p: (_score(p, cat, min_ppu), -(p.price_inr or 0)))
    unit = "kg" if cat.unit == "kg" else "L"
    bits: list[str] = []
    if top.price_per_unit and len(ppus) > 1 and top.price_per_unit == min_ppu:
        bits.append(f"lowest price per {unit} (Rs {top.price_per_unit:g}/{unit})" if lang == "en" else f"sabse kam daam per {unit} (Rs {top.price_per_unit:g}/{unit})")
    if top.ingredient_hits:
        bits.append(f"label says {top.ingredient_hits[0]}" if lang == "en" else f"label par {top.ingredient_hits[0]} likha hai")
    if top.rating and top.rating >= 4.0 and len(priced) > 1:
        n = f" by {top.rating_count:,} buyers" if top.rating_count else ""
        bits.append(f"rated {top.rating:g}{n}" if lang == "en" else f"rating {top.rating:g}" + (f" ({top.rating_count:,} log)" if top.rating_count else ""))
    if not bits:
        if len(priced) == 1:
            bits.append("the only one with a visible price" if lang == "en" else "sirf isi ka daam dikh raha hai")
        else:
            bits.append("best value among the prices I could see" if lang == "en" else "jo daam dikhe unme sabse achhi value")
    return Recommendation(product=top, reason=(", ".join(bits[:2])))
