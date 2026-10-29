# ruff: noqa: E501
"""Small deterministic parsers for what a browser-loop step returns. Page text is untrusted: only numbers and short
titles are kept, clipped; nothing from it is ever executed or used as an instruction."""

from __future__ import annotations

import re

from friday.shopping.compare import parse_pack

_PRICE = re.compile(r"(?:rs\.?|inr|₹)?\s*([\d][\d,]*(?:\.\d+)?)", re.I)
_FLAG = re.compile(r"\b([a-z_]+)\s*=\s*([a-z_]+)", re.I)


def flags(text: str) -> dict[str, str]:
    """'login_wall=yes; location_prompt=no' -> {'login_wall': 'yes', ...}"""
    return {k.lower(): v.lower() for k, v in _FLAG.findall(text or "")}


def yes(text: str, key: str) -> bool:
    return flags(text).get(key, "") in ("yes", "true")


_THREE = re.compile(r"([^|;\n]+?)\s*\|\s*([^|;\n]*?)\s*\|\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_TWO = re.compile(r"([^|;\n]+?)\s*\|\s*(?:rs\.?|inr|₹)\s*(\d[\d,]*(?:\.\d+)?)", re.I)


def product_lines(text: str, limit: int = 8) -> list[dict[str, str]]:
    """'Aashirvaad Atta | 5 kg | Rs 289; Pillsbury ...' -> [{'title','pack','price'}]. The loop flattens line breaks, so entries are found by
    their '| pack | price' shape, not by line. Entries without a price are dropped."""
    rows = [(m.group(1), m.group(2), m.group(3)) for m in _THREE.finditer(text or "")]
    if not rows:
        rows = [(m.group(1), "", m.group(2)) for m in _TWO.finditer(text or "")]
    out: list[dict[str, str]] = []
    for raw_title, pack, raw_price in rows:
        title = re.sub(r"^\W*\d+[.)]\s*", "", raw_title.strip(" -*,"))[:90]
        try:
            price = float(raw_price.replace(",", ""))
        except ValueError:
            continue
        if not title or price <= 0:
            continue
        out.append({"title": title, "pack": pack.strip()[:30], "price": f"{price:g}"})
        if len(out) >= limit:
            break
    return out


def qty_of(p: dict[str, str]) -> float | None:
    return parse_pack(p.get("pack"), p.get("title"))[0]


def per_unit(p: dict[str, str]) -> float | None:
    q = qty_of(p)
    return round(float(p["price"]) / q, 1) if q else None


def matches_variant(p: dict[str, str], *, pack: str = "", brand: str = "") -> bool:
    ok = True
    if pack:
        want = parse_pack(pack)[0]
        have = qty_of(p)
        ok = ok and want is not None and have is not None and abs(want - have) < 1e-9
    if brand:
        ok = ok and re.search(rf"(?<![a-z]){re.escape(brand.lower())}(?![a-z])", p["title"].lower()) is not None
    return ok


def pick_variants(products: list[dict[str, str]], *, pack: str = "", brand: str = "") -> tuple[list[dict[str, str]], bool]:
    """-> (what to show, variant_missing). Variant given -> exactly the matches; not given (or no match) -> up to 3 main variants."""
    given = bool(pack or brand)
    if given:
        hit = [p for p in products if matches_variant(p, pack=pack, brand=brand)]
        if hit:
            return hit[:3], False
    seen: set[str] = set()
    main: list[dict[str, str]] = []
    for p in sorted(products, key=lambda p: (per_unit(p) is None, per_unit(p) or 0.0)):
        key = re.sub(r"[^a-z0-9]+", " ", p["title"].lower()).strip() + f"|{qty_of(p)}"  # same brand in another pack is another variant
        if key not in seen:
            seen.add(key)
            main.append(p)
    return main[:3], given


def row(p: dict[str, str], unit: str = "kg") -> str:
    bits = [f"Rs {p['price']}"]
    pu = per_unit(p)
    if pu:
        bits.append(f"Rs {pu:g}/{unit}")
    pack = f" {p['pack']}" if p.get("pack") and p["pack"].lower() not in p["title"].lower() else ""
    return f"{p['title']}{pack}: " + ", ".join(bits)
