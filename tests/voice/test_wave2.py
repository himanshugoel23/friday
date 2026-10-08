# ruff: noqa: E501
"""Stage 3 wave 2 (Voice): protocol conformance, SECURITY-3/4/24/27 in the runner,
NP-4 caller-ID/signals, S-6 recordings, S-9 worker/limiters/drain, S-10 shared caches,
and graceful degradation when the provider lacks a capability."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from friday.core.config import Settings
from friday.core.events import Event
from friday.core.interfaces import (
    CancellableRunner,
    InboundCallRunner,
    InboundTelephony,
    ProviderError,
    telephony_capabilities,
)
from friday.core.models import (
    AccountIdentifier,
    AudioClass,
    CallAction,
    CallActionType,
    CallMode,
    CallOutcome,
    CareRequestKind,
    DialStatus,
    Language,
    OutboundCallRequest,
    Speaker,
    TaskType,
)
from friday.core.scale import Job, MemoryCache, MemoryJobQueue, MemoryRateLimiter
from friday.voice.session import CallRunner
from friday.voice.simulator import BusinessAgent
from friday.voice.telephony.exotel import ExotelTelephony
from friday.voice.telephony.routing import RoutedTelephony
from friday.voice.telephony.sarvam import SarvamTelephony
from friday.voice.telephony.twilio import TwilioTelephony
from friday.voice.tts.cache import CachedTTS
from friday.voice.worker import VoiceWorker

from .conftest import (
    AIRTEL,
    LOOKS,
    ScriptedPolicy,
    hangup,
    make_brief,
    no_answer_user,
    say,
)
from .test_cost import fake_tts
from .test_twilio import Recorder as TwilioRecorder
from .test_twilio import StubSTT, StubTTS, start_stream


def sys_lines(result):
    return [t.text for t in result.transcript.turns if t.speaker == Speaker.SYSTEM]


def fri_lines(result):
    return [t.text for t in result.transcript.turns if t.speaker == Speaker.FRIDAY]


# ------------------------------------------------------------------ conformance


def test_protocol_conformance(sim, make_runner):
    runner = make_runner(ScriptedPolicy([]))
    assert isinstance(runner, CancellableRunner) and isinstance(runner, InboundCallRunner)
    assert isinstance(sim, InboundTelephony)
    assert telephony_capabilities(sim) >= {"dtmf", "bridge_transfer", "missed_call"}


# ------------------------------------------------------------------ SECURITY-3 / 4 / 27


async def test_unflagged_commitment_is_blocked_by_the_runner(make_runner, sim):
    """SECURITY-3: the policy forgot commits_booking; the runner still gates the text."""
    sneaky = say("Theek hai, 6 baje final. Ramesh ji aa jayenge.")
    result = await make_runner(ScriptedPolicy([sneaky, hangup(CallOutcome.PENDING_APPROVAL)])).run(
        make_brief(), no_answer_user
    )
    assert "Theek hai, 6 baje final. Ramesh ji aa jayenge." not in [
        t for t, _ in sim.legs[-1].spoken
    ]
    assert any("commitment not allowed" in s for s in sys_lines(result))
    assert result.outcome == CallOutcome.PENDING_APPROVAL


async def test_callback_wording_is_not_a_commitment(make_runner, sim):
    ok = say("Main Rahul se confirm karke aapko 6 baje ke baad call back karti hoon.")
    result = await make_runner(ScriptedPolicy([ok, hangup(CallOutcome.PENDING_APPROVAL)])).run(
        make_brief(), no_answer_user
    )
    assert not any(s.startswith("BLOCKED") for s in sys_lines(result))


async def test_success_needs_a_gated_commit_turn(make_runner):
    """SECURITY-4: outcome comes from what happened, not from the model's claim."""
    hallucinated = hangup(CallOutcome.SUCCESS, "Thank you, bye.")
    result = await make_runner(ScriptedPolicy([say("Rate kya hai?"), hallucinated])).run(
        make_brief(), no_answer_user
    )
    assert result.outcome == CallOutcome.PARTIAL
    assert "OUTCOME DOWNGRADED: no gated commit" in sys_lines(result)
    assert "committed" not in result.collected
    # a real, approved commit stands and is reported to the engine
    commit = say("6pm book kar dijiye.", commits_booking=True)
    ok = await make_runner(ScriptedPolicy([commit, hangup(CallOutcome.SUCCESS)])).run(
        make_brief(approved_terms="6pm, Rs 400"), no_answer_user
    )
    assert ok.outcome == CallOutcome.SUCCESS and ok.collected["committed"] == "true"


