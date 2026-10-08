"""Deterministic document extraction (fake path): from the text content when the
media is text, else from the filename/metadata ("coolcare_quote_699.jpg")."""

from __future__ import annotations

import re

from friday.core.models import ExtractionKind

from ..schemas import ExtractOut, PriceItemOut
from ..textutil import extract_amounts

_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z][\w &()'/.-]{1,60}?)\s*(?:[-:.…]+|\s{2,}|\t)\s*"
    r"(?:₹|rs\.?|inr)?\s*(?P<amt>\d[\d,]*)\s*(?:/-)?\s*(?P<unit>(?:per|/)\s*\w+)?\s*$",
    re.I,
)


def guess_kind(name: str, hint: str = "") -> ExtractionKind:
    s = f"{name} {hint}".lower()
    for word, kind in (
        ("menu", ExtractionKind.MENU),
        ("price", ExtractionKind.PRICE_LIST),
        ("rate", ExtractionKind.PRICE_LIST),
        ("quote", ExtractionKind.QUOTE),
        ("quotation", ExtractionKind.QUOTE),
        ("estimate", ExtractionKind.QUOTE),
        ("bill", ExtractionKind.BILL),
        ("invoice", ExtractionKind.BILL),
        ("receipt", ExtractionKind.BILL),
    ):
        if word in s:
            return kind
    return ExtractionKind.GENERIC


def extract(payload: dict) -> ExtractOut:
    filename = payload.get("filename") or ""
    hint = payload.get("hint") or ""
    requested = payload.get("kind") or "generic"
    kind = ExtractionKind(requested) if requested != "generic" else guess_kind(filename, hint)
    text = payload.get("text") or ""
    items: list[PriceItemOut] = []
    if text:
        for line in text.splitlines():
            m = _LINE.match(line)
            if m:
                amt = int(m.group("amt").replace(",", ""))
                unit = (m.group("unit") or "").replace("/", "per ").strip() or None
                items.append(
                    PriceItemOut(
                        name=m.group("name").strip(),
                        amount_inr=amt,
                        price_text=line.strip(),
                        unit=unit,
                    )
                )
    stem = re.sub(r"\.[a-z0-9]+$", "", filename.lower())
    business = None
    words = [
        w
        for w in re.split(r"[_\-\s]+", stem)
        if w
        and not w.isdigit()
        and w
        not in {
            "menu",
            "quote",
            "price",
            "list",
            "bill",
            "invoice",
            "img",
            "image",
            "scan",
            "pricelist",
            "rate",
            "card",
            "photo",
            "doc",
            "pdf",
            "wa",
            "whatsapp",
        }
    ]
    if words:
        business = " ".join(w.title() for w in words[:3])
    total = None
    m = re.search(r"(?:total|grand total|net)\s*[:=-]?\s*(?:₹|rs\.?)?\s*(\d[\d,]*)", text, re.I)
    if m:
        total = int(m.group(1).replace(",", ""))
    if total is None and kind == ExtractionKind.QUOTE:
        nums = [int(n) for n in re.findall(r"(?<!\d)(\d{3,6})(?!\d)", stem)]
        amounts = extract_amounts(text) if text else []
        total = (amounts[-1] if amounts else None) or (nums[-1] if nums else None)
    if not text:
        text = f"[{kind.value} from {filename or 'attachment'}]" + (
            f" total {total}" if total else ""
        )
    inclusions = [
        ln.strip("•*- ").strip()
        for ln in text.splitlines()
        if re.search(r"includ|free|with ", ln, re.I)
    ][:5]
    return ExtractOut(
        kind=kind,
        text=text,
        items=items,
        business_name=business,
        quote_amount_inr=total,
        quote_text=(f"₹{total}" if total else None),
        inclusions=inclusions,
        confidence=0.9 if items or total else 0.4,
    )
