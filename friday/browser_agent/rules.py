# ruff: noqa: E501
"""Deterministic page / element classification from DATA (data/rules.v1.json). No model is involved: these functions
decide what is a payment control, an irreversible click, a legal attestation, an ID-number field, a captcha."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from friday.browser_agent.types import Element, PageSnapshot

DATA = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _rules() -> dict[str, list[re.Pattern[str]]]:
    raw = json.loads((DATA / "rules.v1.json").read_text())
    out: dict[str, list[re.Pattern[str]]] = {}
    for k, v in raw.items():
        if isinstance(v, list):
            out[k] = [re.compile(p, re.I) for p in v] if k not in ("denied_domain_suffixes", "denied_domains_contains") else []
    out["_suffixes"] = [re.compile(re.escape(s) + r"$", re.I) for s in raw["denied_domain_suffixes"]]
    out["_contains"] = [re.compile(re.escape(s), re.I) for s in raw["denied_domains_contains"]]
    return out


@lru_cache(maxsize=1)
def brand_domains() -> dict[str, list[str]]:
    return {k: list(v) for k, v in json.loads((DATA / "domains.v1.json").read_text())["brands"].items()}


def _any(key: str, text: str) -> bool:
    return any(p.search(text) for p in _rules()[key])


def label(el: Element) -> str:
    """Everything a human could read about the element (UNTRUSTED text; only matched, never obeyed)."""
    return " ".join(x for x in (el.name, el.placeholder, el.type, el.autocomplete, el.group) if x).strip()


def own_label(el: Element) -> str:
    return " ".join(x for x in (el.name, el.placeholder, el.type, el.autocomplete) if x).strip()


# ----------------------------------------------------------------------------- hosts
def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def host_allowed(host: str, allowed: list[str]) -> bool:
    h = host.lower()
    return any(h == a.lower() or h.endswith("." + a.lower()) for a in allowed if a)


def domain_denied(host: str) -> bool:
    """Government / identity / payment-processor hosts can never be on a task's allow-list."""
    h = host.lower()
    return any(p.search(h) for p in _rules()["_suffixes"]) or any(p.search(h) for p in _rules()["_contains"])


def payment_url(url: str) -> bool:
    return _any("payment_url", url)


def strip_query(url: str) -> str:
    """host + path only: no query string (may carry tokens), no fragment."""
    try:
        u = urlsplit(url)
    except ValueError:
        return ""
    return f"{u.hostname or ''}{u.path or ''}"[:160]


# ----------------------------------------------------------------------------- elements
def is_payment_element(el: Element) -> bool:
    if el.autocomplete.lower().startswith("cc-"):
        return True
    return _any("payment_element", own_label(el))


def is_sensitive_id(el: Element) -> bool:
    return _any("sensitive_id_element", own_label(el))


def is_password(el: Element) -> bool:
    return el.type.lower() == "password" or _any("password_element", own_label(el))


def is_otp(el: Element) -> bool:
    return el.autocomplete.lower() == "one-time-code" or _any("otp_element", own_label(el))


def is_attestation(el: Element) -> bool:
    if el.role in ("button", "link"):
        return False
    return _any("attestation", label(el))


def is_account_creation(el: Element) -> bool:
    return el.role in ("button", "link") and _any("account_creation", own_label(el))


def is_irreversible(el: Element) -> bool:
    """A click that sends, books, cancels or signs. A submit button is irreversible unless its label is plainly navigation."""
    if el.role not in ("button", "link"):
        return False
    name = " ".join(el.name.split())
    if _any("irreversible_element", name):
        return not _any("safe_submit_labels", name.strip().lower())
    return bool(el.submit and not _any("safe_submit_labels", name.strip().lower()))


# ----------------------------------------------------------------------------- pages
def page_is_payment(snap: PageSnapshot) -> bool:
    if payment_url(snap.url):
        return True
    for el in snap.elements:
        if el.role in ("textbox", "radio", "select", "textarea", "checkbox") and is_payment_element(el):
            return True
    return _any("payment_page", snap.text)


def page_has_captcha(snap: PageSnapshot) -> bool:
    return snap.captcha or _any("captcha_markers", snap.title) or (len(snap.text) < 600 and _any("captcha_markers", snap.text))


def injection_flags(text: str) -> list[str]:
    """Which injection-looking phrases appear. Flagged for the model ('this is page data') and the log; never obeyed either way."""
    return [p.pattern[:40] for p in _rules()["injection_markers"] if p.search(text)]
