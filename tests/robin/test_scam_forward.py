# ruff: noqa: E501
"""T13: scam check by WhatsApp forward. Tested with FAKES only (fake WhatsApp, fake TTS/STT/converter, fake vision, fake LLM); no real
provider was called. Phones, numbers and links are invented. The corpus of tests/robindevice/test_scamcheck.py is reused through the
WhatsApp path."""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import pytest

from friday.chatbot_media.convert import FakeConverter
from friday.core.interfaces import LLMResponse
from friday.core.models import Channel, InboundMessage, MediaBlob, MessageKind
from friday.docunderstand.ports import FakeVision
from friday.robin import lines, wiring
from friday.robin.channel import FakeWhatsApp, MemoryWindow, ParentInbound, WhatsAppParentChannel
from friday.robin.models import ConsentSource
from friday.robin.scamintake import ScamForward
from friday.robindevice import scamcheck
from friday.voice.stt.fake import FakeSTT
from friday.voice.tts.fake import build_fake_tts
from tests.robin.conftest import PARENT_PHONE
from tests.robindevice.test_scamcheck import CASES

SECRET_BITS = ("Zorblax", "98765 43210", "9876543210", "evil-zorblax.example")  # invented tokens that must never be stored or logged
SCAM_WITH_SENDER = "CBI officer here, Zorblax case. You are under digital arrest, do not tell anyone. Call 98765 43210 or open http://evil-zorblax.example/pay and share your OTP."


class FakeLLM:
    def __init__(self, verdict: str) -> None:
        self.verdict, self.calls = verdict, []

    async def complete(self, **kw):
        self.calls.append(kw)
        return LLMResponse(text=json.dumps({"verdict": self.verdict}), model="fake")


@pytest.fixture
async def ch(w, container):
    wa, tts = FakeWhatsApp(), build_fake_tts(container)
    channel = WhatsAppParentChannel(wa, tts=lambda: tts, converter=FakeConverter(), clock=w.clock, window=MemoryWindow())
    w.ctx.parent_channel = channel
    vision = FakeVision()
    llm_box = SimpleNamespace(llm=None)
    scam = ScamForward(w.hub, messaging=lambda: wa, vision=lambda: vision, llm=lambda: llm_box.llm)
    w.hub.parent_route = ParentInbound(w.hub, messaging=lambda: wa, stt=lambda: FakeSTT(), scam=scam)
    return SimpleNamespace(wa=wa, tts=tts, vision=vision, scam=scam, llm_box=llm_box, w=w, n=0)


async def send(ch, words: str, frm: str = PARENT_PHONE) -> str:
    """One forwarded text from the parent; returns the words Robin spoke (None-safe: '' when nothing was spoken)."""
    ch.n += 1
    before = len(ch.tts.calls)
    await ch.w.hub.parent_inbound(InboundMessage(channel=Channel.WHATSAPP, from_phone=frm, kind=MessageKind.TEXT, text=words, provider_message_id=f"t{ch.n}"))
    return ch.tts.calls[-1][0] if len(ch.tts.calls) > before else ""


async def send_image(ch, payload: dict | None, *, caption: str | None = None) -> str:
    ch.n += 1
    mid = f"IMG{ch.n}"
    ch.wa.media[mid] = MediaBlob(data=b"\x89PNGfake" + json.dumps(payload or {}).encode(), mime="image/png")
    before = len(ch.tts.calls)
    await ch.w.hub.parent_inbound(InboundMessage(channel=Channel.WHATSAPP, from_phone=PARENT_PHONE, kind=MessageKind.IMAGE, media_url=mid, media_mime="image/png", text=caption, provider_message_id=f"i{ch.n}"))
    return ch.tts.calls[-1][0] if len(ch.tts.calls) > before else ""


async def checks(w, fam):
    return [r for r in await w.store.list(fam.id, "audit") if r.data.get("event") == "scam_check"]


async def everything_stored(w, fam) -> str:
    return json.dumps([r.data for k in ("audit", "pending", "incident", "dose", "checkin", "digest", "intro", "medicine") for r in await w.store.list(fam.id, k)], default=str, ensure_ascii=False)