async def test_non_commit_task_success_is_untouched(make_runner):
    result = await make_runner(ScriptedPolicy([hangup(CallOutcome.SUCCESS)])).run(
        make_brief(task_type=TaskType.ENQUIRY), no_answer_user
    )
    assert result.outcome == CallOutcome.SUCCESS


async def test_delegation_window_and_scope_are_enforced(make_runner, sim):
    from friday.core.models import Delegation, Quote

    start = datetime(2026, 1, 6, 17, 0, tzinfo=UTC)
    deleg = Delegation(
        granted=True, window_start=start, window_end=start.replace(hour=19), scope=["slot"]
    )
    q = Quote(business_name="x", amount_inr=300, price_text="300")
    # price decision is not in the delegated scope
    scoped = say("6pm book kar dijiye.", commits_booking=True, quote=q,
                 collected={"slot_at": start.isoformat()})  # fmt: skip
    result = await make_runner(ScriptedPolicy([scoped, hangup(CallOutcome.PENDING_APPROVAL)])).run(
        make_brief(delegation=deleg), no_answer_user
    )
    assert any("scope" in s for s in sys_lines(result))


# ------------------------------------------------------------------ SECURITY-24


async def test_ivr_key_buffer_resets_on_each_prompt(make_runner, sim):
    acct = AccountIdentifier(user_id="u", label="Registered mobile", value="9812345678")
    keys = lambda d: CallAction(type=CallActionType.PRESS_KEYS, digits=d)  # noqa: E731
    # "2" then "3" are separate prompts (fine); a PIN keyed as 48 + 21 inside one prompt is not
    policy = ScriptedPolicy(
        [keys("2"), keys("3"), keys("48"), keys("21"), hangup(CallOutcome.PARTIAL)]
    )
    brief = make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel",
                       approved_identifiers=[acct])  # fmt: skip
    result = await make_runner(policy).run(brief, no_answer_user)
    # the IVR re-prompts after every key, so each chunk starts a fresh buffer (reset per
    # prompt); concatenation WITHOUT a prompt in between is blocked - see
    # tests/security/test_call_runner_redteam.py::test_dtmf_chunks_are_concatenated_per_prompt
    assert sim.legs[-1].dtmf == ["2", "3", "48", "21"]
    assert not any(x.startswith("BLOCKED") for x in sys_lines(result))


async def test_transcript_turns_carry_audio_class(make_runner):
    policy = ScriptedPolicy([CallAction(type=CallActionType.PRESS_KEYS, digits="2"),
                             hangup(CallOutcome.PARTIAL, None)])  # fmt: skip
    brief = make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel")
    result = await make_runner(policy).run(brief, no_answer_user)
    callee = [t for t in result.transcript.turns if t.speaker == Speaker.CALLEE]
    assert callee[0].audio_class == AudioClass.IVR_PROMPT
    assert not callee[0].text.startswith("[")  # no text-prefix convention any more


# ------------------------------------------------------------------ NP-4


async def test_new_number_line_follows_the_disclosure(make_runner, sim):
    policy = ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)])
    result = await make_runner(policy).run(make_brief(number_changed=True), no_answer_user)
    lines = fri_lines(result)
    assert lines[0].startswith("Hi, main Friday hoon")
    assert "naye number" in lines[1]
    assert not any(ch.isdigit() for ch in lines[1])  # nothing for the safety guard to flag
    plain = await make_runner(ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)])).run(
        make_brief(), no_answer_user
    )
    assert not any("naye number" in x for x in fri_lines(plain))


async def test_from_number_reaches_every_provider(sim, vsettings):
    req = OutboundCallRequest(to_phone="+918040000001", task_id="t", from_number="+918069110003")
    assert (await sim.place_call(req)).from_number == "+918069110003"

    rec = TwilioRecorder()
    tw = TwilioTelephony(account_sid="AC", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS(),
                         transport=httpx.MockTransport(rec))  # fmt: skip
    await tw.place_call(req)
    assert parse_qs(rec.requests[-1].content.decode())["From"] == ["+918069110003"]

    def exo_handler(r):
        exo_handler.last = r
        return httpx.Response(200, json={"Call": {"Sid": "e1"}})

    exo = ExotelTelephony(sid="s", api_key="k", api_token="t", caller_ids=["+918047110001"],
                          voicebot_app_id="1", public_base_url="https://f.example.in", secret="x",
                          stt=StubSTT(), tts=StubTTS(), transport=httpx.MockTransport(exo_handler))  # fmt: skip
    await exo.place_call(req)
    assert parse_qs(exo_handler.last.content.decode())["CallerId"] == ["+918069110003"]

    def sar_handler(r):
        sar_handler.last = r
        return httpx.Response(201, json={"request_uuid": "u1"})

    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
                          public_base_url="https://f.example.in", secret="x", stt=StubSTT(),
                          tts=StubTTS(), transport=httpx.MockTransport(sar_handler))  # fmt: skip
    await sar.place_call(req)
    assert json.loads(sar_handler.last.content)["from"] == "918069110003"


