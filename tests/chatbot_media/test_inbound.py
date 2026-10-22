"""A voice note in: transcript, low-confidence confirmation, preference commands, caps stay."""

from __future__ import annotations

from datetime import UTC, datetime

from friday.channels.simulator import SimulatorChannel
from friday.chatbot_media import copy as vcopy
from friday.chatbot_media.inbound import FakeTranscriber, SttTranscriber, VoiceInbound
from friday.chatbot_media.prefs import VoiceState
from friday.core.clock import FakeClock
from friday.core.models import (
    Channel,
    InboundMessage,
    Language,
    MediaBlob,
    MessageKind,
    Transcription,
    User,
)
from friday.core.scale import MemoryCache

NOW = datetime(2026, 10, 22, 4, 30, tzinfo=UTC)
USER = User(id="u1", phone="+919800000001")


class Rig:
    def __init__(self, transcriber: FakeTranscriber | None = None, *, voice: bool = True) -> None:
        self.clock = FakeClock(NOW)
        self.state = VoiceState(MemoryCache(self.clock))
        self.sim = SimulatorChannel(self.clock)
        self.transcriber = transcriber or FakeTranscriber()
        self.replies: list[tuple[str, list]] = []

        async def reply(user, text, buttons):  # noqa: ANN001
            self.replies.append((text, list(buttons)))

        self.inbound = VoiceInbound(
            state=self.state,
            transcriber=lambda: self.transcriber,
            fetch_media=self.sim.fetch_media,
            reply=reply,
            now=self.clock.now,
            voice_enabled=voice,
        )

    def voice_msg(self, spoken: str, *, mime: str = "audio/ogg") -> InboundMessage:
        media = self.sim.put_media(spoken.encode(), mime, "voice.ogg")
        return InboundMessage(
            channel=Channel.SIMULATOR, from_phone=USER.phone, kind=MessageKind.VOICE_NOTE,
            media_url=media, media_mime=mime,
        )  # fmt: skip

    def text_msg(self, text: str) -> InboundMessage:
        return InboundMessage(channel=Channel.SIMULATOR, from_phone=USER.phone, text=text)

    async def receive(self, msg: InboundMessage) -> InboundMessage | None:
        if msg.kind == MessageKind.VOICE_NOTE:
            msg.text = await self.inbound.transcribe(msg)
        return await self.inbound.on_inbound(USER, msg)


async def test_a_confident_voice_note_becomes_text_for_the_normal_path() -> None:
    r = Rig()
    out = await r.receive(r.voice_msg("kal 2 baje interview hai"))
    assert out is not None and out.text == "kal 2 baje interview hai"
    assert out.kind == MessageKind.VOICE_NOTE and out.raw["from_voice"] is True
    assert r.replies == []  # no "maine suna" when the transcript is confident
    turn = await r.state.turn("u1")
    assert turn is not None and turn.voice


async def test_low_confidence_asks_back_with_two_buttons() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    out = await r.receive(r.voice_msg("kal 2 baje interview hai"))
    assert out is None  # held back until the user says yes
    (text, buttons), = r.replies
    assert text == 'Maine suna: "kal 2 baje interview hai". Sahi hai?'
    assert [b.id for b in buttons] == ["vn:ok", "vn:no"]
    assert all(len(b.title) <= 20 for b in buttons)


async def test_yes_sends_the_transcript_on_as_voice() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    await r.receive(r.voice_msg("kal 2 baje interview hai"))
    tap = InboundMessage(
        channel=Channel.SIMULATOR, from_phone=USER.phone, kind=MessageKind.BUTTON_REPLY,
        button_id="vn:ok", text="Haan, sahi",
    )  # fmt: skip
    out = await r.inbound.on_inbound(USER, tap)
    assert out is not None and out.text == "kal 2 baje interview hai"
    assert out.kind == MessageKind.VOICE_NOTE and out.button_id is None
    assert (await r.state.turn("u1")).voice  # type: ignore[union-attr]


async def test_no_asks_to_send_again_and_forgets_the_transcript() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    await r.receive(r.voice_msg("kal 2 baje interview hai"))
    r.replies.clear()
    tap = InboundMessage(
        channel=Channel.SIMULATOR, from_phone=USER.phone, kind=MessageKind.BUTTON_REPLY,
        button_id="vn:no", text="Nahi",
    )  # fmt: skip
    assert await r.inbound.on_inbound(USER, tap) is None
    assert r.replies[0][0] == vcopy.ROMAN["heard_retry"]
    # a second tap finds nothing pending
    assert await r.inbound.on_inbound(USER, tap) is None
    assert r.replies[-1][0] == vcopy.ROMAN["heard_expired"]


