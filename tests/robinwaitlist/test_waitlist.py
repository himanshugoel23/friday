# ruff: noqa: E501
"""Robin waitlist: page, sign-up rules, abuse limits, storage, reports, founder chat command."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.robinwaitlist.router import waitlist_router
from friday.robinwaitlist.store import WaitlistStore, clean_src

GOOD = {"name": "Asha", "phone": "98765 43210", "consent": True, "src": "wa-group"}


@pytest.fixture
def env(tmp_path):
    store = WaitlistStore(tmp_path / "wl", now=lambda: datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(waitlist_router(store, contact="WhatsApp DELETE to the number that invited you"), prefix="/robin")
    return TestClient(app), store


def test_page_is_visual_short_and_honest_and_asks_only_name_and_number(env):
    import re

    client, store = env
    r = client.get("/robin?src=wa-group")
    assert r.status_code == 200 and "Robin is not live yet" in r.text and "not an emergency service" in r.text
    assert r.headers["x-robots-tag"] == "noindex" and "testimonial" not in r.text.lower()
    assert "Hinglish" in r.text  # language toggle is present
    assert "Mom is alone" in r.text and "At 3 am, who finds out first?" in r.text and "Robin can." in r.text
    assert "<svg" in r.text and r.text.count('class="ph') >= 3  # the design carries the story: illustration + phone mock-ups
    for url in ("tribuneindia.com/news/chandigarh", "freepressjournal.in/amp/mumbai", "freepressjournal.in/indore"):
        assert url in r.text  # every news card links to the publisher's own page
    body = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", r.text, flags=re.S)
    words = len(re.sub(r"<[^>]+>", " ", body).split())
    assert words < 360, words  # includes phone mock-up text, the hidden thank-you block and legal lines; the story itself is a few words per screen
    visible = re.findall(r'<input[^>]*type="(text|tel|checkbox|email)"', r.text)
    assert visible.count("text") == 2 and visible.count("tel") == 1 and "checkbox" not in visible  # name, honeypot, number only
    assert "1 page views" in store.summary()


def test_privacy_page_shows_the_contact(env):
    client, _ = env
    r = client.get("/robin/privacy")
    assert r.status_code == 200 and "WhatsApp DELETE" in r.text and "not sell" in r.text


def test_valid_signup_is_stored_and_idempotent(env):
    client, store = env
    assert client.post("/robin/join", json=GOOD).json() == {"ok": True}
    assert client.post("/robin/join", json=GOOD).json() == {"ok": True}
    assert store.count() == 1
    row = store._rows()[0]
    assert row["phone"] == "+919876543210" and row["src"] == "wa-group" and row["city"] == "" and row["consent"]


@pytest.mark.parametrize("patch,field", [({"consent": False}, "consent"), ({"name": "  "}, "name"), ({"phone": "123"}, "phone"), ({"phone": "+91 98765"}, "phone"), ({"phone": "abc"}, "phone")])
def test_invalid_inputs_are_rejected_with_the_field(env, patch, field):
    client, store = env
    r = client.post("/robin/join", json={**GOOD, **patch})
    assert r.status_code == 422 and r.json()["field"] == field and store.count() == 0


def test_international_numbers_are_accepted_for_nri_children(env):
    client, store = env
    assert client.post("/robin/join", json={**GOOD, "phone": "+1 415 555 0100"}).json()["ok"]
    assert store._rows()[0]["phone"] == "+14155550100"


def test_honeypot_pretends_success_and_stores_nothing(env):
    client, store = env
    assert client.post("/robin/join", json={**GOOD, "website": "http://spam"}).json() == {"ok": True}
    assert store.count() == 0


def test_unknown_fields_are_refused(env):
    client, _ = env
    assert client.post("/robin/join", json={**GOOD, "admin": True}).status_code == 422


def test_per_ip_rate_limit(env):
    client, store = env
    codes = [client.post("/robin/join", json={**GOOD, "phone": f"98765 {43210 + i}"}).status_code for i in range(10)]
    assert codes[:8] == [200] * 8 and 429 in codes[8:] and store.count() == 8


def test_src_is_sanitised():
    assert clean_src("WA-Group") == "wa-group" and clean_src("<script>") == "direct" and clean_src(None) == "direct" and clean_src("x" * 40) == "direct"


def test_files_are_private_and_lines_can_be_encrypted(tmp_path):
    class Fake:
        def encrypt(self, text, *, aad):
            return "enc:" + text[::-1]

        def decrypt(self, token, *, aad):
            return token[4:][::-1]
    store = WaitlistStore(tmp_path / "wl", cipher=Fake())
    store.add(name="Ravi", phone="+919876543210", city="Pune", lang="hindi", whom="mother", worries=[], src="x")
    raw = (tmp_path / "wl" / "signups.jsonl").read_text()
    assert "9876543210" not in raw and raw.startswith("enc:")
    assert stat.S_IMODE(os.stat(tmp_path / "wl" / "signups.jsonl").st_mode) == 0o600 and stat.S_IMODE(os.stat(tmp_path / "wl").st_mode) == 0o700
    assert store._rows()[0]["name"] == "Ravi"


def test_summary_masks_phones_and_csv_has_full_numbers(env):
    client, store = env
    client.post("/robin/join", json=GOOD)
    s = store.summary()
    assert "1 sign-ups" in s and "wa-group" in s and "+919876543210" not in s and "10" in s
    assert "+919876543210" in store.csv() and store.csv().splitlines()[0].startswith("id,time,name,phone")


def test_delete_phone_and_delete_all(env):
    client, store = env
    client.post("/robin/join", json=GOOD)
    assert store.delete_phone("+919876543210") == 1 and store.count() == 0
    client.post("/robin/join", json=GOOD)
    store.delete_all()
    assert store.count() == 0


def test_ops_routes_are_token_gated_and_switch_gated(monkeypatch, tmp_path):
    from friday.api.opsstatus import ops_status_router

    token = "t" * 24
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", token)

    class St:
        robin_waitlist_enabled = True
        robin_waitlist_dir = str(tmp_path / "wl")

    class C:
        settings = St()

    app = FastAPI()
    app.state.container = C()
    app.include_router(ops_status_router(), prefix="/ops-status")
    client = TestClient(app)
    WaitlistStore(tmp_path / "wl").add(name="Ravi", phone="+919876543210", city="Pune", lang="hindi", whom="mother", worries=["bills"], src="x")
    assert client.get(f"/ops-status/{token}/waitlist").status_code == 200 and "1 sign-ups" in client.get(f"/ops-status/{token}/waitlist").text
    assert "+919876543210" in client.get(f"/ops-status/{token}/waitlist.csv").text
    assert client.get("/ops-status/wrongtoken123456789/waitlist").status_code == 404
    St.robin_waitlist_enabled = False
    assert client.get(f"/ops-status/{token}/waitlist").status_code == 404


def test_switch_defaults_off_and_script_exists():
    from pathlib import Path

    from friday.core.config import Settings
    assert Settings().robin_waitlist_enabled is False
    assert (Path(__file__).parents[2] / "deploy" / "enable-robin-waitlist.sh").exists()


def test_ab_harness_redirects_keeps_the_variant_and_reports_join_rate(tmp_path, monkeypatch):
    from friday.robinwaitlist import variants

    pages = {"a": '<html><body>PAGE A <script>v="{{VARIANT}}"</script></body></html>', "b": '<html><body>PAGE B <script>v="{{VARIANT}}"</script></body></html>'}
    monkeypatch.setattr(variants, "available", lambda: ["a", "b"])
    monkeypatch.setattr(variants, "load", lambda v: pages[v].replace("{{VARIANT}}", v) if v in pages else None)
    store = WaitlistStore(tmp_path / "wl", now=lambda: datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(waitlist_router(store), prefix="/robin")
    client = TestClient(app, follow_redirects=False)
    r = client.get("/robin?src=family")
    assert r.status_code == 302 and "v=" in r.headers["location"] and "src=family" in r.headers["location"]
    ra = client.get("/robin?v=a&src=family")
    assert ra.status_code == 200 and "PAGE A" in ra.text and 'v="a"' in ra.text
    assert "PAGE B" in client.get("/robin?v=b").text
    assert client.get("/robin?v=zz").status_code == 200  # unknown variant: the default page, never an error
    client.post("/robin/join", json={**GOOD, "v": "a"})
    s = store.summary()
    assert "By page variant:" in s and "a=1 of 1 views (100.0%)" in s and "b=0 of 1 views" in s
    assert store._rows()[0]["v"] == "a" and ',"a",' in store.csv().splitlines()[1]


def test_variant_ids_can_be_restricted(tmp_path, monkeypatch):
    from friday.robinwaitlist import variants

    monkeypatch.setattr(variants, "available", lambda: ["a", "b", "c"])
    monkeypatch.setattr(variants, "load", lambda v: f"<html>PAGE {v}</html>")
    app = FastAPI()
    app.include_router(waitlist_router(WaitlistStore(tmp_path / "wl"), variant_ids=["b"]), prefix="/robin")
    client = TestClient(app, follow_redirects=False)
    assert all("v=b" in client.get("/robin").headers["location"] for _ in range(5))