async def test_runner_passes_brief_from_number_to_the_provider(make_runner, sim):
    brief = make_brief(from_number="+918069110002")
    result = await make_runner(ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)])).run(
        brief, no_answer_user
    )
    assert (
        result.from_number == "+918069110002"
        and sim.legs[-1].request.from_number == "+918069110002"
    )


@pytest.mark.parametrize(("note", "signal"), [("sim:blocks_number=*", "blocked"),
                                              ("sim:rejects_number=+918069110002", "rejected")])  # fmt: skip
async def test_simulated_carrier_block_signals_reach_the_result(make_runner, sim, note, signal):
    biz = sim.world.by_phone(LOOKS).model_copy(deep=True)
    biz.persona.notes = [note]
    sim.agent_for = lambda phone, role=None: BusinessAgent(sim, biz, 1)
    result = await make_runner(ScriptedPolicy([])).run(
        make_brief(from_number="+918069110002"), no_answer_user
    )
    assert result.dial_status == DialStatus.FAILED and result.outcome == CallOutcome.FAILED
    assert signal in result.error  # the engine maps "block"/"reject" to NumberOutcome
    assert result.collected["provider_signal"] == signal


async def test_provider_block_signals(vbus):
    rec = TwilioRecorder()
    tw = TwilioTelephony(account_sid="AC", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS(),
                         transport=httpx.MockTransport(rec))  # fmt: skip
    leg = await tw.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await tw.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "failed",
                            "SipResponseCode": "608"}, leg.key)  # fmt: skip
    assert await leg.wait_for_answer(1) == DialStatus.FAILED and leg.block_signal == "blocked"

    exo = ExotelTelephony(sid="s", api_key="k", api_token="t", caller_ids=["+918047110001"],
                          voicebot_app_id="1", public_base_url="https://f.example.in", secret="x",
                          stt=StubSTT(), tts=StubTTS(),
                          transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"Call": {"Sid": "e1"}})))  # fmt: skip
    leg = await exo.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await exo.handle_status({"CallSid": "e1", "Status": "failed", "EventType": "terminal",
                             "Reason": "Number marked as spam"}, leg.key)  # fmt: skip
    assert leg.block_signal == "blocked" and await leg.wait_for_answer(1) == DialStatus.FAILED

    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
                          public_base_url="https://f.example.in", secret="x", stt=StubSTT(),
                          tts=StubTTS(),
                          transport=httpx.MockTransport(lambda r: httpx.Response(201, json={"request_uuid": "u1"})))  # fmt: skip
    leg = await sar.place_call(OutboundCallRequest(to_phone="+918040000001", task_id="t"))
    await sar.handle_hangup({"RequestUUID": "u1", "HangupCause": "CALL_REJECTED"}, leg.key)
    assert leg.block_signal == "rejected" and await leg.wait_for_answer(1) == DialStatus.FAILED


async def test_inbound_on_a_retired_number_is_accepted_everywhere(sim, vbus):
    seen: list[Event] = []

    async def on(e):
        seen.append(e)

    vbus.subscribe(Event, on)
    retired = "+918000999999"  # not in any pool
    sim.retired_numbers.add(retired)
    cid = await sim.simulate_inbound_call(LOOKS, retired)
    assert cid and sim.take_inbound(cid) is not None

    tw = TwilioTelephony(account_sid="AC", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS(),
                         bus=vbus, inbound_claim_timeout_s=5)  # fmt: skip
    tw.inbound_twiml({"CallSid": "CAr", "From": LOOKS, "To": retired})
    await start_stream(tw, tw.by_sid["CAr"], [], {})
    exo = ExotelTelephony(sid="s", api_key="k", api_token="t", caller_ids=["+918047110001"],
                          voicebot_app_id="1", public_base_url="https://f.example.in", secret="x",
                          stt=StubSTT(), tts=StubTTS(), bus=vbus, inbound_claim_timeout_s=5)  # fmt: skip
    await exo.handle_passthru({"CallSid": "ex1", "CallFrom": LOOKS, "CallTo": retired})
    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=[], public_base_url="https://f.example.in",
                          secret="x", stt=StubSTT(), tts=StubTTS(), bus=vbus, inbound_claim_timeout_s=5)  # fmt: skip
    await sar.answer_xml({"CallUUID": "sv1", "From": LOOKS, "To": retired}, None)
    sar_leg = sar.by_sid["sv1"]
    await sar.handle_stream_message({"event": "start", "start": {"callId": "sv1", "streamId": "s"}},
                                    lambda t: asyncio.sleep(0), {}, key=sar_leg.key)  # fmt: skip
    inbound = [e for e in seen if type(e).__name__ == "InboundCallReceived"]
    assert [e.to_number for e in inbound].count(retired) >= 3
    for leg in (tw.by_sid["CAr"], sar_leg):
        leg._end()