async def test_a_pending_confirmation_expires() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    await r.receive(r.voice_msg("kal 2 baje interview hai"))
    r.clock.advance(minutes=11)
    tap = InboundMessage(
        channel=Channel.SIMULATOR, from_phone=USER.phone, kind=MessageKind.BUTTON_REPLY,
        button_id="vn:ok",
    )  # fmt: skip
    assert await r.inbound.on_inbound(USER, tap) is None
    assert r.replies[-1][0] == vcopy.ROMAN["heard_expired"]


async def test_the_transcript_is_not_in_the_shared_cache() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    await r.receive(r.voice_msg("mera khaas raaz"))
    cache = r.state.cache
    for key in ("vn:pend:u1", "vn:pref:u1", "vn:turn:u1"):
        assert "khaas raaz" not in repr(await cache.get(key))


async def test_devanagari_speaker_gets_devanagari_prompts() -> None:
    r = Rig(FakeTranscriber(confidence=0.3))
    await r.receive(r.voice_msg("कल 2 बजे इंटरव्यू है"))
    assert r.replies[0][0] == 'मैंने सुना: "कल 2 बजे इंटरव्यू है"। सही है?'
    assert r.replies[0][1][0].title == "हाँ, सही"


async def test_empty_or_failed_transcription_asks_to_resend() -> None:
    for tr in (FakeTranscriber(fail=True), FakeTranscriber(text="")):
        r = Rig(tr)
        assert await r.receive(r.voice_msg("x")) is None
        assert r.replies[0][0] == vcopy.ROMAN["not_understood"]


async def test_too_long_voice_note_is_refused_kindly() -> None:
    r = Rig(FakeTranscriber(too_long=True))
    assert await r.receive(r.voice_msg("x")) is None
    assert r.replies[0][0] == vcopy.ROMAN["too_long"]


async def test_download_failure_asks_to_resend() -> None:
    r = Rig()
    msg = r.voice_msg("x")
    msg.media_url = "sim-media:unknown"
    assert await r.receive(msg) is None
    assert r.replies[0][0] == vcopy.ROMAN["not_understood"]


async def test_preference_command_is_answered_and_not_passed_on() -> None:
    r = Rig()
    out = await r.receive(r.text_msg("text mein reply karo"))
    assert out is None and r.replies[0][0] == vcopy.ROMAN["pref_text"]
    assert await r.state.mode("u1") == "text"
    r.replies.clear()
    assert await r.receive(r.text_msg("voice note bhejo")) is None
    assert r.replies[0][0] == vcopy.ROMAN["pref_voice"]
    assert await r.state.mode("u1") == "voice"
    await r.receive(r.text_msg("jaisa main bhejun waisa reply"))
    assert await r.state.mode("u1") == "mirror"


async def test_a_spoken_preference_command_works_too() -> None:
    r = Rig()
    assert await r.receive(r.voice_msg("sirf text")) is None
    assert await r.state.mode("u1") == "text"
    assert r.replies[0][0] == vcopy.ROMAN["pref_text"]


async def test_a_doubtful_spoken_command_is_confirmed_first() -> None:
    r = Rig(FakeTranscriber(confidence=0.2))
    assert await r.receive(r.voice_msg("sirf text")) is None
    assert await r.state.mode("u1") == "mirror"  # not changed on a doubtful transcript
    assert r.replies[0][0].startswith("Maine suna")


async def test_a_typed_message_marks_the_turn_as_text() -> None:
    r = Rig()
    await r.receive(r.voice_msg("hello"))
    assert (await r.state.turn("u1")).voice  # type: ignore[union-attr]
    out = await r.receive(r.text_msg("kal 2 baje interview hai"))
    assert out is not None and out.text == "kal 2 baje interview hai"
    assert not (await r.state.turn("u1")).voice  # type: ignore[union-attr]


async def test_with_the_voice_switch_off_only_the_script_is_remembered() -> None:
    r = Rig(voice=False)
    out = await r.receive(r.text_msg("text mein reply karo"))
    assert out is not None and r.replies == []  # not a command while voice is off
    turn = await r.state.turn("u1")
    assert turn is not None and not turn.voice and turn.script == "roman"
    out = await r.receive(r.text_msg("कल 2 बजे इंटरव्यू है"))
    assert (await r.state.turn("u1")).script == "devanagari"  # type: ignore[union-attr]


class _Stt:
    """The existing STT provider shape: returns a Transcription."""

    name = "stub"
    supported_languages = frozenset({Language.HINGLISH})

    async def transcribe(self, audio, *, language_hint=None):  # noqa: ANN001
        return Transcription(text=audio.data.decode(), language=Language.HI, confidence=0.9)


async def test_stt_transcriber_wraps_the_existing_provider() -> None:
    t = await SttTranscriber(_Stt()).transcribe(MediaBlob(data="नमस्ते".encode(), mime="audio/ogg"))
    assert t.text == "नमस्ते" and t.language == "hi" and t.confidence == 0.9
