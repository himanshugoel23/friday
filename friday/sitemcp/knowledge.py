# ruff: noqa: E501
"""Site knowledge: versioned DATA files (urls, selectors, flows, quirks), all marked 'unverified' until a live probe
confirms them. ``validate`` is strict: a click selector or url that smells like paying or placing an order is refused,
so a knowledge edit can never add a payment step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from friday.sitemcp.fakes.dom import selector_supported

SEED_DIR = Path(__file__).parent / "knowledge"
# words that must never appear in a selector Friday CLICKS or FILLS, or in a url Friday opens itself
PAY_TOKENS = ("place-order", "placeorder", "place_order", "pay-now", "paynow", "pay_now", "confirm-order", "confirmorder",
              "confirm_order", "upi", "cvv", "card-number", "submit-payment", "make-payment", "payment-submit", "pay-btn")
PAY_URL_TOKENS = ("/payment", "/pay/", "/pay?", "/place-order", "/placeorder", "/order/confirm", "razorpay", "juspay",
                  "paytm", "phonepe", "billdesk", "payu", "cashfree", "/checkout/pay")
STRICT_PROCEED_TOKENS = ("place", "confirm", "order", "upi", "pay-now", "paynow", "pay_now")
STATUSES = ("unverified", "verified")
REQUIRED = ("schema", "site", "display", "version", "status", "domains", "base_url", "rate", "urls", "blocked", "location",
            "search", "product", "cart", "checkout", "login")

CLICK_KEYS = (("location", "open"), ("location", "submit"), ("location", "suggestion"), ("product", "add"),
              ("product", "qty_plus"), ("checkout", "proceed"), ("login", "open"), ("login", "send_otp"),
              ("login", "verify"), ("login", "logout"))
FILL_KEYS = (("location", "input"), ("login", "phone"), ("login", "otp"))


def smells_like_payment_selector(sel: str) -> bool:
    low = sel.lower()
    return any(t in low for t in PAY_TOKENS)


def smells_like_payment_url(url: str) -> bool:
    low = url.lower()
    return any(t in low for t in PAY_URL_TOKENS)


def all_selectors(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def rec(v: Any, key: str = "") -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                rec(x, k)
        elif isinstance(v, list):
            for x in v:
                rec(x, key)
        elif isinstance(v, str) and key in SELECTOR_KEYS:
            sel = v.rsplit("@", 1)[0] if "@" in v else v  # 'a@href' = selector + attribute
            if sel:
                out.append(sel)

    for part in ("location", "search", "product", "cart", "checkout", "login", "blocked", "probe"):
        rec(doc.get(part, {}))
    return out


SELECTOR_KEYS = {"open", "input", "submit", "suggestion", "current", "row", "title", "price", "mrp", "pack", "rating", "stock",
                 "url", "name", "qty", "add", "qty_plus", "proceed", "fee_row", "label", "amount", "total", "payment_marker",
                 "phone", "send_otp", "otp", "verify", "logged_in_marker", "logout", "selectors", "id_attr", "bill"}


def validate(doc: dict[str, Any]) -> list[str]:
    p: list[str] = []
    for k in REQUIRED:
        if k not in doc:
            p.append(f"missing key: {k}")
    if p:
        return p
    if doc["schema"] != 1:
        p.append("schema must be 1")
    if doc["status"] not in STATUSES:
        p.append("status must be unverified or verified")
    base = urlsplit(doc["base_url"])
    if base.scheme not in ("https", "http") or (base.hostname or "") not in doc["domains"]:
        p.append("base_url host must be listed in domains")
    for sec, key in CLICK_KEYS + FILL_KEYS:
        sel = (doc.get(sec) or {}).get(key)
        if sel and smells_like_payment_selector(sel):
            p.append(f"{sec}.{key} looks like a payment control")
    proceed = (doc["checkout"] or {}).get("proceed") or ""
    if any(t in proceed.lower() for t in STRICT_PROCEED_TOKENS):
        p.append("checkout.proceed looks like placing an order")
    for name, tpl in doc["urls"].items():
        if smells_like_payment_url(tpl):
            p.append(f"urls.{name} looks like a payment url")
    for s in all_selectors(doc):
        if not selector_supported(s):
            p.append(f"selector outside the supported css subset: {s}")
    return p


def load_one(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems = validate(doc)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return doc


def load_knowledge(directory: Path = SEED_DIR) -> dict[str, dict[str, Any]]:
    return {d["site"]: d for d in (load_one(f) for f in sorted(directory.glob("*.v*.json")))}