# ------------------------------------------------------------------ S-6 recordings


class FakeStore:
    def __init__(self, owns_all: bool = False, fail: bool = False):
        self.puts: list[tuple[str, bytes, str]] = []
        self.owns_all = owns_all
        self.fail = fail

    async def put(self, key, data, *, content_type):
        if self.fail:
            raise RuntimeError("s3 down")
        self.puts.append((key, data, content_type))
        return f"s3://friday-recordings/{key}"

    def owns(self, url):
        return self.owns_all


def runner_with(sim, vsettings, fclock, vbus, **kw):
    return CallRunner(telephony=kw.pop("telephony", sim), policy=kw.pop("policy"),
                      settings=vsettings, clock=fclock, bus=vbus, **kw)  # fmt: skip


async def test_recording_is_moved_to_the_object_store(sim, vsettings, fclock, vbus):
    store = FakeStore()
    runner = runner_with(sim, vsettings, fclock, vbus, recording_store=store,
                         policy=ScriptedPolicy([say("Rate kya hai?"), hangup(CallOutcome.PARTIAL)]))  # fmt: skip
    result = await runner.run(make_brief(), no_answer_user)
    assert result.recording_url.startswith("s3://friday-recordings/")
    key, data, ctype = store.puts[0]
    assert key.startswith(f"{result.task_id}/{result.call_id}") and b"FRIDAY" in data
    assert not result.recording_url.startswith("file://")  # never a local path in the record


async def test_recording_upload_failure_never_leaves_a_local_path(sim, vsettings, fclock, vbus):
    runner = runner_with(sim, vsettings, fclock, vbus, recording_store=FakeStore(fail=True),
                         policy=ScriptedPolicy([hangup(CallOutcome.PARTIAL)]))  # fmt: skip
    result = await runner.run(make_brief(), no_answer_user)
    assert result.recording_url is None and result.outcome == CallOutcome.PARTIAL


async def test_provider_recording_is_fetched_with_auth_then_stored(sim, vsettings, fclock, vbus):
    store = FakeStore()
    fetched: list[str] = []

    class Spy:
        name = "routed"

        def capabilities(self):
            return sim.capabilities()

        async def place_call(self, req):
            leg = await sim.place_call(req)

            async def url():
                return "https://api.twilio.com/2010-04-01/Accounts/AC/Recordings/RE1.mp3"

            async def fetch(u):
                fetched.append(u)
                return b"mp3-bytes"

            leg.recording_url, leg.fetch_recording = url, fetch
            return leg

    runner = runner_with(sim, vsettings, fclock, vbus, recording_store=store, telephony=Spy(),
                         policy=ScriptedPolicy([hangup(CallOutcome.PARTIAL)]))  # fmt: skip
    result = await runner.run(make_brief(), no_answer_user)
    assert fetched and store.puts[0][1] == b"mp3-bytes" and store.puts[0][2] == "audio/mpeg"
    assert result.recording_url.startswith("s3://")


async def test_recording_already_in_the_store_is_kept(sim, vsettings, fclock, vbus):
    runner = runner_with(sim, vsettings, fclock, vbus, recording_store=FakeStore(owns_all=True),
                         policy=ScriptedPolicy([hangup(CallOutcome.PARTIAL)]))  # fmt: skip
    result = await runner.run(make_brief(), no_answer_user)
    assert result.recording_url.startswith("file://")


