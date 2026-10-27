# ruff: noqa: E501
"""A LOGIN code typed in the WhatsApp chat (founder decision 2026-10-27): accepted only while Friday
itself started that login for that user, single use, ~5 min, straight to the browser worker, never
the LLM, stored chat text redacted at once. Bank / payment / UPI PIN / card / CVV / Aadhaar codes and
passwords are refused (pointing to the secure page / the user's own app). Fakes only."""

from __future__ import annotations

import pytest

from friday.api.runtime import Runtime
from friday.connectors import login_copy
from friday.connectors.flow import register_browser_handler
from friday.connectors.otp import (
    LOGIN_OTP,
    PendingLoginRegistry,
    chat_secret_kind,
    classify_chat_secret,
    extract_login_code,
)
from tests.chatbot.conftest import TESTER, TESTER2, build_chat


@pytest.fixture(autouse=True)
def _clean_handler():
    register_browser_handler(None)
    yield
    register_browser_handler(None)


def on(tmp_path, **over):
    return {"browser_enabled": True, "browser_enabled_users": ["*"], "browser_backend": "fake",
            "browser_vault_dir": str(tmp_path / "v"), "browser_credentials_dir": str(tmp_path / "c"),
            "browser_audit_file": str(tmp_path / "a.jsonl"), "browser_login_otp_in_chat": True, **over}


# ------------------------------------------------------------------ the pure classifier
@pytest.mark.parametrize("text", [
    "4821", "482193", "48210000", " 4821 ", "otp hai 4821", "OTP: 4821", "mera otp 4821 hai",
    "my otp is 4821", "code is 4821", "otp4821", "४८२१", "४८ २१", "ओटीपी ४८२१ है", "٤٨٢١", "４８２１",
    "4 8 2 1", "48-21", "48.21", "482 193", "4​8​2​1", "OTP  4  8  2  1  hai",
    "four eight two one", "ek do teen char", "zomato otp 4821",
])
def test_login_code_shapes_are_accepted_with_a_pending_login(text):
    v = classify_chat_secret(text, login_site="zomato")
    assert v.kind == LOGIN_OTP and v.code.isdigit() and 4 <= len(v.code) <= 8


@pytest.mark.parametrize("text", [
    "4821 aur 1234", "hello", "book a table for 4", "meri 4821 rupay ki bill", "123", "123456789",
    "call me at 9811100001 today", "otp kya hai", "kal 5 baje 4 log aayenge", "", "   ",
    "x" * 90 + "4821", "do char din baad",
])
def test_not_a_code_stays_a_normal_message(text):
    assert classify_chat_secret(text, login_site="zomato").kind != LOGIN_OTP
    assert extract_login_code(text, site="zomato") is None


def test_no_pending_login_means_never_a_code():
    for text in ("4821", "otp hai 4821", "४८२१"):
        assert classify_chat_secret(text).kind == "none"
        assert chat_secret_kind(text, login_pending=False) == "none"
    assert chat_secret_kind("4821", login_pending=True) == LOGIN_OTP


@pytest.mark.parametrize("text,kind", [
    ("hdfc bank otp 4821", "refuse_payment_otp"), ("my UPI otp is 482193", "refuse_payment_otp"),
    ("payment otp ४८२१", "refuse_payment_otp"), ("transaction code 4821", "refuse_payment_otp"),
    ("upi pin 1234", "refuse_upi_pin"), ("UPI-PIN ४८२१", "refuse_upi_pin"), ("my mpin 1234", "refuse_upi_pin"),
    ("atm pin 4821", "refuse_upi_pin"),
    ("cvv 123", "refuse_card"), ("CVV: ४८२", "refuse_card"), ("card number 4111 1111 1111 1111", "refuse_card"),
    ("4111111111111111", "refuse_card"), ("4111-1111-1111-1111", "refuse_card"), ("5555 5555 5555 4444 exp 12/30", "refuse_card"),
    ("aadhaar otp 123456", "refuse_aadhaar"), ("आधार otp 123456", "refuse_aadhaar"), ("my aadhar is 1234 5678 9012", "refuse_aadhaar"),
    ("my password is Hunter2", "refuse_password"), ("mera password abc123 hai", "refuse_password"),
    ("password: Zomato@123", "refuse_password"), ("पासवर्ड abc123", "refuse_password"), ("pwd=xyz987", "refuse_password"),
])
def test_secrets_are_refused_with_or_without_a_pending_login(text, kind):
    assert classify_chat_secret(text, login_site="zomato").kind == kind
    assert classify_chat_secret(text).kind == kind
    assert classify_chat_secret(text, login_site="zomato").code == ""


def test_ordinary_talk_about_cards_and_passwords_is_not_refused():
    for text in ("forgot password", "my card savings", "which card is best for fuel", "password manager kya hai",
                 "hdfc card ending 4821 se kitna bacha"):
        assert classify_chat_secret(text).kind == "none", text


def test_verdict_never_prints_or_pickles_the_code():
    import pickle

    v = classify_chat_secret("4821", login_site="zomato")
    assert "4821" not in repr(v) and "4821" not in str(v) and "4821" not in f"{v!r}"
    with pytest.raises(TypeError):
        pickle.dumps(v)