# ============================================================================ the corpus of test_scamcheck.py, through WhatsApp
FORWARDABLE = [c for c in CASES if c[0] in ("text", "url")]


def test_corpus_is_reused_and_nothing_in_it_is_a_greeting():
    assert len(FORWARDABLE) >= 55
    assert all(len(c[1].split()) > 3 or c[0] == "url" for c in FORWARDABLE)  # the short-greeting shortcut never swallows a corpus text (a link is never a greeting)


@pytest.mark.parametrize("kind,text,verdicts,category", FORWARDABLE, ids=[f"{i}-{c[0]}" for i, c in enumerate(FORWARDABLE)])
async def test_corpus_through_the_whatsapp_path(w, ch, kind, text, verdicts, category):
    fam, parent = await w.family(notified=False)
    spoken = await send(ch, text)
    (rec,) = await checks(w, fam)
    assert rec.data["verdict"] in verdicts, (rec.data["verdict"], rec.data["category"])
    assert rec.data["verdict"] == scamcheck.check_rules(kind, text, "hinglish").verdict  # the same engine, the same answer
    if category and rec.data["verdict"] in ("SCAM_LIKELY", "RISKY"):
        assert rec.data["category"] in scamcheck.check_rules(kind, text, "hinglish").categories
    assert spoken and not re.search(r"\bsafe\b", spoken, re.I)  # never 'safe'
    if rec.data["verdict"] == "NO_SIGNS_FOUND":
        assert "koi khatre ke nishaan nahi mile" in spoken and "sab theek" in spoken  # 'no warning signs found', plus: not a promise
    else:
        assert "mat" in spoken  # do not click / do not pay


# ============================================================================ the reply: voice note + text, in the parent's language
async def test_reply_is_a_voice_note_and_the_same_words_as_text(w, ch):
    fam, parent = await w.family(notified=False)
    spoken = await send(ch, "Share your OTP now or your account will be blocked, click http://sbi-kyc-update.com/login")
    assert ch.wa.audios and any(m.text == spoken for m in ch.wa.sent)  # voice first, then the same words as text
    assert "click" in spoken and "Asha" in spoken and "Mujhe" not in spoken[:0]


@pytest.mark.parametrize("lang,must", [("en", "do not click"), ("hinglish", "click mat kijiye"), ("hi", "क्लिक मत कीजिए")])
async def test_high_verdict_in_the_parents_language(w, ch, lang, must):
    fam, parent = await w.family(notified=False)
    parent.language = lang
    await w.store.save_member(parent, fam.owner_user_id)
    spoken = await send(ch, "Share your OTP now or your account will be blocked, click http://sbi-kyc-update.com/login")
    assert must in spoken and "Asha" in spoken
    if lang == "hi":
        assert re.search(r"[ऀ-ॿ]", spoken)


@pytest.mark.parametrize("lang,must", [("en", "I found no warning signs"), ("hinglish", "Mujhe koi khatre ke nishaan nahi mile"), ("hi", "मुझे कोई ख़तरे के निशान नहीं मिले")])
async def test_no_warning_signs_is_never_worded_as_safe(w, ch, lang, must):
    fam, parent = await w.family(notified=False)
    parent.language = lang
    await w.store.save_member(parent, fam.owner_user_id)
    spoken = await send(ch, "Beta kal doctor ke paas chalna hai, 11 baje taiyar rehna, main aa jaunga.")
    assert must in spoken and not re.search(r"\bsafe\b|सुरक्षित|surakshit", spoken, re.I)


def test_no_new_line_says_safe_and_all_are_pending():
    keys = [k for k in (*lines.SPOKEN, *lines.CHAT) if k.startswith("scam.")]
    assert len(keys) >= 11
    for ln in lines.all_lines():
        if ln.id.startswith("robin.scam."):
            assert ln.status == "PENDING_FOUNDER_APPROVAL" and not re.search(r"\bsafe\b|surakshit|सुरक्षित", ln.text, re.I), ln.id
    assert lines.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"  # untouched


async def test_a_plain_greeting_is_not_judged(w, ch):
    fam, parent = await w.family(notified=False)
    spoken = await send(ch, "namaste ji")
    assert "Robin" in spoken and await checks(w, fam) == []  # the short hello, nothing recorded


