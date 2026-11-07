# ruff: noqa: E501
"""T10: a call FORWARDED from a Robin member's phone, through the real app (bus event -> CallbackService -> RobinHub), tested with fakes.

A scripted caller leg stands in for the carrier-forwarded call; nothing is dialled and no number is real (all invented). The parent's phone is
the FakeParentCaller, her WhatsApp the FakeParentChannel, the child's WhatsApp the simulator channel."""

from __future__ import annotations

from datetime import datetime

from friday.core.clock import IST
from friday.core.events import InboundCallReceived
from friday.robin.models import CallResult
from tests.e2e.robin.harness import CHILD, PARENT, RobinWorld, assert_no_pii
from tests.frontdoor.conftest import FRIDAY_NUMBER, ScriptedLeg

STRANGER = "+919100000077"  # invented
FIELDS = {"robin_forwarded_calls_enabled": True, "friday_numbers": [FRIDAY_NUMBER]}


async def start(**kw) -> RobinWorld:
    w = await RobinWorld.start(**{**FIELDS, **kw})
    w.script_calls(CallResult.ANSWERED)
    fam = await w.setup_family()
    child = await w.hub.ctx.child(fam)
    child.name = "Asha"  # the e2e child has no member name yet (the lines fall back to 'ji')
    await w.store.save_member(child, fam.owner_user_id)
    w.script_calls(CallResult.NO_ANSWER)
    return w


def missed_texts(w: RobinWorld) -> list[str]:
    """The parent's 'X called you' messages (the scheduler may also drain other lines to her)."""
    return [t for _, t in w.channel.texts if "baje phone kiya" in t]


async def forwarded(w: RobinWorld, missed_phone: str, caller: str, script: list, *, leg: ScriptedLeg | None = None) -> ScriptedLeg:
    leg = leg or ScriptedLeg(script)
    w.f.c.telephony.inbound_legs[leg.provider_call_id] = leg
    await w.f.c.bus.publish(InboundCallReceived(from_phone=caller, to_number=FRIDAY_NUMBER, provider_call_id=leg.provider_call_id, provider="test", redirecting=f"<sip:{missed_phone}@vobiz.example>;reason=no-answer"))
    await w.f.settle()
    return leg


async def test_stranger_rings_the_parent_not_urgent_message_and_no_ringing():
    w = await start()
    try:
        n_parent, n_child = len(w.channel.texts), len(w.child_texts())
        leg = await forwarded(w, PARENT, STRANGER, ["Main Sharma bol raha hoon, society ke maintenance ke baare mein", "nahi"])
        assert "AI assistant answering for Papa" in leg.texts[0] or "Papa ki AI assistant" in leg.texts[0]
        assert leg.hung_up and len(leg.texts) == 3  # who, urgent, thank-you
        assert len(w.channel.texts) == n_parent + 1 and "maintenance" in w.channel.texts[-1][1]
        assert len(w.channel.voice_notes) >= 2  # the parent also gets a short voice note
        assert len(w.child_texts()) == n_child  # a stranger's non-urgent call does not message the child, and the stranger is told nothing
        await w.advance(minutes=30)
        assert w.calls(purpose="emergency_ring") == []
    finally:
        await w.close()


async def test_urgent_stranger_rings_the_parent_six_times_and_stops_at_the_cap():
    w = await start()
    try:
        await forwarded(w, PARENT, STRANGER, ["Beta ka accident hua hai, jaldi batao", "haan"])
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1
        for _ in range(5):
            await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 6
        await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 6, "6 tries is the cap"
    finally:
        await w.close()


async def test_parent_saying_fine_stops_the_ringing_of_a_forwarded_urgent_call():
    w = await start()
    try:
        await forwarded(w, PARENT, STRANGER, ["bank ka zaroori kaam hai", "yes"])
        await w.advance(minutes=3)
        reply = await w.parent_says("main theek hoon")
        assert reply is not None and reply.action == "fine"
        await w.advance(minutes=3)
        await w.advance(minutes=30)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 2  # 'I am fine' stops it
    finally:
        await w.close()


async def test_urgent_forwarded_call_at_three_in_the_morning_still_rings():
    w = await start(now=datetime(2026, 1, 5, 21, 0, tzinfo=IST))
    try:
        w.clock.set(datetime(2026, 1, 6, 3, 0, tzinfo=IST))
        await forwarded(w, PARENT, STRANGER, ["emergency hai", "yes"])
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1  # security paths ignore time of day
        await w.advance(minutes=3)
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 2
    finally:
        await w.close()