def test_pending_registry_is_single_use_and_expires():
    t = [0.0]
    reg = PendingLoginRegistry(ttl_seconds=300, clock=lambda: t[0])
    reg.expect("u1", "Zomato", "task1")
    assert reg.peek("u2") is None and reg.peek("u1").site == "zomato"
    t[0] = 299
    assert reg.consume("u1").task_id == "task1" and reg.consume("u1") is None
    reg.expect("u1", "zomato", "task2")
    t[0] = 700
    assert reg.peek("u1") is None  # five minutes are over
    reg.expect("u1", "zomato", "task3")
    assert reg.clear_task("task3") == 1 and reg.peek("u1") is None
    assert "task" not in repr(reg)


# ------------------------------------------------------------------ the chat pipeline
async def _rows(w, user):
    return [m.text for m in await w.c.repos.messages.list_for_user(user.id, limit=100)
            if m.direction.value == "inbound"]


async def test_off_by_default_a_code_in_chat_is_just_a_message(tmp_path):
    w = await build_chat(**on(tmp_path, browser_login_otp_in_chat=False))
    try:
        await w.onboard()
        stack = w.pipeline.browser
        assert stack.pending_logins is None
        await w.say("4821")
        assert stack.otp.take("task1") is None and "4821" in w.brain.seen
    finally:
        await w.c.aclose()