async def test_delete_recording_everywhere(sim, tmp_path):
    # simulator
    leg = await sim.place_call(OutboundCallRequest(to_phone=LOOKS, task_id="t"))
    await leg.wait_for_answer(5)
    await leg.hangup()
    url = await leg.recording_url()
    await sim.delete_recording(url)
    with pytest.raises(ProviderError):
        await sim.delete_recording("file:///etc/passwd")
    # twilio
    rec = TwilioRecorder()
    tw = TwilioTelephony(account_sid="ACx", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS(),
                         transport=httpx.MockTransport(rec))  # fmt: skip
    await tw.delete_recording("https://api.twilio.com/2010-04-01/Accounts/ACx/Recordings/RE123.mp3")
    assert rec.requests[-1].method == "DELETE"
    assert rec.requests[-1].url.path == "/2010-04-01/Accounts/ACx/Recordings/RE123.json"
    for bad in ("https://evil.example/Recordings/RE1.mp3",
                "https://api.twilio.com/2010-04-01/Accounts/OTHER/Recordings/RE1.mp3"):  # fmt: skip
        with pytest.raises(ProviderError):
            await tw.delete_recording(bad)
    assert await tw.fetch_recording("https://evil.example/Recordings/RE1.mp3") is None
    gone = TwilioTelephony(account_sid="ACx", auth_token="t", from_number="+918069110001",
                           public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS(),
                           transport=httpx.MockTransport(lambda r: httpx.Response(404, text="no")))  # fmt: skip
    await gone.delete_recording("https://api.twilio.com/2010-04-01/Accounts/ACx/Recordings/RE9.mp3")
    # routed delegates to whichever provider owns the URL
    routed = RoutedTelephony([sim, tw])
    await routed.delete_recording(
        "https://api.twilio.com/2010-04-01/Accounts/ACx/Recordings/RE5.mp3"
    )
    # exotel: fails loudly so the erasure job keeps it in pending_deletions
    exo = ExotelTelephony(sid="s", api_key="k", api_token="t", caller_ids=[], voicebot_app_id="1",
                          public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=StubTTS())  # fmt: skip
    with pytest.raises(ProviderError):
        await exo.delete_recording("https://recordings.exotel.com/x/abc.mp3")


# ------------------------------------------------------------------ S-9 worker


def call_job(i: int) -> Job:
    return Job(kind="call.place", payload={"task_id": f"t{i}"}, dedupe_key=f"call:{i}")


def make_worker(queue, runner, settings, sim, name, handler, concurrency=2):
    return VoiceWorker(queue=queue, handler=handler, settings=settings, runner=runner,
                       telephony=sim, concurrency=concurrency, poll_s=0.01, wid=name)  # fmt: skip


async def test_two_voice_workers_handle_each_call_once(sim, vsettings, fclock, vbus):
    queue = MemoryJobQueue(fclock)
    done: list[tuple[str, str]] = []

    def handler_for(name, runner):
        async def handle(job: Job) -> None:
            await runner.run(make_brief(task_id=job.payload["task_id"]), no_answer_user)
            await queue.ack(job.id)
            done.append((name, job.id))

        return handle

    workers = []
    for name in ("voice-a", "voice-b"):
        runner = runner_with(sim, vsettings, fclock, vbus, policy=ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)]))  # fmt: skip
        workers.append(make_worker(queue, runner, vsettings, sim, name, handler_for(name, runner)))
    jobs = [await queue.enqueue(call_job(i)) for i in range(6)]
    assert all(w.free_slots == 2 for w in workers)
    while await queue.depth():
        for w in workers:
            await w.run_once()
            await w.wait_idle(5)
    ids = [j for _, j in done]
    assert sorted(ids) == sorted(j.id for j in jobs) and len(set(ids)) == 6  # exactly once
    assert {n for n, _ in done} == {"voice-a", "voice-b"}
    assert sim.legs[0].request.metadata  # real calls were placed


async def test_worker_never_claims_beyond_capacity(sim, vsettings, fclock, vbus):
    queue = MemoryJobQueue(fclock)
    gate = asyncio.Event()

    async def handle(job):
        await gate.wait()
        await queue.ack(job.id)

    runner = runner_with(sim, vsettings, fclock, vbus, policy=ScriptedPolicy([]))
    w = make_worker(queue, runner, vsettings, sim, "voice-a", handle, concurrency=2)
    for i in range(5):
        await queue.enqueue(call_job(i))
    assert await w.run_once() == 2 and w.free_slots == 0
    assert await w.run_once() == 0  # at capacity: nothing more is claimed
    assert await queue.depth() == 3
    gate.set()
    await w.wait_idle(5)
    assert await w.run_once() == 2