async def test_parent_missed_and_the_child_calling_is_told_that_papa_has_been_told():
    w = await start()
    try:
        n = len(w.child_texts())
        await forwarded(w, PARENT, CHILD, ["Papa main hoon, shaam ko late aaunga", "nahi"])
        fresh = w.child_texts()[n:]
        assert len(fresh) == 1 and "Papa has been told" in fresh[0]
        assert "late aaunga" in w.channel.texts[-1][1]
    finally:
        await w.close()


async def test_child_missed_and_the_parent_calling_gets_a_confirmation_in_her_language():
    w = await start()
    try:
        n_child, n_parent, n_vn = len(w.child_texts()), len(w.channel.texts), len(w.channel.voice_notes)
        leg = await forwarded(w, CHILD, PARENT, ["Beta dawai khatam ho gayi hai", "nahi"])
        assert "Asha" in leg.texts[0] and "Papa" not in leg.texts[0]  # the missed person is named, not the parent
        fresh = w.child_texts()[n_child:]
        assert len(fresh) == 1 and "Papa" in fresh[0] and "dawai khatam" in fresh[0]
        assert len(w.channel.texts) == n_parent + 1 and "Asha ko bata diya gaya hai" in w.channel.texts[-1][1]  # hinglish: the parent's language
        assert len(w.channel.voice_notes) == n_vn + 1
    finally:
        await w.close()


async def test_urgent_call_for_the_child_rings_the_child_and_i_have_it_stops_it():
    w = await start()
    try:
        await forwarded(w, CHILD, PARENT, ["mujhe seene mein dard ho raha hai", "yes"])
        assert len(w.calls(role="child", purpose="emergency_ring")) == 1
        await w.child_says("I have it")
        await w.advance(minutes=3)
        await w.advance(minutes=30)
        assert len(w.calls(role="child", purpose="emergency_ring")) == 1
    finally:
        await w.close()


async def test_caller_hangs_up_after_saying_who_the_message_still_goes():
    w = await start()
    try:
        n = len(w.channel.texts)
        await forwarded(w, PARENT, STRANGER, ["courier wala hoon, parcel ke liye", "HANGUP"])
        assert len(w.channel.texts) == n + 1 and "parcel" in w.channel.texts[-1][1]
    finally:
        await w.close()


async def test_nobody_speaks_the_family_still_hears_that_a_call_was_missed():
    w = await start()
    try:
        await forwarded(w, PARENT, STRANGER, [None, None, None, None])
        assert len(missed_texts(w)) == 1 and "nothing clear" in missed_texts(w)[0]  # NB the 'no summary' filler is in the child's chat language (existing behaviour)
    finally:
        await w.close()


async def test_a_number_that_is_not_a_robin_member_still_goes_the_old_receptionist_path():
    """Regression: Robin ON and the forwarded switch ON, but the redirecting number is nobody's in a Robin family: the receptionist handles it
    exactly as before, and Robin sends nothing."""
    w = await start(receptionist_enabled=True, receptionist_redirect_fields=["Diversion"])
    try:
        n_parent, n_child = len(w.channel.texts), len(w.child_texts())
        leg = await forwarded(w, "+919800000555", STRANGER, ["Main Zoya bol rahi hoon, kaam ke baare mein", "haan"])
        assert leg.texts[0].startswith("Hello, main Friday bol rahi hoon, ek virtual assistant")  # the receptionist's own greeting
        assert "AI assistant" not in " ".join(leg.texts)
        assert len(w.channel.texts) == n_parent and len(w.child_texts()) == n_child and w.calls(purpose="emergency_ring") == []
    finally:
        await w.close()


async def test_switch_off_means_no_change():
    w = await RobinWorld.start(friday_numbers=[FRIDAY_NUMBER], receptionist_enabled=True, receptionist_redirect_fields=["Diversion"])  # forwarded switch left at its default (OFF)
    try:
        assert w.settings.robin_forwarded_calls_enabled is False
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        n = len(w.channel.texts)
        leg = await forwarded(w, PARENT, STRANGER, ["Main Zoya bol rahi hoon", "haan"])
        assert "AI assistant answering for" not in " ".join(leg.texts)  # Robin did not take it
        assert len(w.channel.texts) == n
        await w.child_says("forwarding jio")  # and the setup words are not Robin's either
        assert not any("real SIM" in t for t in w.child_texts())
        assert not any("forwarding" in t.lower() and "Optional" in t for t in w.child_texts())  # no onboarding offer either
    finally:
        await w.close()


