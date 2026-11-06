# ruff: noqa: E501
"""Landing page variants A/B/C (docs/ROBIN_LANDING_BRIEF.md): page contract, claims policy, word budget, router serving."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.robinwaitlist import variants
from friday.robinwaitlist.router import waitlist_router
from friday.robinwaitlist.store import WaitlistStore

IDS = ["a", "b", "c"]
BANNED = [
    "24/7",
    "round the clock",
    "guarantee",
    "100% safe",
    "never alone",
    "alone",
    "scared",
    "3 am",
    "before it is too late",
    "800 km",
    "crore",
    "lakh",
    "fall",
    "we are watching",
    "always watching",
    "testimonial",
]
TRIBUNE = "https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud"
FPJ = "https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app"
FOOTER = "Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet."
WORD_CAP = 520


def page(v: str) -> str:
    import importlib

    return str(importlib.import_module(f"friday.robinwaitlist.variants.{v}").PAGE)


def visible_text(html: str) -> str:
    body = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text.replace("&#8618;", " ")).strip()


def script_text(html: str) -> str:
    return " ".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S))


def test_all_three_variants_are_available():
    assert {"a", "b", "c"} <= set(variants.available())


@pytest.mark.parametrize("v", IDS)
def test_page_contract(v):
    html = page(v)
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
        TRIBUNE,
        FPJ,
        "No payment. No price announced yet.",
        "consent:true",
        "?src=share",
        "https://wa.me/?text=",
        'id="sticky"',
    ):
        assert needle in html, needle
    assert (
        html.count('type="text"') == 2 and html.count('type="tel"') == 1 and "checkbox" not in html
    )  # name, honeypot, number
    assert len(re.findall(r"<details\b", html)) == 5
    assert FOOTER in visible_text(html) and "Ask us to delete it any time." in visible_text(html)
    assert html.count('target="_blank" rel="noopener"') >= 2
    assert "hi-Latn" in html and "Hinglish" in html
    assert "Robin ek AI assistant hai, insaan nahi." in script_text(html)
    assert len(html.encode()) < 70_000


@pytest.mark.parametrize("v", IDS)
def test_claims_policy_no_banned_phrase(v):
    html = page(v)
    hay = [
        ("visible text", visible_text(html).lower()),
        ("script/Hinglish dictionary", script_text(html).lower()),
    ]
    for where, text in hay:
        for phrase in BANNED:
            assert phrase.lower() not in text, f"{v}: banned phrase {phrase!r} in {where}"
    for bad in ("clock", "countdown", "shield"):
        assert bad not in visible_text(html).lower()


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
    assert variants.load(v).replace('fetch("join"', 'fetch("/robin/join"').replace('href="privacy"', 'href="/robin/privacy"') == r.text
    j = client.post(
        "/robin/join",
        json={"name": "Asha", "phone": "98765 43210", "consent": True, "src": "t", "v": v},
    )
    assert j.json() == {"ok": True} and store.count() == 1
