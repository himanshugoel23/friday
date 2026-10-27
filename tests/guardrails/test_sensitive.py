# ruff: noqa: E501
"""Codes typed in chat: login OTP only with a pending login; everything else refused (founder
decision 2026-10-27)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from friday.guardrails import Action, Category, Context, Guardrails, GuardrailsConfig
from friday.guardrails.sensitive import PendingLogins, find

NOW = datetime(2026, 10, 27, 8, 41, tzinfo=UTC)


def ctx(user="u1", lang="en", now=NOW):
    return Context(user_id=user, lang=lang, now=now, phase="pre")


class Sink:
    def __init__(self, fail=False):
        self.got: list[tuple[str, str]] = []
        self.fail = fail

    def __call__(self, task_id, code):
        if self.fail:
            raise RuntimeError("worker down")
        self.got.append((task_id, code))


def make(sink=None, **over) -> tuple[Guardrails, Sink]:
    sink = sink or Sink()
    cfg = GuardrailsConfig(new_categories=True, login_otp_in_chat=True, **over)
    return Guardrails(cfg, otp_sink=sink), sink


# ------------------------------------------------------------------ accepted: login code with a pending login
@pytest.mark.parametrize("text,code", [
    ("4821", "4821"), ("482913", "482913"), ("otp 4821", "4821"), ("otp hai 4821", "4821"),
    ("OTP is 4821", "4821"), ("4 8 2 1", "4821"), ("४८२१", "4821"), ("ओटीपी है ४८२१", "4821"),
    ("4821 hai", "4821"), ("code: 48-21", "4821"), ("the otp is 123456", "123456"), ("1234 5678", "12345678"),
])
def test_login_code_is_accepted_when_a_login_is_pending(text, code):
    g, sink = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check(text, ctx())
    assert d.category == Category.SENSITIVE_CODES and d.route == "browser_worker"
    assert d.action == Action.ALLOW and d.reply
    assert sink.got == [("task-1", code)]


def test_the_code_never_appears_in_the_decision_the_audit_or_the_log():
    g, _ = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check("otp hai 482913", ctx())
    for blob in (repr(d), str(d.audit), str(list(g.log)), repr(find("otp hai 482913"))):
        assert "482913" not in blob
    assert d.audit["snippet"] == ""


def test_single_use():
    g, sink = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    assert g.check("4821", ctx()).route == "browser_worker"
    again = g.check("4821", ctx())
    assert again.route is None and len(sink.got) == 1


def test_expires_after_five_minutes():
    g, sink = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check("otp 4821", ctx(now=NOW + timedelta(minutes=5, seconds=1)))
    assert d.route is None and sink.got == []
    assert d.action == Action.REFUSE  # explicit "otp" with no live login: refused, not relayed


def test_only_for_the_user_who_started_the_login():
    g, sink = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check("otp 4821", ctx(user="u2"))
    assert d.route is None and sink.got == [] and d.action == Action.REFUSE
    assert g.check("4821", ctx(user="u1")).route == "browser_worker"


def test_a_failing_worker_keeps_the_login_pending_and_tells_the_user():
    g, _ = make(sink=Sink(fail=True))
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check("4821", ctx())
    assert d.route is None and d.reply and d.rule == "sensitive_codes.sink_failed"
    assert g.pending.has_pending("u1", NOW)


# ------------------------------------------------------------------ not accepted without a pending login
def test_unsolicited_digit_strings_are_not_otps():
    g, sink = make()
    for text in ("4821", "5000", "123456", "४८२१", "mera order 4821 kab aayega", "my order number is 48215"):
        d = g.check(text, ctx())
        assert d.category == Category.IN_SCOPE and not d.handled, text
    assert sink.got == []


def test_otp_with_digits_but_no_login_is_refused_and_never_relayed():
    g, sink = make()
    for text in ("otp hai 4821", "the otp is 4821", "otp 4 8 2 1", "ओटीपी है ४८२१"):
        d = g.check(text, ctx())
        assert d.category == Category.SENSITIVE_CODES and d.action == Action.REFUSE, text
        assert "login" in d.reply.lower()
    assert sink.got == []


def test_login_otp_in_chat_switch_off_never_relays_even_with_a_pending_login():
    sink = Sink()
    g = Guardrails(GuardrailsConfig(new_categories=True), otp_sink=sink)  # login_otp_in_chat off
    g.begin_login("u1", "zomato", "task-1", NOW)
    d = g.check("otp hai 4821", ctx())
    assert d.route is None and sink.got == []


def test_a_bare_code_goes_through_with_no_sink_configured():
    g = Guardrails(GuardrailsConfig(new_categories=True, login_otp_in_chat=True))
    g.begin_login("u1", "zomato", "task-1", NOW)
    assert g.check("4821", ctx()).route is None


# ------------------------------------------------------------------ always refused, pending login or not
@pytest.mark.parametrize("text,kind", [
    ("bank ka otp 482913 hai", "payment_code"),
    ("transaction otp 662190", "payment_code"),
    ("my UPI OTP is 123456", "payment_code"),
    ("card otp 998877", "payment_code"),
    ("aadhaar otp is 553201", "aadhaar_otp"),
    ("आधार ओटीपी 553201", "aadhaar_otp"),
    ("upi pin 4821", "upi_pin"),
    ("mera atm pin 1234 hai", "upi_pin"),
    ("upi pin hai ४८२१", "upi_pin"),
    ("cvv 123", "cvv"),
    ("c v v 123", "cvv"),
    ("my card number is 4111 1111 1111 1111", "card_number"),
    ("card no 4111-1111-1111-1111", "card_number"),
    ("4111111111111111", "card_number"),
    ("mera password hai Rahul@1234", "password"),
    ("my password is hunter42", "password"),
    ("password: abc12345", "password"),
])
def test_never_accepted_even_with_a_pending_login(text, kind):
    g, sink = make()
    g.begin_login("u1", "zomato", "task-1", NOW)
    assert find(text).kind == kind
    d = g.check(text, ctx())
    assert d.category == Category.SENSITIVE_CODES and d.action == Action.REFUSE and d.route is None
    assert sink.got == []
    assert g.pending.has_pending("u1", NOW)  # the refusal does not consume the pending login


def test_refusals_point_to_the_safe_place():
    g, _ = make()
    assert "secure link" in g.check("my password is hunter42", ctx()).reply
    assert "own bank or UPI app" in g.check("upi pin 4821", ctx()).reply
    assert "secure" in g.check("mera password hai Rahul@1234", ctx(lang="hinglish")).reply.lower()


def test_a_forgotten_password_question_is_not_a_password():
    for text in ("I forgot my password for the bank app, how do I reset it", "password kya hai mera gmail ka"):
        assert find(text) is None


def test_ordinary_numbers_are_not_cards():
    for text in ("mera order 4821 kab aayega", "call 9811100001", "EMI 12000 hai", "invoice 20261027"):
        assert find(text) is None, text


# ------------------------------------------------------------------ redaction of the stored copy
def test_stored_text_is_redacted_for_secrets_and_for_codes_when_a_login_is_pending():
    g, _ = make()
    assert g.redact_stored("my password is hunter42", "u1", NOW)
    assert g.redact_stored("cvv 123", "u1", NOW)
    assert g.redact_stored("otp hai 4821", "u1", NOW)
    assert not g.redact_stored("4821", "u1", NOW)  # a bare number, no login pending: kept
    g.begin_login("u1", "zomato", "t", NOW)
    assert g.redact_stored("4821", "u1", NOW)
    assert not g.redact_stored("mummy ko call karo", "u1", NOW)
    assert not Guardrails(GuardrailsConfig()).redact_stored("my password is hunter42", "u1", NOW)


def test_pending_logins_registry():
    p = PendingLogins()
    p.start("u1", "Zomato", "t1", NOW)
    p.start("u1", "swiggy", "t2", NOW + timedelta(minutes=1))
    assert p.has_pending("u1", NOW)
    assert p.claim("u1", NOW).task_id == "t2"  # the newest
    assert p.claim("u1", NOW).task_id == "t1"
    assert p.claim("u1", NOW) is None
    p.start("u1", "zomato", "t3", NOW)
    p.cancel("u1")
    assert not p.has_pending("u1", NOW)
    p.start("u1", "zomato", "t4", NOW)
    assert p.claim("u1", NOW + timedelta(minutes=6)) is None