async def test_provider_limiter_caps_concurrent_calls(sim, vsettings, fclock, vbus):
    lim = MemoryRateLimiter(concurrency={"telephony": 1, "simulator": 1})
    runner = runner_with(sim, vsettings, fclock, vbus, rate_limiter=lim,
                         policy=ScriptedPolicy([hangup(CallOutcome.PARTIAL, None)]))  # fmt: skip
    runner.slot_timeout_s = 0.05
    async with lim.slot("telephony"):  # another call holds the only slot
        blocked = await runner.run(make_brief(), no_answer_user)
    assert (
        blocked.outcome == CallOutcome.FAILED
        and "limit" in blocked.error
        or "rate" in blocked.error
    )
    assert not sim.legs  # never dialled
    ok = await runner.run(make_brief(), no_answer_user)  # slot released -> works
    assert ok.outcome == CallOutcome.PARTIAL
    async with lim.slot("simulator"):
        capped = await runner.run(make_brief(), no_answer_user)
    assert capped.outcome == CallOutcome.FAILED and "concurrency limit" in capped.error
    assert sim.legs[-1].ended  # the dialled leg was hung up straight away


async def test_graceful_drain_finishes_live_calls_and_refuses_new_ones(
    sim, vsettings, fclock, vbus
):
    from friday.core.models import MidCallQuestion

    gate = asyncio.Event()

    async def slow_user(q):
        await gate.wait()
        return None

    q = MidCallQuestion(task_id="x", text="?", timeout_s=30)
    policy = ScriptedPolicy([CallAction(type=CallActionType.ASK_USER, text="Ek minute ji.", question=q),
                             hangup(CallOutcome.PARTIAL, None)])  # fmt: skip
    runner = runner_with(sim, vsettings, fclock, vbus, policy=policy)
    live = asyncio.create_task(runner.run(make_brief(), slow_user))
    for _ in range(30):
        await asyncio.sleep(0)
    assert runner.live_calls == 1
    drain = asyncio.create_task(runner.drain(timeout_s=5))
    await asyncio.sleep(0)
    refused = await runner.run(make_brief(task_id="late"), no_answer_user)
    assert refused.outcome == CallOutcome.FAILED and "draining" in refused.error
    gate.set()  # the live call finishes normally
    assert (await live).outcome == CallOutcome.PARTIAL
    assert await drain is True and runner.live_calls == 0


async def test_drain_timeout_wraps_up_a_stuck_call(sim, vsettings, fclock, vbus):
    from friday.core.models import MidCallQuestion

    gate = asyncio.Event()

    async def slow_user(q):
        await gate.wait()
        return None

    q = MidCallQuestion(task_id="x", text="?", timeout_s=30)
    policy = ScriptedPolicy(
        [CallAction(type=CallActionType.ASK_USER, text="Ek minute ji.", question=q)]
    )
    runner = runner_with(sim, vsettings, fclock, vbus, policy=policy)
    live = asyncio.create_task(runner.run(make_brief(), slow_user))
    for _ in range(30):
        await asyncio.sleep(0)
    drain = asyncio.create_task(runner.drain(timeout_s=0.01))
    await asyncio.sleep(0.05)
    gate.set()
    assert (await live).outcome == CallOutcome.CANCELLED
    assert await drain is False


async def test_worker_stop_drains_and_pins_stream_urls(sim, vsettings, fclock, vbus):
    queue = MemoryJobQueue(fclock)
    runner = runner_with(sim, vsettings, fclock, vbus, policy=ScriptedPolicy([]))
    tw = TwilioTelephony(account_sid="AC", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(), tts=StubTTS())  # fmt: skip
    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
                          public_base_url="https://f.example.in", secret="x", stt=StubSTT(), tts=StubTTS())  # fmt: skip
    routed = RoutedTelephony([sar, tw])
    handled = []

    async def handle(job):
        handled.append(job.id)
        await queue.ack(job.id)

    w = VoiceWorker(queue=queue, handler=handle, settings=vsettings, runner=runner, telephony=routed,
                    concurrency=2, poll_s=0.01, wid="voice-z")  # fmt: skip
    assert tw.worker_id == sar.worker_id == "voice-z"
    assert "w=voice-z" in tw.media_ws_url and "w=voice-z" in sar.media_ws_url_for("k")
    await queue.enqueue(call_job(1))
    await w.start()
    for _ in range(100):
        if handled:
            break
        await asyncio.sleep(0.01)
    assert await w.stop(drain_s=1) is True and handled
    await queue.enqueue(call_job(2))
    assert await w.run_once() == 0  # stopped: no more claims


