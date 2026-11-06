# ruff: noqa: E501
"""Landing page variants s1, s2, s3 (docs/ROBIN_LANDING_BRIEF.md revision 2): page contract, claims policy, word budget, router serving."""

from __future__ import annotations

import importlib
import re
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.robinwaitlist import variants
from friday.robinwaitlist.router import waitlist_router
from friday.robinwaitlist.store import WaitlistStore

IDS = ["s1", "s2", "s3"]
FOOTER = "Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet."
TRUST = "Your parents are told, can stop it any time, and Robin does not read their chats or record their phone calls."
CARDS = [
    (
        "https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud",
        "The Tribune",
        "4 Jun 2025",
        "Chandigarh's elderly woman loses Rs 2.5 crore in digital arrest fraud",
    ),
    (
        "https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app",
        "Free Press Journal",
        "12 Jan 2022",
        "Mumbai: Senior citizen loses Rs 3.95 lakh to KYC fraud after downloading AnyDesk app",
    ),
    (
        "https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore",
        "Free Press Journal",
        "30 Sep 2026",
        "UPI Limit Scam Costs Pensioner Couple Nearly ₹6 Lakh In Indore",
    ),
]
# plain substrings, case-insensitive
BANNED_SUBSTR = [
    "24/7",
    "round the clock",
    "guarantee",
    "100%",
    "never fooled",
    "always watching",
    "never alone",
    "alone",
    "scared",
    "3 am",
    "before it is too late",
    "what if",
    "we are watching",
    "testimonial",
    "shocking",
    "victim",
    "drained",
    "wiped out",
    "800 km",
    "hinglish",
]
# whole words (so "far" does not hit "farther" and "fall" does not hit "waterfall"), case-insensitive
BANNED_WORDS = [
    "stops",
    "blocks",
    "prevents",
    "far",
    "fall",
    "clock",
    "countdown",
    "shield",
    "shields",
    "countdowns",
]
WORD_CAP = 900


def page(v: str) -> str:
    return str(importlib.import_module(f"friday.robinwaitlist.variants.{v}").PAGE)


def visible_text(html: str) -> str:
    body = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text.replace("&#8618;", " ").replace("&#8599;", " ")).strip()


def without_cards(html: str) -> str:
    """Page with the sourced incident report cards removed (amounts may appear only inside them)."""
    return re.sub(r'<div class="rep">.*?</div>', " ", html, flags=re.S)


def test_available_variants_are_s1_s2_s3():
    assert variants.available() == IDS
    assert variants.load("a") is None and variants.load("b") is None and variants.load("zz") is None


@pytest.mark.parametrize("v", IDS)
def test_page_contract(v):
    html = page(v)
    text = visible_text(html)
    for needle in (
        'id="name"',
        'id="phone"',
        'id="website"',
        'tabindex="-1"',
        'type="tel"',
        'fetch("join"',
        "{{VARIANT}}",
        'name="robots" content="noindex"',
        'href="privacy"',
        "consent:true",
        "?src=share",
        "https://wa.me/?text=",
        'id="sticky"',
        '<html lang="en">',
        "No payment. No price announced yet.",
    ):
        assert needle in html, needle
    assert (
        html.count('type="text"') == 2 and html.count('type="tel"') == 1 and "checkbox" not in html
    )  # name, honeypot, number
    assert len(re.findall(r"<details\b", html)) == 6
    assert FOOTER in text and TRUST in text
    assert (
        "We will WhatsApp you about the launch, nothing else. Your number is not sold or shared for ads, and we delete it on request."
        in text
    )
    assert 'id="lang"' not in html and "setLang" not in html  # English only, no language toggle
    assert 'lang="hi"' in html and re.search(
        r"[ऀ-ॿ]", html
    )  # parent's language only inside the phone mock-ups
    assert "optional Android app" in text
    assert len(html.encode()) < 70_000
    assert html.count('target="_blank" rel="noopener"') >= 3


@pytest.mark.parametrize("v", IDS)
def test_three_sourced_incident_cards_exactly_as_brief(v):
    html, text = page(v), visible_text(page(v))
    for url, outlet, date, headline in CARDS:
        assert f'href="{url}" target="_blank" rel="noopener"' in html
        assert outlet in text and date in text and headline in text
    assert "News reports, linked in full. Robin is not mentioned in them." in text
    assert len(re.findall(r'<div class="rep">', html)) == 3


@pytest.mark.parametrize("v", IDS)
def test_claims_policy(v):
    html = page(v)
    low = visible_text(html).lower()
    script = " ".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S)).lower()
    for where, text in (("visible text", low), ("script", script)):
        for phrase in BANNED_SUBSTR:
            assert phrase not in text, f"{v}: banned phrase {phrase!r} in {where}"
        for w in BANNED_WORDS:
            assert not re.search(rf"\b{w}\b", text), f"{v}: banned word {w!r} in {where}"
    # amounts and rupee figures only inside the three sourced cards, never in the hero or elsewhere
    outside = visible_text(without_cards(html)).lower()
    for token in ("crore", "lakh", "₹", "rs 2", "rs 3", "rs 6"):
        assert token not in outside, f"{v}: {token!r} outside the incident cards"
    # the scam verdict is never "safe" for money; no call recording / police / human-desk claims
    for phrase in (
        "police will",
        "we call the police",
        "contacts the police",
        "human team",
        "our team will call",
        "records calls",
        "listens to calls",
    ):
        assert phrase not in low


@pytest.mark.parametrize("v", IDS)
def test_word_budget(v):
    words = len(visible_text(page(v)).split())
    print(f"variant {v}: {words} visible words")
    assert words < WORD_CAP, words


@pytest.mark.parametrize("v", IDS)
def test_router_serves_variant_with_token_replaced_and_accepts_join(v, tmp_path):
    store = WaitlistStore(tmp_path / "wl", now=lambda: datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(waitlist_router(store, contact="x"), prefix="/robin")
    client = TestClient(app)
    r = client.get(f"/robin?v={v}")
    assert r.status_code == 200 and f'v:"{v}"' in r.text and "{{VARIANT}}" not in r.text
    j = client.post(
        "/robin/join",
        json={"name": "Asha", "phone": "98765 43210", "consent": True, "src": "t", "v": v},
    )
    assert j.json() == {"ok": True} and store.count() == 1
    assert (
        store._rows()[0]["v"] == v
    )  # the variant id survives into the stored row (so the report can split by variant)
    legacy = client.get("/robin?v=legacy")
    assert (
        legacy.status_code == 200 and "Mom is alone" in legacy.text
    )  # the retired page stays reachable for comparison


def test_router_without_variant_redirects_to_one_of_the_three(tmp_path):
    store = WaitlistStore(tmp_path / "wl", now=lambda: datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(waitlist_router(store, contact="x"), prefix="/robin")
    r = TestClient(app).get("/robin?src=wa", follow_redirects=False)
    assert r.status_code == 302 and re.search(r"v=s[123]&src=wa$", r.headers["location"])