async def test_code_goes_to_the_worker_once_never_to_the_llm_and_is_stored_redacted(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.pending_logins.expect(user.id, "zomato", "task1")
        out = await w.say("otp hai 4821")
        assert out and "4821" not in " ".join(m.text or "" for m in out)  # never echoed back
        assert stack.otp.take("task1") == "4821"  # the browser worker gets it, once
        assert stack.otp.take("task1") is None
        assert stack.pending_logins.peek(user.id) is None  # single use
        assert not any("4821" in (s or "") for s in w.brain.seen)  # never the LLM
        assert not any("4821" in (t or "") for t in await _rows(w, user))  # stored text redacted
        assert "[redacted]" in await _rows(w, user)
        assert "4821" not in (tmp_path / "a.jsonl").read_text() if (tmp_path / "a.jsonl").exists() else True
        out = await w.say("4821")  # a second code with nothing pending: an ordinary message
        assert stack.otp.take("task1") is None and "4821" in w.brain.seen
    finally:
        await w.c.aclose()


@pytest.mark.parametrize("text", ["४८२१", "४८ २१", "4 8 2 1", "ओटीपी ४८२१ है", "mera otp 4821 hai", "ek do teen char"])
async def test_evasions_are_still_routed_and_redacted(tmp_path, text):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.pending_logins.expect(user.id, "zomato", "t")
        await w.say(text)
        got = stack.otp.take("t")
        assert got in {"4821", "1234"}
        assert text not in await _rows(w, user)
        assert w.brain.seen.count(text) == 0
    finally:
        await w.c.aclose()


async def test_code_expires_after_five_minutes(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        now = [1000.0]
        stack.pending_logins._clock = lambda: now[0]
        stack.pending_logins.expect(user.id, "zomato", "t")
        now[0] += 301
        await w.say("4821")
        assert stack.otp.take("t") is None and "4821" in w.brain.seen  # late: an ordinary message
    finally:
        await w.c.aclose()


async def test_a_code_from_another_user_is_not_used(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        await w.onboard("Asha", TESTER2)
        user = await w.user()
        stack = w.pipeline.browser
        stack.pending_logins.expect(user.id, "zomato", "tA")
        await w.say("4821", TESTER2)  # the other tester has no login pending
        assert stack.otp.take("tA") is None
        assert stack.pending_logins.peek(user.id) is not None
        await w.say("4821", TESTER)
        assert stack.otp.take("tA") == "4821"
    finally:
        await w.c.aclose()


@pytest.mark.parametrize("text,kind", [
    ("hdfc bank otp 4821", "refuse_payment_otp"), ("upi pin 1234", "refuse_upi_pin"), ("cvv 123", "refuse_card"),
    ("4111 1111 1111 1111", "refuse_card"), ("aadhaar otp 123456", "refuse_aadhaar"), ("my password is Hunter2", "refuse_password"),
])
async def test_refused_secrets_get_a_pointer_and_are_stored_redacted(tmp_path, text, kind):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.pending_logins.expect(user.id, "zomato", "t")
        out = await w.say(text)
        assert [m.text for m in out] == [login_copy.line(login_copy.REFUSAL_LINE[kind], "hi")]
        assert stack.otp.take("t") is None  # never relayed
        assert stack.pending_logins.peek(user.id) is not None  # the real login code is still wanted
        assert text not in await _rows(w, user) and text not in w.brain.seen
    finally:
        await w.c.aclose()


async def test_refusals_work_without_a_pending_login_too(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        out = await w.say("my password is Hunter2")
        assert out and "Hunter2" not in " ".join(m.text or "" for m in out)
        assert "my password is Hunter2" not in await _rows(w, user)
        assert not any("Hunter2" in (s or "") for s in w.brain.seen)
    finally:
        await w.c.aclose()


async def test_a_user_not_named_for_the_browser_is_not_touched(tmp_path):
    w = await build_chat(**on(tmp_path, browser_enabled_users=["someone-else"]))
    try:
        await w.onboard()
        user = await w.user()
        w.pipeline.browser.pending_logins.expect(user.id, "zomato", "t")
        await w.say("4821")
        assert w.pipeline.browser.otp.take("t") is None and "4821" in w.brain.seen
    finally:
        await w.c.aclose()


async def test_webhook_path_handles_the_code_before_the_queue_sees_it(tmp_path):
    w = await build_chat(**on(tmp_path))
    try:
        await w.onboard()
        user = await w.user()
        rt = Runtime(w.c, fast_pin_hash=True)
        stack = rt.pipeline.browser
        queue = w.c.get("job_queue")
        stack.pending_logins.expect(user.id, "zomato", "t")
        msg = w.channel.make_inbound(TESTER, "४८२१").model_copy(update={"provider_message_id": "wamid.C1"})
        depth = await queue.depth()
        assert await rt.accept_inbound(msg)
        assert await queue.depth() == depth  # nothing carrying the code was queued
        assert stack.otp.take("t") == "4821"
        assert not any("४८२१" in (t or "") for t in await _rows(w, user))
        ordinary = w.channel.make_inbound(TESTER, "hello").model_copy(update={"provider_message_id": "wamid.C2"})
        assert await rt.accept_inbound(ordinary) and await queue.depth() == depth + 1
    finally:
        await w.c.aclose()


async def test_the_flow_registers_the_pending_login_and_hints_at_chat():
    """BrowserFlow's login step marks the login pending (with the chat hint) and the end clears it."""
    from friday.connectors.flow import BrowserFlow, Outgoing, Phase, TaskState
    from friday.connectors.otp import OneTimeOtpChannel
    from friday.connectors.registry import ConnectorRegistry
    from friday.connectors.sites.adapters import Profile

    sent: list[Outgoing] = []

    async def send(o: Outgoing) -> None:
        sent.append(o)

    class Sessions:
        async def open(self, *a, **k):
            return object()

        async def close(self, task_id):
            return None

    class Adapter:
        site_name = "Zomato"

        def __init__(self, ctx):
            self.ctx = ctx

    def make(pending):
        return BrowserFlow(send=send, registry=ConnectorRegistry(), sessions=Sessions(),
                           otp=OneTimeOtpChannel(), profile=lambda uid: Profile(),
                           login_link=lambda t: f"https://x.test/o/{t}", base_urls={},
                           enabled=lambda: True, adapters={"zomato.food": Adapter}, pending_logins=pending)

    pending = PendingLoginRegistry()
    flow = make(pending)
    st = TaskState(task_id="t1", user_id="u1", connector="zomato.food", lang="en")
    flow._save(st, Phase.running)  # noqa: SLF001
    adapter = await flow._open(st)  # noqa: SLF001
    await adapter.ctx.on_code_wait()
    assert pending.peek("u1").task_id == "t1" and pending.peek("u1").site == "zomato"
    assert "https://x.test/o/t1" in sent[0].text and login_copy.line("chat_hint", "en") in sent[0].text
    await flow._finish(st, Phase.done, "outcome", "ok")  # noqa: SLF001
    assert pending.peek("u1") is None
    # switch off: no registry, no hint, the old wording only
    sent.clear()
    flow2 = make(None)
    st2 = TaskState(task_id="t2", user_id="u2", connector="zomato.food", lang="en")
    flow2._save(st2, Phase.running)  # noqa: SLF001
    await (await flow2._open(st2)).ctx.on_code_wait()  # noqa: SLF001
    assert login_copy.line("chat_hint", "en") not in sent[0].text


async def test_forget_and_delete_everything_drop_a_pending_login_and_leftover_logins(tmp_path):
    w = await build_chat(**on(tmp_path))  # saved logins switch is OFF, but a login was saved before
    try:
        await w.onboard()
        user = await w.user()
        stack = w.pipeline.browser
        stack.cred_vault.save(user.id, "zepto", "u@example.test", "Pw-Test-12345", hosts=["www.zeptonow.com"], consent=True)
        stack.pending_logins.expect(user.id, "zomato", "t")
        stack.otp.submit("t", "4821")
        await w.pipeline.delete_everything(user)
        assert stack.cred_vault.saved_logins(user.id) == []  # deleted although the switch is off
        assert stack.pending_logins.peek(user.id) is None and stack.otp.take("t") is None
    finally:
        await w.c.aclose()


def test_every_login_line_exists_in_both_languages_and_is_pending_approval():
    assert login_copy.PENDING_FOUNDER_APPROVAL
    for key, row in login_copy.LINES.items():
        assert set(row) == {"en", "hi"}, key
    for key in login_copy.REFUSAL_LINE.values():
        assert key in login_copy.LINES
    # the login-code hint and the refusals never ask for a bank/payment code
    assert "never" in login_copy.LINES["chat_hint"]["en"].lower()
    assert len(login_copy.all_ids()) == len(login_copy.LINES)
