# ruff: noqa: E501
"""Slice 7 parity features. Fakes only: no mailbox, no WhatsApp, no call."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from friday.chatbot import templates
from friday.chatbot.parity import calendar as cal
from friday.chatbot.parity import copy, escalation, nudge, pricing, rides, turns
from friday.chatbot.parity import digest as dg
from friday.chatbot.parity.invites import InviteLedger, hash_token
from friday.core.config import Settings
from tests.chatbot.conftest import build_chat

LANGS = ("hinglish", "hi", "en")


# ---------------------------------------------------------------- copy
def test_every_line_has_three_languages_and_formats():
    for key, v in copy.LINES.items():
        assert set(v) == set(LANGS), key
    assert copy.PENDING_FOUNDER_APPROVAL is True


# ---------------------------------------------------------------- 1 digest
def inbox(**kw):
    base = dict(
        mails=(
            dg.Mail("1", "Asha", "Quote for website", needs_reply=True),
            dg.Mail("2", "bank@x.example", "Update your PAN immediately", "click link to verify KYC"),
            dg.Mail("3", "news", "Weekly news"),
        ),
        storage_pct=99,
        renewals=(dg.Renewal("Domain", date(2026, 11, 30)), dg.Renewal("Netflix", date(2026, 11, 5))),
    )
    base.update(kw)
    return dg.Inbox(**base)


@pytest.mark.parametrize("lang", LANGS)
def test_digest_has_leads_phishing_storage_and_dated_renewals(lang):
    d = dg.build_digest(inbox(), lang)
    assert "Asha" in d.text and "99" in d.text
    assert "Update your PAN" in d.text and d.phishing_ids == ["2"]
    assert "5 Nov 2026" in d.text and d.text.index("Netflix") < d.text.index("Domain")
    assert "Weekly news" not in d.text


def test_phishing_needs_id_word_and_action_word():
    assert dg.is_phishing(dg.Mail("a", "x", "KYC update required"))
    assert not dg.is_phishing(dg.Mail("a", "x", "Your PAN card photo"))
    assert not dg.is_phishing(dg.Mail("a", "x", "Please update the invoice"))


def test_empty_inbox_says_nothing_important():
    assert dg.build_digest(dg.Inbox(), "en").text == copy.line("digest_empty", "en")


def test_digest_corrects_a_wrong_prior_claim():
    first = dg.build_digest(inbox(), "en")
    later = dg.build_digest(inbox(storage_pct=60, renewals=(dg.Renewal("Netflix", date(2026, 12, 5)),)), "en")
    assert later.corrections == []
    fixed = dg.build_digest(
        inbox(storage_pct=60, renewals=(dg.Renewal("Netflix", date(2026, 12, 5)),)), "en", prior=first.claims
    )
    assert "Correction" in fixed.text
    assert "Netflix renewal 5 Dec 2026" in fixed.text
    assert any("storage 99%" in old for old, _ in fixed.corrections)


def test_no_correction_when_nothing_changed():
    first = dg.build_digest(inbox(), "en")
    assert dg.build_digest(inbox(), "en", prior=first.claims).corrections == []


def test_digest_deadline_two_minutes():
    assert dg.within_deadline(0, 119) and not dg.within_deadline(0, 121)
    assert dg.due_for_digest(0, 5, False) and not dg.due_for_digest(0, 5, True)


# ---------------------------------------------------------------- 3 invites
def test_invites_count_down_and_tokens_are_hashed_at_rest():
    led = InviteLedger(quota=2)
    l1 = led.issue("u1", "https://x.example/")
    l2 = led.issue("u1", "https://x.example")
    assert led.issue("u1", "https://x.example") is None and led.left("u1") == 0
    tok = l1.rsplit("/", 1)[1]
    assert l1.startswith("https://x.example/i/") and tok not in led.stored_hashes()
    assert hash_token(tok) in led.stored_hashes() and l1 != l2
    assert led.redeem(tok) == "u1" and led.redeem(tok) is None and led.redeem("bogus") is None
    assert led.used("u1") == 1 and led.left("u2") == 2


# ---------------------------------------------------------------- 4 nudge
def test_window_reopen_template_is_valid_and_has_no_false_urgency():
    report = templates.check(templates.load())
    assert report.ok, str(report)
    d = templates.by_key()["chatbot_window_reopen"]
    for v in d.variants:
        assert not nudge.has_false_urgency(v.body), v.key
    ref = nudge.reopen_template("Rahul", "salon ka rate", "hi")
    assert ref.key == "chatbot_window_reopen" and len(ref.params) == 2


def test_urgency_detector_and_window():
    assert nudge.has_false_urgency("Time-sensitive: reply now")
    now = datetime(2026, 1, 5, 10)
    assert nudge.window_closed(now - timedelta(hours=25), now)
    assert not nudge.window_closed(now - timedelta(hours=3), now)
    assert nudge.window_closed(None, now)


def test_template_doc_lists_the_new_template():
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[3] / "docs" / "WHATSAPP_TEMPLATES.md").read_text()
    assert "`friday_window_reopen_v1`" in doc


# ---------------------------------------------------------------- 5 calendar
def ev(i, h1, h2, **kw):
    d = datetime(2026, 1, 5)
    return cal.Event(i, f"E{i}", d.replace(hour=h1), d.replace(hour=h2), **kw)


def test_clash_detector():
    pairs = cal.clashes([ev("a", 10, 11), ev("b", 10, 12), ev("c", 12, 13), ev("d", 9, 18, all_day=True)])
    assert [(a.id, b.id) for a, b in pairs] == [("a", "b")]
    assert cal.clashes([ev("a", 10, 11), ev("c", 11, 12)]) == []


def test_new_invite_only_once():
    events = [ev("a", 10, 11, invited=True), ev("b", 13, 14)]
    assert [e.id for e in cal.new_invites(events, set())] == ["a"]
    assert cal.new_invites(events, {"a"}) == []
    assert len(cal.heads_up(events, set(), "en")) == 1


# ---------------------------------------------------------------- 6 rides
A = rides.Place("Sector 62, Noida", 28.6208, 77.3639)
B = rides.Place("IGI Airport T3", 28.5562, 77.1000)


def test_uber_link_format():
    link = rides.uber_link(A, B)
    u = urlparse(link)
    assert (u.scheme, u.netloc, u.path) == ("https", "m.uber.com", "/looking")
    q = parse_qs(u.query)
    assert json.loads(q["pickup"][0]) == {
        "addressLine1": "Sector 62, Noida", "latitude": 28.6208, "longitude": 77.3639}
    assert json.loads(q["drop[0]"][0])["addressLine1"] == "IGI Airport T3"
    assert " " not in link and "{" not in link and '"' not in link and "," not in u.query.split("&")[0]
    assert unquote(link).count("{") == 2


def test_uber_link_refuses_bad_places():
    assert rides.uber_link(rides.Place("", 1, 1), B) is None
    assert rides.uber_link(A, rides.Place("x", 91, 0)) is None


@pytest.mark.parametrize("app", ["ola", "Rapido", "namma yatri"])
def test_other_apps_get_no_link(app):
    out = rides.ride_reply(app, A, B, "en")
    assert "http" not in out and "won't send" in out


def test_uber_reply_has_link():
    assert "m.uber.com/looking" in rides.ride_reply("uber", A, B)
    assert "http" not in rides.ride_reply("uber", None, None)


# ---------------------------------------------------------------- 8 status
def test_status_text_and_eta():
    assert "3 minutes" in turns.status_text(170, "en")
    assert turns.format_eta(30, "en") == "1 minute"
    assert turns.status_text(None, "en") == copy.line("status_unknown_eta", "en")


async def test_status_sent_once_only_when_slow():
    sent: list[str] = []

    async def send(t):
        sent.append(t)

    async def slow():
        await asyncio.sleep(0.05)
        return 7

    async def fast():
        return 1

    assert await turns.run_with_status(fast(), send, after_s=0.02) == 1 and sent == []
    assert await turns.run_with_status(slow(), send, eta_s=120, after_s=0.01) == 7
    assert len(sent) == 1 and "2" in sent[0]


# ---------------------------------------------------------------- 9 INR
@pytest.mark.parametrize(
    ("v", "out"),
    [(0, "₹0"), (999, "₹999"), (1234, "₹1,234"), (1234567, "₹12,34,567"),
     (Decimal("1499.5"), "₹1,499.50"), ("100000", "₹1,00,000"), (-250, "-₹250")],
)
def test_format_inr(v, out):
    assert pricing.format_inr(v) == out


@pytest.mark.parametrize("t", ["Price $12.99 per month", "pay in USD only", "US card only",
                               "only accepts US cards", "50 dollars"])
def test_usd_routes_refused(t):
    assert pricing.check_route(t, "en") == copy.line("price_usd_refused", "en")


@pytest.mark.parametrize("t", ["₹499 per month", "Rs 1,200 via UPI", "Indian card ok"])
def test_inr_routes_pass(t):
    assert pricing.check_route(t) is None


# ---------------------------------------------------------------- 11 escalation
NOW = datetime(2026, 1, 5, 12)
ME = "+919811100001"


def rem(**kw):
    base = dict(id="r", user_id="u", user_phone=ME, call_target=ME, text="dawai",
                whatsapp_sent_at=NOW - timedelta(minutes=15))
    base.update(kw)
    return escalation.Reminder(**base)


async def allow(_):
    return True


async def deny(_):
    return False


async def test_escalates_only_when_unacknowledged_after_wait_and_enabled():
    d = escalation.decide
    assert await d(rem(), NOW, enabled=True, gate_allows=allow) == escalation.Step.CALL
    assert await d(rem(), NOW, enabled=False, gate_allows=allow) == escalation.Step.SKIP_DISABLED
    assert await d(rem(acknowledged=True), NOW, enabled=True, gate_allows=allow) == escalation.Step.SKIP_ACKED
    assert await d(rem(called=True), NOW, enabled=True, gate_allows=allow) == escalation.Step.SKIP_ALREADY_CALLED
    soon = rem(whatsapp_sent_at=NOW - timedelta(minutes=2))
    assert await d(soon, NOW, enabled=True, gate_allows=allow) == escalation.Step.NONE
    unsent = rem(whatsapp_sent_at=None)
    assert await d(unsent, NOW, enabled=True, gate_allows=allow) == escalation.Step.NONE


async def test_never_calls_anyone_but_the_user_and_obeys_the_gate():
    other = rem(call_target="+919811100002")
    assert await escalation.decide(other, NOW, enabled=True, gate_allows=allow) == escalation.Step.SKIP_NOT_OWN_NUMBER
    assert await escalation.decide(rem(), NOW, enabled=True, gate_allows=deny) == escalation.Step.SKIP_GATE


async def test_callgate_adapter_uses_the_gate_decision():
    class Dec:
        def __init__(self, ok):
            self.allowed = ok

    class Gate:
        def __init__(self, ok):
            self.ok, self.calls = ok, 0

        async def decide(self, req, brief, user, now):
            self.calls += 1
            return Dec(self.ok)

    for ok in (True, False):
        g = Gate(ok)
        chk = escalation.callgate_check(g, lambda r: "req", lambda r, q: "brief", "user", lambda: NOW)
        assert await chk(rem()) is ok and g.calls == 1


# ---------------------------------------------------------------- switches + service wiring
def test_all_parity_switches_default_off_and_read_env(monkeypatch):
    names = ["digest", "invites", "ride_links", "nudges", "status", "inr_only", "escalation"]
    s = Settings(_env_file=None)
    assert [getattr(s, f"parity_{n}") for n in names] == [False] * 7
    monkeypatch.setenv("FRIDAY_PARITY_INVITES", "true")
    assert Settings(_env_file=None).parity_invites is True


async def test_service_ignores_parity_text_while_switches_are_off():
    w = await build_chat()
    try:
        await w.onboard()
        out = await w.say("invites")
        assert all("invite" not in (m.text or "").lower() or "link" not in (m.text or "").lower() for m in out)
    finally:
        await w.c.aclose()


async def test_service_invites_ride_and_inr_when_on():
    w = await build_chat(parity_invites=True, parity_ride_links=True, parity_inr_only=True,
                         public_base_url="https://f.example")
    try:
        await w.onboard()
        out = await w.say("invites")
        assert any("https://f.example/i/" in (m.text or "") for m in out)
        out = await w.say("book an ola cab")
        assert any("won't send" in (m.text or "") or "nahi bhejungi" in (m.text or "") for m in out)
        out = await w.say("this plan is US card only")
        assert any("INR" in (m.text or "") for m in out)
    finally:
        await w.c.aclose()