async def test_media_socket_on_the_wrong_worker_is_refused(vsettings):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from friday.core.container import Container
    from friday.voice.http import build_router
    from friday.voice.telephony.sarvam import sarvam_token

    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=[], public_base_url="https://f.example.in",
                          secret="x", stt=StubSTT(), tts=StubTTS())  # fmt: skip
    sar.worker_id = "voice-a"
    c = Container(Settings(_env_file=None, public_base_url="https://f.example.in"))
    c.override("telephony", sar)
    app = FastAPI()
    app.include_router(build_router(c), prefix="/voice")
    client = TestClient(app)
    tok = sarvam_token("x", "media:k1")
    with (
        pytest.raises(WebSocketDisconnect) as e,
        client.websocket_connect(f"/voice/sarvam/media?key=k1&token={tok}&w=voice-b") as ws,
    ):
        ws.receive_text()
    assert e.value.code == 1013


# ------------------------------------------------------------------ S-10 shared cache


async def test_tts_renders_are_shared_across_workers():
    shared = MemoryCache()
    a, b = fake_tts(), fake_tts()
    w1, w2 = CachedTTS(a, cache=shared), CachedTTS(b, cache=shared)
    assert await w1.prerender(["Hi, main Friday hoon."], Language.HINGLISH) == 1
    clip, hit = await w2.synthesize_cached("Hi, main Friday hoon.", Language.HINGLISH)
    assert hit and not b.calls and clip.data == b"Hi, main Friday hoon." and w2.billed_chars == 0
    _, hit = await w2.synthesize_cached("Kuch aur.", Language.HINGLISH)
    assert not hit and len(b.calls) == 1


async def test_leg_reports_zero_billed_chars_for_shared_renders():
    shared = MemoryCache()
    first = CachedTTS(StubTTS(), cache=shared)
    await first.prerender(["Hi, main Friday hoon."], Language.HINGLISH)
    rec = TwilioRecorder()
    tw = TwilioTelephony(account_sid="AC", auth_token="t", from_number="+918069110001",
                         public_base_url="https://f.example.in", stt=StubSTT(),
                         tts=CachedTTS(StubTTS(), cache=shared), transport=httpx.MockTransport(rec))  # fmt: skip
    leg = await tw.place_call(OutboundCallRequest(to_phone=LOOKS, task_id="t"))
    await tw.handle_status({"CallSid": leg.provider_call_id, "CallStatus": "in-progress"}, leg.key)
    await start_stream(tw, leg, [], {})
    await leg.wait_for_answer(5)
    await leg.speak("Hi, main Friday hoon.", Language.HINGLISH)
    assert leg.tts_billed_chars == 0
    await leg.speak("Ek nayi line hai.", Language.HINGLISH)
    assert leg.tts_billed_chars == len("Ek nayi line hai.")


async def test_learned_ivr_map_goes_to_the_shared_cache_and_is_replayed(
    sim, vsettings, fclock, vbus
):
    cache = MemoryCache()
    acct = AccountIdentifier(
        user_id="u", company="Airtel", label="Registered mobile", value="9812345678"
    )

    def brief():
        return make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel",
                          care_request=CareRequestKind.COMPLAINT, approved_identifiers=[acct])  # fmt: skip

    keys = lambda d: CallAction(type=CallActionType.PRESS_KEYS, digits=d)  # noqa: E731
    first_policy = ScriptedPolicy([
        keys("2"), keys("3"), keys("9812345678#"), keys("9"),
        CallAction(type=CallActionType.WAIT_ON_HOLD),
        say("I'd like to raise a complaint about my broadband.", Language.EN),
        hangup(CallOutcome.PARTIAL, "Thank you, bye."),
    ])  # fmt: skip
    r1 = await runner_with(sim, vsettings, fclock, vbus, cache=cache, policy=first_policy).run(
        brief(), no_answer_user
    )
    learned = await cache.get("ivr_map:+911800000121")
    assert learned == ["2", "3", "{Registered mobile}#", "9"]  # menu keys only, no raw digits
    assert "9812345678" not in json.dumps(learned)
    assert r1.ivr_keys_replayed == 0

    second_policy = ScriptedPolicy([say("I'd like to raise a complaint.", Language.EN),
                                    hangup(CallOutcome.PARTIAL, "Thank you, bye.")])  # fmt: skip
    r2 = await runner_with(sim, vsettings, fclock, vbus, cache=cache, policy=second_policy).run(
        brief(), no_answer_user
    )
    assert r2.ivr_keys_replayed == 4 and r2.policy_calls == 2  # zero LLM for the menus


