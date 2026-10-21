# ruff: noqa: E501
"""Stream the model's reply into the voice: first sentence early, per-sentence guards, fallbacks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from friday.brain.fake_llm import FakeLLM
from friday.brain.openai_llm import OpenAILLM
from friday.brain.sarvam_llm import RoutedLLM, SarvamLLM
from friday.brain.service import FridayBrain
from friday.core.clock import IST
from friday.core.config import Settings
from friday.core.interfaces import LLMMessage, ProviderError
from friday.core.models import (
    CallActionType,
    CallBrief,
    ContactTarget,
    Language,
    Speaker,
    TargetKind,
    TaskType,
    Transcript,
)
from friday.latency.stream_adapters import (
    FakeStreamingLLM,
    OpenAIChatStream,
    SarvamChatStream,
    json_chunks,
    streaming_for,
)
from friday.latency.streaming import (
    JsonFieldStream,
    RepeatGuard,
    SentenceSplitter,
    stream_to_voice,
)
from friday.voice.session import _Session

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=IST)


# --------------------------------------------------------------------------- sentences
def _split_all(text: str, step: int | None = None, **kw: Any) -> list[str]:
    sp = SentenceSplitter(**kw)
    out: list[str] = []
    if step is None:
        out += sp.feed(text)
    else:
        for i in range(0, len(text), step):
            out += sp.feed(text[i : i + step])
    return out + sp.flush()


def test_splitter_splits_on_terminators_and_merges_short_pieces():
    assert _split_all("Ji, namaste. Main Rahul ji ke liye rate poochh rahi hoon. Kya aap bata sakte hain?") == [
        "Ji, namaste. Main Rahul ji ke liye rate poochh rahi hoon.",
        "Kya aap bata sakte hain?",
    ]
    assert _split_all("हाँ जी, बताइए आप कौन बोल रहे हैं। मैं फ्राइडे हूँ और कॉल कर रही हूँ।") == [
        "हाँ जी, बताइए आप कौन बोल रहे हैं।", "मैं फ्राइडे हूँ और कॉल कर रही हूँ।"]


def test_splitter_keeps_numbers_and_times_whole():
    got = _split_all("Shaam 10.30 baje aa jaiye aur Rs.400 dena hoga. Theek hai ji, shukriya aapka.")
    assert got == ["Shaam 10.30 baje aa jaiye aur Rs.400 dena hoga.", "Theek hai ji, shukriya aapka."]


@pytest.mark.parametrize("step", [1, 2, 5, 11])
def test_splitter_gives_the_same_pieces_however_the_text_arrives(step):
    text = "Ji, main dekhti hoon abhi. Aapko kal shaam 6 baje chalega kya? Theek hai, phir baat karte hain."
    assert _split_all(text, step) == _split_all(text)


def test_splitter_waits_for_text_after_a_full_stop_and_cuts_long_clauses():
    sp = SentenceSplitter(min_chars=5)
    assert sp.feed("Ji haan sir kal aa jaiye.") == []  # a "." at the very end may be "10." + "30"
    assert sp.feed(" Phir") == ["Ji haan sir kal aa jaiye."]
    assert sp.feed(" milte hain?") == ["Phir milte hain?"]  # "?" is final at once
    long = "Ji main aapko bata dun ki hum kal subah aa sakte hain, lekin shaam ko thoda mushkil hoga"
    parts = _split_all(long, clause_chars=60, min_chars=10)
    assert parts[0].endswith(",") and " ".join(parts) == long


# --------------------------------------------------------------------------- JSON text field
def _field(raw: str, key: str = "text", step: int = 1) -> tuple[str, JsonFieldStream]:
    f, out = JsonFieldStream(key), []
    for i in range(0, len(raw), step):
        out.append(f.feed(raw[i : i + step]))
    return "".join(out), f


@pytest.mark.parametrize("step", [1, 3, 100])
def test_json_field_decodes_escapes_unicode_and_collects_type(step):
    raw = json.dumps({"type": "say", "text": 'Ji "haan"\nकल aa jaiye हाँ', "language": "hinglish"})
    text, f = _field(raw, step=step)
    assert text == 'Ji "haan"\nकल aa jaiye हाँ'
    assert f.strings == {"type": "say", "language": "hinglish"} and f.target_done and not f.broken


def test_json_field_skips_nested_values_and_non_string_fields():
    raw = '{"collected":[{"key":"text","value":"not me"}],"commits_booking":false,"type":"say","care":{"text":"nor me"},"text":"yes me","n":null}'
    text, f = _field(raw)
    assert text == "yes me" and f.strings["type"] == "say"


def test_json_field_text_before_type_and_null_text():
    text, f = _field('{"text":"pehle text","type":"say"}')
    assert text == "pehle text" and f.strings == {"type": "say"}
    text, f = _field('{"type":"wait","text":null}')
    assert text == "" and f.strings == {"type": "wait"}


def test_json_field_never_raises_on_garbage():
    f = JsonFieldStream("text")
    assert f.feed('{"text" 5}') == "" and f.broken
    assert f.feed("more") == ""


# --------------------------------------------------------------------------- the runner
REPLY = {
    "type": "say",
    "text": "Ji namaste, main Rahul ji ke liye haircut ka rate poochh rahi hoon. "
            "Kya aap batayenge? Main phir se call nahi karungi.",
    "language": "hinglish",
    "commits_booking": False,
}


async def _run(chunks_src: FakeStreamingLLM, check=None, **kw: Any):
    spoken_at: list[tuple[str, int]] = []

    async def speak(s: str) -> None:
        spoken_at.append((s, chunks_src.yielded))

    res = await stream_to_voice(
        chunks_src.stream(), speak=speak, check=check or (lambda s, a: None), **kw
    )
    return res, spoken_at


async def test_tts_starts_on_the_first_sentence_while_the_rest_is_still_being_written():
    chunks = json_chunks(json.dumps(REPLY), 5)
    fake = FakeStreamingLLM(chunks, delay_s=0.002)
    res, spoken_at = await _run(fake)
    assert res.reason is None and res.complete and len(res.spoken) == 3
    first_sentence, chunks_read_when_spoken = spoken_at[0]
    assert first_sentence.startswith("Ji namaste") and first_sentence.endswith("rahi hoon.")
    assert chunks_read_when_spoken < len(chunks)  # spoken BEFORE the model finished writing
    assert res.first_sentence_ms is not None and res.first_sentence_ms < res.total_ms
    assert " ".join(res.spoken) == res.text  # nothing lost, nothing added
    assert fake.closed == 1


async def test_speech_waits_for_type_say_and_never_streams_other_actions():
    fake = FakeStreamingLLM(json_chunks(json.dumps({**REPLY, "type": "hangup"}), 7))
    res, spoken_at = await _run(fake)
    assert spoken_at == [] and res.reason == "gate:hangup" and res.complete  # whole reply collected
    assert json.loads(res.raw)["type"] == "hangup"
    # text first, type last: nothing is spoken until the type is known, then it is
    swapped = json.dumps({"text": REPLY["text"], "type": "say"})
    fake = FakeStreamingLLM(json_chunks(swapped, 9))
    res, spoken_at = await _run(fake)
    assert res.reason is None and len(res.spoken) == 3
    assert spoken_at[0][1] >= len(fake.chunks) - 2  # had to wait for the type at the very end


async def test_a_failing_sentence_stops_the_stream_and_nothing_after_it_is_spoken():
    chunks = json_chunks(json.dumps(REPLY), 5)
    fake = FakeStreamingLLM(chunks, delay_s=0.001)

    def check(sentence: str, accepted):
        return "ungrounded number" if sentence.startswith("Kya aap") else None

    res, spoken_at = await _run(fake, check=check)
    assert [s for s, _ in spoken_at] == [res.accepted[0]] and len(res.spoken) == 1
    assert res.reason == "guard: ungrounded number" and res.failed_sentence.startswith("Kya aap")
    assert fake.closed == 1 and fake.yielded < len(chunks)  # the model was cancelled


async def test_barge_in_stops_speaking_the_rest():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), delay_s=0.001)
    stopped = {"v": False}
    spoken: list[str] = []

    async def speak(s: str) -> None:
        spoken.append(s)
        stopped["v"] = True  # the caller starts talking over her after sentence 1

    res = await stream_to_voice(fake.stream(), speak=speak, check=lambda s, a: None,
                                should_stop=lambda: stopped["v"])
    assert len(spoken) == 1 and res.reason == "barge_in"


async def test_a_stream_error_before_any_sentence_is_reported_for_fallback():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), fail_at=0)
    res, spoken_at = await _run(fake)
    assert spoken_at == [] and res.reason == "error: ProviderError" and not res.complete


async def test_a_stream_error_mid_reply_keeps_what_was_said_and_replays_nothing():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), fail_at=20, delay_s=0.001)
    res, spoken_at = await _run(fake)
    assert res.reason == "error: ProviderError" and not res.complete
    assert len(res.spoken) == 1  # only the sentence that had been completed and checked


async def test_a_voice_failure_propagates_and_stops_the_model():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), delay_s=0.001)

    async def speak(_s: str) -> None:
        raise RuntimeError("call ended")

    with pytest.raises(RuntimeError, match="call ended"):
        await stream_to_voice(fake.stream(), speak=speak, check=lambda s, a: None)
    assert fake.closed == 1


async def test_plain_text_streams_work_without_json():
    async def gen():
        for part in ("Ji haan, main dekh ", "leti hoon abhi. Aap ", "line par rahiye."):
            yield part

    said: list[str] = []

    async def speak(s: str) -> None:
        said.append(s)

    res = await stream_to_voice(gen(), speak=speak, check=lambda s, a: None, text_field=None)
    assert said == ["Ji haan, main dekh leti hoon abhi.", "Aap line par rahiye."] and res.reason is None


def test_repeat_guard_is_the_per_sentence_version_of_the_repeat_rule():
    g = RepeatGuard(["Kal shaam 6 baje free hain kya aap?", "Kal shaam 6 baje free hain kya aap?"])
    assert g("Kal shaam 6 baje free hain kya aap?") == "repeating herself"  # said twice already
    g1 = RepeatGuard(["Kal shaam 6 baje free hain kya aap?"])
    assert g1("Kal shaam 6 baje free hain kya aap?") is None  # said once: a second time is allowed
    assert g1("kal shaam 6 baje FREE hain kya aap") == "repeats a sentence of this reply"


# --------------------------------------------------------------------------- the brain
def _brief(task_type: TaskType = TaskType.ENQUIRY) -> CallBrief:
    return CallBrief(
        task_id="t1", requester_user_id="u1", task_type=task_type,
        goal="Ask the price of a haircut", on_behalf_of="Rahul",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon", phone="+918040000001"),
    )


def _transcript(*friday_lines: str) -> Transcript:
    tr = Transcript()
    for line in friday_lines:
        tr.add(Speaker.FRIDAY, line, at=NOW)
        tr.add(Speaker.CALLEE, "haan boliye", at=NOW)
    tr.add(Speaker.CALLEE, "haan ji haircut ka kya poochna tha", at=NOW)
    return tr


class CountingLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.completes = 0

    async def complete(self, **kw: Any):
        self.completes += 1
        return await super().complete(**kw)


def _brain(stream: FakeStreamingLLM | None, *, on: bool = True) -> tuple[FridayBrain, CountingLLM]:
    llm = CountingLLM()
    settings = Settings(_env_file=None, mode="simulator", env="test", anthropic_api_key=None,
                        openai_api_key=None, llm_stream_to_tts=on)
    brain = FridayBrain(llm, settings)
    brain.streaming_llm = stream
    return brain, llm


async def _streamed(brain: FridayBrain, brief: CallBrief, tr: Transcript, **kw: Any):
    said: list[str] = []

    async def speak(s: str) -> None:
        said.append(s)

    turn = await brain.next_call_action_streamed(brief, tr, [], speak=speak, **kw)
    return turn, said


async def test_brain_streams_a_free_form_reply_and_makes_one_model_request():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), delay_s=0.001)
    brain, llm = _brain(fake)
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert " ".join(said) == REPLY["text"] and turn.spoken == said and not turn.fell_back
    assert turn.action.type == CallActionType.WAIT  # everything is already spoken: just listen
    assert llm.completes == 0 and len(fake.calls) == 1  # the streamed request IS the model call
    call = fake.calls[0]
    assert call["purpose"] == "call_turn" and call["json_schema"]["type"] == "object"
    assert turn.result.first_sentence_ms is not None


async def test_brain_blocks_an_invented_price_sentence_and_uses_the_safe_line():
    bad = {**REPLY, "text": "Ji namaste, main Rahul ji ke liye rate poochh rahi hoon. "
                            "Haircut 450 rupaye lagega aapko. Aap kal aa sakte hain kya sir?"}
    fake = FakeStreamingLLM(json_chunks(json.dumps(bad), 5), delay_s=0.001)
    brain, llm = _brain(fake)
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert said == ["Ji namaste, main Rahul ji ke liye rate poochh rahi hoon."]  # sentence 2 never spoken
    assert "450" not in " ".join(said)
    assert turn.action.type in (CallActionType.HANGUP, CallActionType.BRIDGE_USER)
    assert "share nahi kar sakti" in turn.action.text  # the existing fixed safe line
    assert "guard" in turn.action.collected and fake.yielded < len(fake.chunks) and fake.closed == 1


async def test_brain_blocks_a_commitment_sentence():
    bad = {**REPLY, "text": "Ji namaste, main Rahul ji ke liye rate poochh rahi hoon. "
                            "Theek hai main payment kar dungi abhi."}
    brain, _ = _brain(FakeStreamingLLM(json_chunks(json.dumps(bad), 5)))
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert len(said) == 1 and turn.action.type == CallActionType.HANGUP


async def test_no_repeated_line_when_she_already_said_it_twice():
    line = "Ji namaste, main Rahul ji ke liye haircut ka rate poochh rahi hoon."
    reply = {**REPLY, "text": line}
    brain, _ = _brain(FakeStreamingLLM(json_chunks(json.dumps(reply), 5)))
    tr = _transcript(line, line)
    turn, said = await _streamed(brain, _brief(), tr)
    assert said == [] and turn.action.type == CallActionType.HANGUP
    assert turn.action.collected.get("guard") == "repeating_herself"
    # once is fine to say again
    brain, _ = _brain(FakeStreamingLLM(json_chunks(json.dumps(reply), 5)))
    turn, said = await _streamed(brain, _brief(), _transcript(line))
    assert said == [line]
    # the same sentence twice in ONE reply: the second is stopped
    twice = {**REPLY, "text": f"{line} {line}"}
    brain, _ = _brain(FakeStreamingLLM(json_chunks(json.dumps(twice), 5)))
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert said == [line]


async def test_stream_error_before_the_first_sentence_falls_back_to_the_normal_call():
    brain, llm = _brain(FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), fail_at=0))
    tr = _transcript("Hello, main Friday.")
    turn, said = await _streamed(brain, _brief(), tr)
    plain = await brain.next_call_action(_brief(), tr, [])
    assert turn.fell_back and said == [] and turn.spoken == []
    assert (turn.action.type, turn.action.text) == (plain.type, plain.text)
    assert llm.completes >= 1  # the ordinary non-streaming request ran


async def test_stream_error_after_a_sentence_ends_the_reply_there_without_a_second_request():
    brain, llm = _brain(FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), fail_at=20, delay_s=0.001))
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert len(said) == 1 and turn.action.type == CallActionType.WAIT and not turn.fell_back
    assert llm.completes == 0  # nothing is replayed or asked again


async def test_a_reply_that_is_not_say_is_collected_and_handled_by_the_normal_guards():
    ask = {"type": "hangup", "text": "Theek hai, dhanyavaad, main sir ko bata dungi.",
           "outcome": "partial", "language": "hinglish"}
    fake = FakeStreamingLLM(json_chunks(json.dumps(ask), 6))
    brain, llm = _brain(fake)
    turn, said = await _streamed(brain, _brief(), _transcript("Hello, main Friday."))
    assert said == [] and turn.action.type == CallActionType.HANGUP and not turn.fell_back
    assert "dhanyavaad" in turn.action.text
    assert llm.completes == 0 and len(fake.calls) == 1  # one request, not two


async def test_barge_in_leaves_the_rest_unspoken_and_listens():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), delay_s=0.001)
    brain, _ = _brain(fake)
    flag = {"v": False}
    said: list[str] = []

    async def speak(s: str) -> None:
        said.append(s)
        flag["v"] = True

    turn = await brain.next_call_action_streamed(
        _brief(), _transcript("Hello, main Friday."), [], speak=speak, should_stop=lambda: flag["v"]
    )
    assert len(said) == 1 and turn.action.type == CallActionType.WAIT


async def test_calls_that_must_not_commit_do_not_stream():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5))
    brain, llm = _brain(fake)
    turn, said = await _streamed(brain, _brief(TaskType.QUOTE), _transcript("Hello, main Friday."))
    assert turn.fell_back and said == [] and fake.calls == [] and llm.completes >= 1


async def test_switch_off_or_no_client_is_the_ordinary_call():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5))
    brain, llm = _brain(fake, on=False)
    tr = _transcript("Hello, main Friday.")
    turn, said = await _streamed(brain, _brief(), tr)
    plain = await brain.next_call_action(_brief(), tr, [])
    assert turn.fell_back and said == [] and fake.calls == []
    assert (turn.action.type, turn.action.text) == (plain.type, plain.text)
    brain2, _ = _brain(None, on=True)
    turn2, said2 = await _streamed(brain2, _brief(), tr)
    assert turn2.fell_back and said2 == []


async def test_zero_llm_paths_are_not_streamed():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5))
    brain, _ = _brain(fake)
    tr = Transcript()
    tr.add(Speaker.FRIDAY, "Hello, main Friday.", at=NOW)
    tr.add(Speaker.CALLEE, "your call is important to us, please hold", at=NOW)  # hold wording
    turn, said = await _streamed(brain, _brief(), tr)
    assert turn.fell_back and fake.calls == []


# --------------------------------------------------------------------------- the call session
async def test_session_speaks_streamed_sentences_records_one_turn_and_returns_the_action():
    fake = FakeStreamingLLM(json_chunks(json.dumps(REPLY), 5), delay_s=0.001)
    brain, _ = _brain(fake)
    spoken_on_leg: list[tuple[str, Any]] = []

    class Leg:
        barged = False

        async def speak(self, text: str, lang: Any) -> None:
            spoken_on_leg.append((text, lang))

    recorded: list[tuple[Any, str]] = []

    async def record(speaker: Any, text: str, lang: Any, **kw: Any) -> None:
        recorded.append((speaker, text))

    brief, tr = _brief(), _transcript("Hello, main Friday.")
    sess = SimpleNamespace(
        r=SimpleNamespace(policy=brain), leg=Leg(), settings=brain.settings, brief=brief,
        transcript=tr, answers=[], tts_chars=0, committed=False, _stream_policy_ms=None,
        _speak_lang=lambda lang: lang, _lang=lambda: Language.HINGLISH, _record=record,
    )
    action = await _Session._next_action(sess, stream=True)  # type: ignore[arg-type]
    assert [t for t, _ in spoken_on_leg] and " ".join(t for t, _ in spoken_on_leg) == REPLY["text"]
    assert recorded == [(Speaker.FRIDAY, REPLY["text"])]  # ONE turn, so the repeat rule still works
    assert action.type == CallActionType.WAIT and sess._stream_policy_ms is not None
    assert sess.tts_chars == len(REPLY["text"]) - (len(spoken_on_leg) - 1)  # joins add the spaces


async def test_session_off_switch_never_calls_the_streamed_method():
    class Policy:
        streamed_calls = 0

        async def next_call_action(self, *a: Any) -> str:
            return "plain"

        async def next_call_action_streamed(self, *a: Any, **k: Any) -> Any:
            Policy.streamed_calls += 1

    settings = Settings(_env_file=None)
    sess = SimpleNamespace(r=SimpleNamespace(policy=Policy()), leg=object(), settings=settings,
                           brief=_brief(), transcript=Transcript(), answers=[])
    assert await _Session._next_action(sess, stream=True) == "plain"  # type: ignore[arg-type]
    assert Policy.streamed_calls == 0
    on = SimpleNamespace(**{**sess.__dict__, "settings": Settings(_env_file=None, llm_stream_to_tts=True)})
    assert await _Session._next_action(on, stream=False) == "plain"  # type: ignore[arg-type]
    assert Policy.streamed_calls == 0  # hang-up handling never streams


# --------------------------------------------------------------------------- adapters
def _openai_stream_client(deltas: list[str | None], fail: bool = False):
    created: dict[str, Any] = {}

    async def create(**kw: Any):
        created.update(kw)
        if fail:
            raise RuntimeError("boom")

        async def gen():
            for d in deltas:
                yield SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=d, refusal=None), finish_reason=None)])
            yield SimpleNamespace(choices=[], usage=None)
        return gen()

    client = SimpleNamespace(
        with_options=lambda **kw: SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))
    )
    return client, created


async def test_openai_adapter_streams_deltas_with_the_same_request_shape():
    client, created = _openai_stream_client(['{"type":"sa', 'y","text":"Ji haan."}', None])
    llm = OpenAILLM(api_key="k", client=client, relaxed_call_schema=True)
    chunks = [c async for c in OpenAIChatStream(llm).stream(
        system="rules", messages=[LLMMessage(role="user", content="hi")], purpose="call_turn",
        max_tokens=100, json_schema={"type": "object", "properties": {"type": {}, "text": {}},
                                     "required": ["type", "text"]})]
    assert "".join(chunks) == '{"type":"say","text":"Ji haan."}'
    assert created["stream"] is True and created["response_format"]["json_schema"]["strict"] is False
    assert created["messages"][0]["role"] == "system" and created["prompt_cache_key"] == "friday:call_turn"


async def test_openai_adapter_normalises_errors_so_the_brain_can_fall_back():
    client, _ = _openai_stream_client([], fail=True)
    llm = OpenAILLM(api_key="k", client=client)
    with pytest.raises(ProviderError):
        async for _ in OpenAIChatStream(llm).stream(system="s", messages=[], purpose="call_turn"):
            pass


async def test_sarvam_adapter_parses_the_event_stream():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        sse = "".join(
            f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}\n\n"
            for d in ('{"type":"say",', '"text":"Ji."}')
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    llm = SarvamLLM("k", transport=httpx.MockTransport(handler))
    got = [c async for c in SarvamChatStream(llm).stream(
        system="rules", messages=[LLMMessage(role="user", content="hi")], purpose="call_turn",
        max_tokens=50, json_schema={"type": "object", "properties": {"text": {}}})]
    assert "".join(got) == '{"type":"say","text":"Ji."}'
    assert seen["body"]["stream"] is True and seen["body"]["max_tokens"] >= 160


async def test_sarvam_adapter_http_error_is_a_provider_error():
    llm = SarvamLLM("k", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(ProviderError):
        async for _ in SarvamChatStream(llm).stream(system="s", messages=[], purpose="call_turn"):
            pass


def test_streaming_for_picks_the_client_that_serves_call_turns():
    openai = OpenAILLM(api_key="k", client=object())
    sarvam = SarvamLLM("k")
    assert isinstance(streaming_for(openai), OpenAIChatStream)
    assert isinstance(streaming_for(RoutedLLM(openai, sarvam, frozenset({"call_turn"}))), SarvamChatStream)
    assert isinstance(streaming_for(RoutedLLM(openai, sarvam, frozenset({"other"}))), OpenAIChatStream)
    assert streaming_for(FakeLLM()) is None


async def test_fake_streaming_llm_is_deterministic_and_counts_closes():
    fake = FakeStreamingLLM(["a", "b", "c"])
    assert [c async for c in fake.stream()] == ["a", "b", "c"] and fake.closed == 1
    fake2 = FakeStreamingLLM(["a", "b"], fail_at=1)
    with pytest.raises(ProviderError):
        async for _ in fake2.stream():
            pass
    assert asyncio.iscoroutinefunction(stream_to_voice)
