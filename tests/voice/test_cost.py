"""Founder cost rules: pre-rendered TTS, no STT on hold, learned IVR replay without
LLM, prompt hang-up/idle/max-duration, per-call cost components."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from friday.core.config import Settings
from friday.core.events import Event
from friday.core.models import (
    AccountIdentifier,
    AudioClass,
    CallAction,
    CallActionType,
    CallOutcome,
    CareRequestKind,
    Language,
    OutboundCallRequest,
    Speaker,
    TaskType,
)
from friday.voice.audio import pcm16_to_ulaw, silence, tone
from friday.voice.langs import VoiceCatalog
from friday.voice.tts.cache import CachedTTS, cached
from friday.voice.tts.fake import FakeTTS

from .conftest import AIRTEL, ScriptedPolicy, hangup, make_brief, no_answer_user, say
from .test_twilio import StubTTS, speech_frames, start_stream


def fake_tts() -> FakeTTS:
    return FakeTTS(VoiceCatalog("fake", Settings(_env_file=None), {}, "f"))


async def test_cached_tts_hits_and_disk(tmp_path):
    inner = fake_tts()
    tts = CachedTTS(inner, cache_dir=str(tmp_path))
    assert (
        await tts.prerender(
            ["Hi, main Friday hoon.", "Hold karne ke liye dhanyavaad."], Language.HINGLISH
        )
        == 2
    )
    clip, hit = await tts.synthesize_cached("Hi, main Friday hoon.", Language.HINGLISH)
    assert hit and clip.data == b"Hi, main Friday hoon." and len(inner.calls) == 2
    assert tts.billed_chars == len("Hi, main Friday hoon.") + len("Hold karne ke liye dhanyavaad.")
    # a fresh process re-uses the on-disk renders: zero vendor calls
    inner2 = fake_tts()
    tts2 = CachedTTS(inner2, cache_dir=str(tmp_path))
    _, hit = await tts2.synthesize_cached("Hi, main Friday hoon.", Language.HINGLISH)
    assert hit and not inner2.calls
    # different language -> different render
    _, hit = await tts2.synthesize_cached("Hi, main Friday hoon.", Language.EN)
    assert not hit
    assert cached(tts2, None) is tts2


async def test_twilio_leg_uses_cache_and_reports_billed_chars(rec, tel):
    tel.tts = CachedTTS(StubTTS())
    leg = await tel.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await tel.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "in-progress"}, leg.key)
    await start_stream(tel, leg, [], {})
    await leg.wait_for_answer(5)
    await leg.speak("Hi, main Friday hoon.", Language.HINGLISH)
    await leg.speak("Hi, main Friday hoon.", Language.HINGLISH)
    assert leg.tts_billed_chars == len("Hi, main Friday hoon.")


async def test_hold_mode_no_stt_on_music_and_announcements_once(rec, tel):
    leg = await tel.place_call(OutboundCallRequest(to_phone="+911800000121", task_id="t"))
    await tel.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "in-progress"}, leg.key)
    sent, state = [], {}
    send = await start_stream(tel, leg, sent, state)
    await leg.wait_for_answer(5)
    tel.stt.text = "Your call is important to us. Please stay on the line."
    leg.set_hold_mode(True)

    async def feed(pcm):
        ulaw = pcm16_to_ulaw(pcm)
        for i in range(0, len(ulaw), 160):
            payload = base64.b64encode(ulaw[i : i + 160]).decode()
            await tel.handle_stream_message(
                {"event": "media", "media": {"payload": payload}}, send, state
            )

    await feed(tone((262, 330, 392), 7.0))  # hold music, cut at 6 s
    music = await leg.listen(5)
    assert music.audio_class == AudioClass.HOLD_MUSIC and tel.stt.calls == 0
    from friday.voice.audio import ulaw_to_pcm16

    announcement = b"".join(ulaw_to_pcm16(f) for f in speech_frames(1.0))
    await feed(silence(1.0) + announcement + silence(1.0))
    first = await leg.listen(5)
    while first.audio_class == AudioClass.HOLD_MUSIC:
        first = await leg.listen(5)
    assert first.audio_class == AudioClass.QUEUE_ANNOUNCEMENT and tel.stt.calls == 1
    await feed(announcement + silence(1.0))  # the same recording loops
    again = await leg.listen(5)
    assert again.audio_class == AudioClass.QUEUE_ANNOUNCEMENT and tel.stt.calls == 1
    assert leg.stt_seconds > 0


def _care_brief(**kw):
    acct = AccountIdentifier(
        user_id="u", company="Airtel", label="Registered mobile", value="9812345678"
    )
    return make_brief(
        AIRTEL,
        "Airtel Customer Care",
        task_type=TaskType.CUSTOMER_CARE,
        company="Airtel",
        care_request=CareRequestKind.COMPLAINT,
        approved_identifiers=[acct],
        **kw,
    )


async def test_learned_ivr_map_replayed_without_policy_calls(make_runner, vbus):
    costs = []

    async def rec_cost(e: Event):
        if type(e).__name__ == "CallCostReport":
            costs.append(e)

    vbus.subscribe(Event, rec_cost)
    policy = ScriptedPolicy(
        [
            say("Hi, I'd like to raise a complaint: broadband down for 3 days.", Language.EN),
            hangup(CallOutcome.SUCCESS, "Thank you, bye."),
        ]
    )
    brief = _care_brief(ivr_notes=["replay: 2 | 3@broadband | {Registered mobile}# | 9@executive"])
    result = await make_runner(policy).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.SUCCESS
    assert result.ivr_keys_replayed == 4
    assert result.policy_calls == 2  # zero LLM for menus and hold
    first_policy_view = policy.calls[0].render()
    assert (
        "HUMAN AGENT JOINED AFTER" in first_policy_view and "learned IVR map" in first_policy_view
    )
    assert result.hold_seconds >= 420
    assert costs and costs[0].hold_seconds == result.hold_seconds
    assert costs[0].policy_calls == 2 and costs[0].tts_chars == result.tts_chars > 0


async def test_ivr_replay_stops_when_menu_changed(make_runner):
    policy = ScriptedPolicy(
        [
            CallAction(type=CallActionType.PRESS_KEYS, digits="3"),
            hangup(CallOutcome.PARTIAL, None),
        ]
    )
    brief = _care_brief(ivr_notes=["replay: 2@hindi | 7@sports"])
    result = await make_runner(policy).run(brief, no_answer_user)
    sys = [t.text for t in result.transcript.turns if t.speaker == Speaker.SYSTEM]
    assert any("IVR REPLAY STOPPED: menu changed" in s for s in sys)
    assert result.ivr_keys_replayed == 1 and result.policy_calls >= 1


async def test_ivr_replay_refuses_unapproved_identifier(make_runner, sim):
    brief = _care_brief(ivr_notes=["replay: 2 | 3 | {account number}#"])
    result = await make_runner(ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)])).run(
        brief, no_answer_user
    )
    assert any("unapproved identifier" in t.text for t in result.transcript.turns)
    assert all(len(d) <= 2 for d in sim.legs[-1].dtmf)


async def test_prerender_fixed_lines_while_ringing(make_runner, sim):
    tts = CachedTTS(fake_tts())
    orig = sim.place_call

    async def place(req):
        leg = await orig(req)
        leg.tel = SimpleNamespace(tts=tts)
        return leg

    sim.place_call = place
    policy = ScriptedPolicy([hangup(CallOutcome.PARTIAL)])
    await make_runner(policy).run(make_brief(), no_answer_user)
    rendered = {c[0] for c in tts.inner.calls}
    brief = make_brief()
    assert brief.disclosure() in rendered
    assert any("intezaar" in t for t in rendered)  # hold line
    assert any("call back" in t for t in rendered)  # safe exit / call-back line


async def test_cost_components_and_prompt_end(make_runner, sim, vbus):
    seen = []

    async def on(e: Event):
        seen.append(e)

    vbus.subscribe(Event, on)
    result = await make_runner(
        ScriptedPolicy([say("Rate kitna hai?"), hangup(CallOutcome.PARTIAL)])
    ).run(make_brief(), no_answer_user)
    assert sim.legs[-1].ended  # hung up straight after HANGUP
    assert result.telephony_seconds > 0 and result.tts_chars > 0 and result.policy_calls == 2
    names = [type(e).__name__ for e in seen]
    assert names.index("CallCostReport") < names.index("CallFinished")
    report = next(e for e in seen if type(e).__name__ == "CallCostReport")
    assert json.loads(report.model_dump_json())["telephony_seconds"] == result.telephony_seconds


async def test_idle_line_ends_call(make_runner, sim):
    policy = ScriptedPolicy([CallAction(type=CallActionType.WAIT) for _ in range(10)])
    result = await make_runner(policy).run(make_brief(), no_answer_user)
    assert result.outcome == CallOutcome.HUNG_UP
    assert any(t.text == "LINE SILENT - ending call" for t in result.transcript.turns) or (
        "CALLEE HUNG UP" in [t.text for t in result.transcript.turns]
    )


@pytest.fixture
def rec():
    from .test_twilio import Recorder

    return Recorder()


@pytest.fixture
def tel(rec):
    import httpx

    from friday.core.events import EventBus
    from friday.voice.telephony.twilio import TwilioTelephony

    from .test_twilio import StubSTT

    return TwilioTelephony(
        account_sid="ACtest",
        auth_token="t",
        from_number="+918069110001",
        public_base_url="https://friday.example.in",
        stt=StubSTT(),
        tts=StubTTS(),
        bus=EventBus(),
        transport=httpx.MockTransport(rec),
    )