# ------------------------------------------------------------------ graceful degradation


def no_bridge(sim):
    sim.capabilities = lambda: frozenset({"outbound", "inbound", "missed_call", "media_stream",
                                          "dtmf", "recording"})  # fmt: skip


async def test_bridge_unsupported_degrades_to_a_callback_pack(make_runner, sim):
    no_bridge(sim)
    bridge = CallAction(type=CallActionType.BRIDGE_USER, text="Connecting Rahul now.")
    policy = ScriptedPolicy([
        say("I'd like to raise a complaint.", Language.EN), bridge, bridge, bridge,
    ])  # fmt: skip
    brief = make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel")
    result = await make_runner(policy).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.NEEDS_USER_VERIFICATION  # final, never retried
    assert result.collected["bridge_unavailable"] == "1"
    assert not sim.legs[-1].children and not sim.legs[-1].left
    assert any("cannot connect the user" in s for s in sys_lines(result))
    # the policy can also exit properly after being told
    exit_ = hangup(CallOutcome.NEEDS_USER_VERIFICATION, "Rahul aapko khud call karenge.")
    result = await make_runner(ScriptedPolicy([bridge, exit_])).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.NEEDS_USER_VERIFICATION


async def test_ivr_task_declines_honestly_when_dtmf_is_unavailable(make_runner, sim):
    sim.capabilities = lambda: frozenset({"outbound", "inbound"})
    policy = ScriptedPolicy([])
    brief = make_brief(AIRTEL, "Airtel", task_type=TaskType.CUSTOMER_CARE, company="Airtel")
    result = await make_runner(policy).run(brief, no_answer_user)
    assert result.outcome == CallOutcome.NEEDS_USER_VERIFICATION
    assert not result.outcome.is_retryable  # the engine reports it instead of re-dialling
    assert result.collected["unsupported_capability"] == "dtmf"
    assert "dtmf" in result.error and not sim.legs  # declined BEFORE dialling
    translator = make_brief(mode=CallMode.TRANSLATOR)
    result = await make_runner(policy).run(translator, no_answer_user)
    assert result.collected["unsupported_capability"] == "media_stream"


async def test_sarvam_dtmf_falls_back_to_in_band_tones():
    calls: list[str] = []

    def handler(r: httpx.Request):
        calls.append(f"{r.method} {r.url.path}")
        if r.url.path.endswith("/DTMF/"):
            return httpx.Response(404, text="no such endpoint")
        return httpx.Response(201, json={"request_uuid": "u1"})

    sar = SarvamTelephony(auth_id="MA", auth_token="t", caller_ids=["+918031110001"],
                          public_base_url="https://f.example.in", secret="x", stt=StubSTT(),
                          tts=StubTTS(), transport=httpx.MockTransport(handler))  # fmt: skip
    sar._http.retries = 0
    leg = await sar.place_call(OutboundCallRequest(to_phone=LOOKS, task_id="t"))
    await sar.answer_xml({"CallUUID": "u1"}, leg.key)
    sent: list[dict] = []

    async def send(text):
        sent.append(json.loads(text))

    await sar.handle_stream_message({"event": "start", "start": {"callId": "u1", "streamId": "s1"}},
                                    send, {}, key=leg.key)  # fmt: skip
    await leg.wait_for_answer(5)
    task = asyncio.create_task(leg.send_dtmf("9"))
    for _ in range(20):
        await asyncio.sleep(0)
        if sent and sent[-1]["event"] == "checkpoint":
            await sar.handle_stream_message({"event": "playedStream", "name": sent[-1]["name"]}, send,
                                            {"leg": leg})  # fmt: skip
    await task
    assert any(p.endswith("/DTMF/") for p in calls) and any(m["event"] == "playAudio" for m in sent)
    assert "bridge_transfer" not in sar.capabilities()
    assert (
        "bridge_transfer"
        in SarvamTelephony(
            auth_id="MA",
            auth_token="t",
            caller_ids=[],
            public_base_url="https://f",
            secret="x",
            stt=StubSTT(),
            tts=StubTTS(),
            enable={"bridge_transfer"},
        ).capabilities()
    )


def test_default_live_telephony_secret_settings_present():
    s = Settings(_env_file=None, sarvam_telephony_auth_token=SecretStr("t"))
    assert s.telephony_route  # core default; the routed builder narrows it to sarvam