async def test_a_paused_family_is_not_answered_by_robin():
    w = await start()
    try:
        await w.parent_says("band karo")
        leg = await forwarded(w, PARENT, STRANGER, ["hello", "nahi"])
        assert "answering for Papa" not in " ".join(leg.texts) and "Papa ki AI assistant" not in " ".join(leg.texts)
        assert missed_texts(w) == []
    finally:
        await w.close()


async def test_flood_cap_stops_a_stranger_from_starting_the_ring_loop_again_and_again():
    w = await start(robin_forwarded_per_hour=2)
    try:
        for _ in range(2):
            await forwarded(w, PARENT, STRANGER, ["kaam hai", "nahi"])
            w.clock.advance(minutes=1)
        await forwarded(w, PARENT, STRANGER, ["jaldi", "yes"])  # third in the hour: the message goes, the ringing does not
        await w.advance(minutes=3)
        assert w.calls(purpose="emergency_ring") == []
        assert any("jaldi" in t for t in missed_texts(w))
        w.clock.advance(hours=2)
        await forwarded(w, PARENT, STRANGER, ["ab zaroori hai", "yes"])
        assert len(w.calls(role="parent", purpose="emergency_ring")) == 1
    finally:
        await w.close()


async def test_nothing_in_the_logs_or_the_audit_trail_has_a_full_number_or_the_words():
    w = await start()
    try:
        await forwarded(w, PARENT, CHILD, ["chest pain hai, ambulance bulao", "yes"])
        w.assert_no_pii(await w.audit_blob())
        assert_no_pii(w.logs.text(), phones=(CHILD, PARENT, STRANGER), what="logs")
    finally:
        await w.close()


async def test_a_slow_caller_is_cut_off_inside_the_cap():
    w = await start()
    try:
        t = {"now": 0.0}
        w.hub.forwarded.mono = lambda: t["now"]

        class SlowLeg(ScriptedLeg):
            async def speak(self, text, language):
                t["now"] += 20.0
                await super().speak(text, language)

            async def listen(self, timeout_s):
                t["now"] += 15.0
                return await super().listen(timeout_s)

        leg = await forwarded(w, PARENT, STRANGER, [], leg=SlowLeg(["bahut lamba sa sandesh", "haan", "aur kuch", "aur kuch"]))
        assert leg.hung_up
        assert t["now"] <= 75 + 20  # the closing line may run just past the 75 s cap, never another question
    finally:
        await w.close()


# ------------------------------------------------------------------ the child's onboarding: per-carrier forwarding setup and the test step
async def test_onboarding_offers_forwarding_and_gives_the_codes_per_carrier_with_u_marks():
    w = await RobinWorld.start(**FIELDS)
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        assert any("Optional" in t and "forwarding jio" in t for t in w.child_texts()), "the setup ends with the forwarding offer"
        for carrier, name in (("jio", "Jio"), ("airtel", "Airtel"), ("vi", "Vi")):
            out = await w.child_says(f"forwarding {carrier}")
            text = "\n".join(out)
            assert name in text and "[U]" in text and "**61*+918065354620**" in text and "Papa" in text
        out = await w.child_says("forwarding jio for me")
        assert "Asha" in "\n".join(out) or "you" in "\n".join(out)
        assert "Which one is it" in "\n".join(await w.child_says("forwarding tata"))
        w.assert_no_pii("\n".join(w.child_texts()).replace("+918065354620", "<ROBIN-LINE>"), phones=(PARENT,))
    finally:
        await w.close()


async def test_test_forwarding_places_no_call_and_says_it_is_for_the_founder_number_only():
    w = await RobinWorld.start(**FIELDS)
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        before_calls, before_legs = len(w.caller.calls), len(w.f.c.telephony.legs)
        out = "\n".join(await w.child_says("test forwarding"))
        assert "founder" in out and "Nothing is dialled" in out
        assert len(w.caller.calls) == before_calls and len(w.f.c.telephony.legs) == before_legs
    finally:
        await w.close()


async def test_without_a_robin_number_the_child_is_told_codes_are_not_ready():
    w = await RobinWorld.start(robin_forwarded_calls_enabled=True)
    try:
        w.script_calls(CallResult.ANSWERED)
        await w.setup_family()
        assert "not set up yet" in "\n".join(await w.child_says("forwarding airtel"))
    finally:
        await w.close()