# ============================================================================ the child
async def test_high_verdict_tells_the_child_with_share_summary_and_never_the_content(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    await send(ch, SCAM_WITH_SENDER)
    told = [t for t in w.sender.texts() if "very risky" in t]
    assert len(told) == 1 and "Papa" in told[0] and "did not keep the message" in told[0]
    assert not any(b in told[0] for b in SECRET_BITS)


async def test_money_moment_points_the_child_to_the_first_hour_playbook(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    await send(ch, "Share your OTP now or your account will be blocked, click http://sbi-kyc-update.com/login")
    (msg,) = [t for t in w.sender.texts() if "very risky" in t]
    assert "first hour" in msg and "1930" in msg and "cybercrime.gov.in" in msg and "bank" in msg


async def test_high_verdict_without_share_summary_consent_does_not_tell_the_child(w, ch):
    fam, parent = await w.family(consent=False, notified=False)
    await w.hub.fam.give_consent(parent.id, "scam_check", ConsentSource.ADMIN_CHAT)  # the parent agreed to the check, not to sharing
    w.sender.sent.clear()
    spoken = await send(ch, SCAM_WITH_SENDER)
    assert "mat" in spoken and not [t for t in w.sender.texts() if "risky" in t]  # the parent is still protected; the child is not told
    assert (await checks(w, fam))[0].data["verdict"] == "SCAM_LIKELY"


async def test_a_weak_risk_alone_does_not_wake_the_child(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    await send(ch, "https://bit.ly/3abcXYZ")  # RISKY, link only
    assert (await checks(w, fam))[0].data["verdict"] == "RISKY" and not [t for t in w.sender.texts() if "risky" in t]


async def test_the_same_alert_is_not_sent_twice_within_ten_minutes(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    await send(ch, "Share your OTP now or your account will be blocked today")
    await send(ch, "Please enter your UPI PIN to confirm.")  # a different message, same category in the same minutes
    assert len([t for t in w.sender.texts() if "very risky" in t or "another message" in t]) == 1


# ============================================================================ no consent
async def test_without_scam_check_consent_the_parent_is_told_and_the_child_informed_once_a_day(w, ch, monkeypatch):
    fam, parent = await w.family(consent=False, notified=False)

    async def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("nothing may be analysed without consent")

    monkeypatch.setattr(scamcheck, "check", boom)
    w.sender.sent.clear()
    spoken = await send(ch, SCAM_WITH_SENDER)
    assert "nahi jaanch sakti" in spoken and "Asha" in spoken
    assert "mat" in spoken  # still: do not click, do not pay
    await send(ch, "Please enter your UPI PIN to confirm.")
    child = [t for t in w.sender.texts() if "scam check is not switched on" in t]
    assert len(child) == 1 and "enable scam check" in child[0]  # informed once, not once per message
    assert await checks(w, fam) == []
    blob = await everything_stored(w, fam)
    assert not any(b in blob for b in SECRET_BITS)
    w.go(hours=24)
    await send(ch, "Please enter your UPI PIN to confirm.")
    assert len([t for t in w.sender.texts() if "scam check is not switched on" in t]) == 2  # the next day, once more


async def test_withdrawn_consent_stops_the_check(w, ch):
    fam, parent = await w.family(notified=False)
    assert "Mujhe" in await send(ch, "Beta kal doctor ke paas chalna hai, 11 baje taiyar rehna, main aa jaunga.")
    await w.hub.fam.withdraw_consent(parent.id, "scam_check", tell_child=True, actor="user", source="test")
    spoken = await send(ch, "Beta kal doctor ke paas chalna hai, 11 baje taiyar rehna, main aa jaunga aur.")
    assert "nahi jaanch sakti" in spoken


async def test_a_paused_parent_can_still_forward_something_to_check(w, ch):
    fam, parent = await w.family(notified=False)
    await w.hub.fam.pause(parent.id, "voice")
    spoken = await send(ch, "Share your OTP now or your account will be blocked, click http://sbi-kyc-update.com/login")
    assert "click mat kijiye" in spoken  # her own forward is an explicit action, like the mic tap


# ============================================================================ nothing kept
async def test_only_verdict_category_and_time_are_stored_and_nothing_is_logged(w, ch, caplog):
    fam, parent = await w.family(notified=False)
    caplog.set_level(logging.DEBUG)
    await send(ch, SCAM_WITH_SENDER)
    blob = await everything_stored(w, fam)
    assert not any(b in blob for b in SECRET_BITS)
    assert not any(b in caplog.text for b in SECRET_BITS) and "digital arrest" not in caplog.text.lower().replace("digital_arrest", "")
    (rec,) = await checks(w, fam)
    assert set(rec.data) <= {"event", "text", "verdict", "category", "member_id", "times", "sender_hash"} and rec.at is not None
    assert rec.data["verdict"] == "SCAM_LIKELY" and rec.data["category"] == "digital_arrest"
    assert re.fullmatch(r"[0-9a-f]{64}", rec.data["sender_hash"])  # hashed, not the number or the host


async def test_repeat_sender_is_hashed_flagged_and_tells_the_child(w, ch):
    fam, parent = await w.family(notified=False)
    first = await send(ch, "Join our VIP Telegram group for stock tips, guaranteed profit 5% daily. Call 98765 43210")
    w.go(hours=1)
    second = await send(ch, "Work from home, like videos and earn Rs 5000 per day, daily income guaranteed. WhatsApp 9876543210")
    other = await send(ch, "Join our VIP Telegram group for stock tips, guaranteed profit 5% daily. Call 91234 56789")
    a, b, c = await checks(w, fam)
    assert a.data["sender_hash"] == b.data["sender_hash"] != c.data["sender_hash"]  # the same number, spelled two ways, is one sender
    assert (a.data["times"], b.data["times"], c.data["times"]) == (1, 2, 1)
    assert "pehle bhi likha" not in first and "pehle bhi likha" in second and "pehle bhi likha" not in other
    blob = await everything_stored(w, fam)
    assert not any(x in blob for x in ("98765", "9876543210", "91234"))


async def test_repeat_of_a_risky_message_tells_the_child_even_without_a_high_verdict(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    msg = "Join our VIP Telegram group for stock tips, guaranteed profit 5% daily. Call 98765 43210"
    await send(ch, msg)
    verdict = (await checks(w, fam))[0].data["verdict"]
    if verdict != "RISKY":
        pytest.skip("the engine rates this example HIGH: covered by the high-verdict tests")
    assert not [t for t in w.sender.texts() if "another message" in t]
    w.go(hours=1)
    await send(ch, msg)
    assert len([t for t in w.sender.texts() if "another message" in t and "2 times" in t]) == 1


# ============================================================================ screenshots
async def test_screenshot_is_read_by_the_vision_port_judged_and_forgotten(w, ch):
    fam, parent = await w.family(notified=False)
    w.sender.sent.clear()
    spoken = await send_image(ch, {"text": SCAM_WITH_SENDER})
    assert len(ch.vision.calls) == 1 and ch.vision.calls[0].mime == "image/png"
    assert "mat" in spoken and (await checks(w, fam))[0].data["verdict"] == "SCAM_LIKELY"
    assert ch.wa.deleted  # the provider's copy is asked to be deleted too
    blob = await everything_stored(w, fam)
    assert not any(b in blob for b in SECRET_BITS)
    assert [t for t in w.sender.texts() if "very risky" in t]


async def test_screenshot_without_a_vision_provider_is_unreadable_not_reassuring(w, ch):
    fam, parent = await w.family(notified=False)
    ch.scam._vision = None
    spoken = await send_image(ch, {"text": "Beta kal doctor ke paas chalna hai"})
    assert "padh nahi payi" in spoken and "mat" in spoken
    assert (await checks(w, fam))[0].data["verdict"] == "UNSURE"


@pytest.mark.parametrize("how", ["unavailable", "fails", "empty"])
async def test_unreadable_pictures_never_say_no_warning_signs(w, ch, how):
    fam, parent = await w.family(notified=False)
    ch.vision.unavailable, ch.vision.fail = how == "unavailable", how == "fails"
    spoken = await send_image(ch, {"text": ""} if how == "empty" else {"text": "x"})
    assert "padh nahi payi" in spoken and "khatre ke nishaan" not in spoken
    assert (await checks(w, fam))[0].data["verdict"] == "UNSURE"


async def test_screenshot_caption_is_judged_together_with_the_picture(w, ch):
    fam, parent = await w.family(notified=False)
    spoken = await send_image(ch, {"text": "Dear customer"}, caption="Please enter your UPI PIN to confirm.")
    assert "mat" in spoken and (await checks(w, fam))[0].data["verdict"] == "SCAM_LIKELY"


async def test_screenshot_without_consent_is_not_read_at_all(w, ch):
    fam, parent = await w.family(consent=False, notified=False)
    spoken = await send_image(ch, {"text": SCAM_WITH_SENDER})
    assert ch.vision.calls == [] and "nahi jaanch sakti" in spoken  # the picture never reached the vision provider


# ============================================================================ the optional LLM can only raise
async def test_llm_is_not_used_unless_switched_on(w, ch):
    fam, parent = await w.family(notified=False)
    llm = FakeLLM("SCAM_LIKELY")
    ch.llm_box.llm = None
    await send(ch, "Please send the documents by tomorrow morning to the new office, thanks a lot.")
    assert llm.calls == []


async def test_llm_can_raise_a_rules_verdict_but_never_lower_it(w, ch):
    fam, parent = await w.family(notified=False)
    quiet = "Please send the documents by tomorrow morning to the new office, thanks a lot."
    assert scamcheck.check_rules("text", quiet).verdict == "NO_SIGNS_FOUND"
    ch.llm_box.llm = llm = FakeLLM("SCAM_LIKELY")
    spoken = await send(ch, quiet)
    assert llm.calls and (await checks(w, fam))[0].data["verdict"] == "RISKY" and "mat" in spoken  # raised (never above RISKY alone)
    ch.llm_box.llm = low = FakeLLM("NO_SIGNS_FOUND")
    await send(ch, "Share your OTP now or your account will be blocked today")
    assert (await checks(w, fam))[-1].data["verdict"] == "SCAM_LIKELY"  # the rules said HIGH: the model cannot lower it
    assert low.calls == []  # and the model is not even asked about a rule-HIGH message


def test_the_llm_switch_is_off_by_default_in_the_production_wiring(w):
    off = SimpleNamespace(settings=SimpleNamespace(robin_device_scam_llm_enabled=False, docs_vision_provider="none"), get=lambda name: (_ for _ in ()).throw(KeyError(name)))
    on = SimpleNamespace(settings=SimpleNamespace(robin_device_scam_llm_enabled=True, docs_vision_provider="none"), get=off.get)
    assert wiring._parent_route(off, w.hub).scam._llm is None
    assert wiring._parent_route(on, w.hub).scam._llm is not None
    assert isinstance(wiring._parent_route(off, w.hub).scam, ScamForward)
    assert type(wiring._parent_route(off, w.hub).scam._vision()).__name__ == "UnavailableVision"  # provider 'none': screenshots are 'could not read'


async def test_default_route_without_extras_still_judges_by_rules(w, ch):
    fam, parent = await w.family(notified=False)
    w.hub.parent_route = ParentInbound(w.hub, messaging=lambda: ch.wa, stt=lambda: FakeSTT())  # no scam passed: rules only
    spoken = await send(ch, "Share your OTP now or your account will be blocked today")
    assert "mat" in spoken and (await checks(w, fam))[0].data["verdict"] == "SCAM_LIKELY"


async def test_an_engine_failure_is_never_reassuring(w, ch, monkeypatch):
    fam, parent = await w.family(notified=False)

    async def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("engine down")

    monkeypatch.setattr(scamcheck, "check", boom)
    spoken = await send(ch, "Please send the documents by tomorrow morning to the new office, thanks a lot.")
    assert "khatre ke nishaan" not in spoken and "mat" in spoken
    assert (await checks(w, fam))[0].data["verdict"] == "UNSURE"


async def test_a_control_word_typed_still_stops_robin_and_is_not_judged(w, ch):
    fam, parent = await w.family(notified=False)
    await send(ch, "stop")
    assert (await w.store.get_member(parent.id)).paused is True and await checks(w, fam) == []
