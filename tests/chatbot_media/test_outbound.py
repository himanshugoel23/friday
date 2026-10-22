"""The outbound hook: voice note or text, script mirroring, every failure degrading to text."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from friday.channels.simulator import SimulatorChannel
from friday.chatbot_media import copy as vcopy
from friday.chatbot_media.convert import FakeConverter
from friday.chatbot_media.ledger import VoiceLedger
from friday.chatbot_media.outbound import OutboundHooks
from friday.chatbot_media.prefs import TurnState, VoiceState
from friday.chatbot_media.speech import VoiceSynthesizer
from friday.core.clock import FakeClock
from friday.core.config import Settings
from friday.core.models import (
    AudioClip,
    Channel,
    Language,
    OutboundMessage,
    ReplyButton,
    TemplateRef,
    VoiceProfile,
)
from friday.core.scale import MemoryCache

PHONE = "+919800000001"
NOW = datetime(2026, 10, 22, 4, 30, tzinfo=UTC)


class RecordingTTS:
    name = "rec"
    supported_languages = frozenset(Language)

    def __init__(self) -> None:
        self.spoken: list[tuple[str, Language]] = []

    def voice_for(self, language: Language) -> VoiceProfile:
        return VoiceProfile(provider="rec", voice_id=f"rec-{language.value}", language=language)

    async def synthesize(self, text: str, language: Language, *, voice=None) -> AudioClip:  # noqa: ANN001
        self.spoken.append((text, language))
        return AudioClip(data=text.encode(), mime="text/plain")


class NoMediaChannel:  # a channel with no upload method
    channel = Channel.WHATSAPP


class BrokenUploadChannel(SimulatorChannel):
    async def upload_media(self, data, mime, filename="voice.ogg"):  # noqa: ANN001
        raise RuntimeError("upload down")


class Rig:
    def __init__(self, *, channel=None, converter=None, devanagari=False, cap=10, **sw) -> None:  # noqa: ANN001
        self.clock = FakeClock(NOW)
        self.settings = Settings(
            _env_file=None, voice_note_replies=True, devanagari_input=devanagari,
            voice_note_daily_cap=cap, **sw,
        )  # fmt: skip
        self.cache = MemoryCache(self.clock)
        self.state = VoiceState(self.cache)
        self.channel = channel or SimulatorChannel(self.clock)
        self.tts = RecordingTTS()
        self.converter = converter or FakeConverter()
        self.synth = VoiceSynthesizer(self.tts, self.converter)
        self.ledger = VoiceLedger(self.cache, self.clock, daily_cap=cap, cost_per_1k_chars_inr=3.0)
        self.hooks = OutboundHooks(
            settings=self.settings, clock=self.clock, state=self.state, ledger=self.ledger,
            synth=self.synth, channel=self.channel,
        )  # fmt: skip

    async def turn(self, *, voice: bool, script: str = "roman", age_s: int = 0) -> None:
        at = self.clock.now() - timedelta(seconds=age_s)
        await self.state.set_turn("u1", TurnState(voice, script, None, at))  # type: ignore[arg-type]

    def msg(self, text: str | None = "Theek hai, ho gaya.", **kw) -> OutboundMessage:  # noqa: ANN003
        return OutboundMessage(
            channel=Channel.WHATSAPP, to_phone=PHONE, user_id="u1", text=text, **kw
        )

    def audio_sent(self) -> list[OutboundMessage]:
        sent = self.channel.messages_to(PHONE)
        return [m for m in sent if (m.media_mime or "").startswith("audio")]


async def test_voice_turn_short_reply_is_one_voice_note_of_the_same_words() -> None:
    r = Rig()
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert out.spoke and out.suppress_text and out.receipt is not None and out.receipt.ok
    assert r.tts.spoken == [("Theek hai, ho gaya.", Language.HINGLISH)]  # the SAME words
    (audio,) = r.audio_sent()
    assert audio.media_mime == "audio/ogg; codecs=opus" and audio.media_url
    blob = await r.channel.fetch_media(audio.media_url)
    assert blob.data == b"OggS" + b"Theek hai, ho gaya." and blob.mime == "audio/ogg; codecs=opus"


async def test_numbers_buttons_and_links_also_go_as_text() -> None:
    r = Rig()
    await r.turn(voice=True)
    for text, buttons in [
        ("Kal 2 baje ka interview likh liya.", []),
        ("Theek hai.", [ReplyButton(id="life:1:ok", title="Sahi hai")]),
        ("Link: https://example.com/pay", []),
    ]:
        out = await r.hooks.before_send(r.msg(text, buttons=buttons))
        assert out.spoke and not out.suppress_text, text
        assert out.msg.text == text and out.msg.buttons == buttons  # the text message is intact


async def test_a_typed_turn_gets_text_only_in_mirror_mode() -> None:
    r = Rig()
    await r.turn(voice=False)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and not out.suppress_text and r.tts.spoken == []
    assert out.reason == "mirror_text_turn"


async def test_text_preference_wins_over_a_voice_note() -> None:
    r = Rig()
    await r.turn(voice=True)
    await r.state.set_mode("u1", "text")
    assert not (await r.hooks.before_send(r.msg())).spoke


async def test_voice_preference_speaks_a_typed_turn() -> None:
    r = Rig()
    await r.turn(voice=False)
    await r.state.set_mode("u1", "voice")
    assert (await r.hooks.before_send(r.msg())).spoke


async def test_both_preference_sends_voice_and_text() -> None:
    r = Rig()
    await r.turn(voice=True)
    await r.state.set_mode("u1", "both")
    out = await r.hooks.before_send(r.msg())
    assert out.spoke and not out.suppress_text


async def test_approval_is_never_voice_only_nor_spoken() -> None:
    r = Rig()
    await r.turn(voice=True)
    await r.state.set_mode("u1", "both")
    buttons = [ReplyButton(id="callap:r1:yes", title="Approve")]
    out = await r.hooks.before_send(r.msg("Mummy ko call karun?", buttons=buttons))
    assert not out.spoke and not out.suppress_text and r.tts.spoken == []


async def test_a_private_reply_is_not_read_aloud_to_a_typed_turn() -> None:
    r = Rig()
    await r.turn(voice=False)
    await r.state.set_mode("u1", "voice")
    out = await r.hooks.before_send(r.msg("HDFC Regalia sabse accha rahega."))
    assert not out.spoke and r.tts.spoken == []
    await r.turn(voice=True)  # asked by voice in this turn: allowed
    assert (await r.hooks.before_send(r.msg("HDFC Regalia sabse accha rahega."))).spoke


async def test_a_long_reply_stays_text() -> None:
    r = Rig()
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg("Yeh lamba jawab hai. " * 40))
    assert not out.spoke and out.reason == "too_long" and r.tts.spoken == []


async def test_outside_the_window_never_a_voice_note() -> None:
    r = Rig()
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg(), in_window=False)
    assert not out.spoke and r.audio_sent() == []


async def test_templates_media_and_non_user_messages_are_untouched() -> None:
    r = Rig()
    await r.turn(voice=True)
    tpl = r.msg(None, template=TemplateRef(key="nudge", params=["a", "b"], language="en"))
    media = r.msg(media_url="M1", media_mime="audio/ogg")
    person = r.msg(person_id="p1")
    business = r.msg(business_id="b1")
    no_user = OutboundMessage(channel=Channel.WHATSAPP, to_phone=PHONE, text="hi")
    for m in (tpl, media, person, business, no_user):
        out = await r.hooks.before_send(m)
        assert out.msg is m and not out.spoke
    assert r.tts.spoken == []


async def test_an_old_turn_does_not_count_as_a_voice_turn() -> None:
    r = Rig()
    await r.turn(voice=True, age_s=11 * 60)
    assert not (await r.hooks.before_send(r.msg())).spoke


async def test_identical_replies_are_synthesised_and_uploaded_once() -> None:
    r = Rig()
    await r.turn(voice=True)
    await r.hooks.before_send(r.msg())
    await r.hooks.before_send(r.msg())
    assert len(r.tts.spoken) == 1 and len(r.converter.calls) == 1
    audio = r.audio_sent()
    assert len(audio) == 2 and audio[0].media_url == audio[1].media_url  # one upload, two sends
    assert len(r.channel._media) == 1  # noqa: SLF001
    cost = await r.ledger.cost_today()
    assert cost.replies == 2 and cost.cache_hits == 1 and cost.synthesised_chars == 19


async def test_daily_cap_then_text(caplog) -> None:
    caplog.set_level(logging.INFO)
    r = Rig(cap=2)
    await r.turn(voice=True)
    results = [await r.hooks.before_send(r.msg(f"Jawab number {'x' * i}.")) for i in range(4)]
    assert [o.spoke for o in results] == [True, True, False, False]
    assert results[2].reason == "daily_cap"
    assert await r.ledger.used_today("u1") == 2
    assert "voice reply skipped: daily cap reached" in caplog.text
    r.clock.advance(days=1)  # the next IST day starts again
    await r.turn(voice=True)
    assert (await r.hooks.before_send(r.msg("Naya din."))).spoke


async def test_cost_log_per_day(caplog) -> None:
    caplog.set_level(logging.INFO)
    r = Rig()
    await r.turn(voice=True)
    await r.hooks.before_send(r.msg("A" * 100))
    cost = await r.ledger.cost_today()
    assert cost.replies == 1 and cost.synthesised_chars == 100
    assert cost.est_inr == pytest.approx(0.3)
    assert "voice reply cost" in caplog.text and "est_inr=0.30" in caplog.text
    assert "AAAA" not in caplog.text  # the reply text never reaches the log


async def test_no_ffmpeg_falls_back_to_text(caplog) -> None:
    caplog.set_level(logging.INFO)
    r = Rig(converter=FakeConverter(present=False))
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and not out.suppress_text and r.tts.spoken == []
    assert out.msg.text == "Theek hai, ho gaya."


async def test_conversion_failure_falls_back_to_text() -> None:
    r = Rig(converter=FakeConverter(fail=True))
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and not out.suppress_text and r.audio_sent() == []
    assert await r.ledger.used_today("u1") == 0  # a failed voice reply costs no cap


async def test_tts_error_falls_back_to_text() -> None:
    r = Rig()

    async def boom(text, language, *, voice=None):  # noqa: ANN001
        raise RuntimeError("tts down")

    r.tts.synthesize = boom  # type: ignore[method-assign]
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and not out.suppress_text


async def test_channel_without_media_upload_falls_back_to_text() -> None:
    r = Rig(channel=NoMediaChannel())
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and out.reason == "voice_unavailable"


async def test_upload_error_falls_back_to_text() -> None:
    r = Rig(channel=BrokenUploadChannel())
    await r.turn(voice=True)
    out = await r.hooks.before_send(r.msg())
    assert not out.spoke and not out.suppress_text and out.reason == "upload_failed"
    assert await r.ledger.used_today("u1") == 0


async def test_devanagari_user_gets_the_devanagari_variant_when_one_exists() -> None:
    r = Rig(devanagari=True)
    await r.turn(voice=False, script="devanagari")
    roman = vcopy.ROMAN["pref_text"]
    out = await r.hooks.before_send(r.msg(roman))
    assert out.msg.text == vcopy.DEVANAGARI["pref_text"]
    other = await r.hooks.before_send(r.msg("A line without a Devanagari variant."))
    assert other.msg.text == "A line without a Devanagari variant."  # falls back to Roman


async def test_script_mirroring_is_off_with_its_switch_off() -> None:
    r = Rig(devanagari=False)
    await r.turn(voice=False, script="devanagari")
    out = await r.hooks.before_send(r.msg(vcopy.ROMAN["pref_text"]))
    assert out.msg.text == vcopy.ROMAN["pref_text"]


async def test_the_voice_speaks_the_devanagari_text_the_user_will_read() -> None:
    r = Rig(devanagari=True)
    await r.turn(voice=True, script="devanagari")
    await r.hooks.before_send(r.msg(vcopy.ROMAN["pref_text"]))
    assert r.tts.spoken[0][0] == vcopy.DEVANAGARI["pref_text"]
    assert r.tts.spoken[0][1] == Language.HI


async def test_a_hook_bug_never_loses_the_message(caplog) -> None:
    caplog.set_level(logging.WARNING)
    r = Rig()

    async def boom(user_id):  # noqa: ANN001
        raise RuntimeError("cache down")

    r.state.turn = boom  # type: ignore[method-assign]
    out = await r.hooks.before_send(r.msg())
    assert out.msg.text == "Theek hai, ho gaya." and not out.suppress_text
    assert "outbound hook failed" in caplog.text


def test_speech_cache_is_a_bounded_lru_and_media_ids_expire() -> None:
    from friday.chatbot_media.speech import MEDIA_ID_TTL, SpeechCache

    cache = SpeechCache(max_items=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    assert cache.get("a") == b"1"  # a is now the newest
    cache.put("c", b"3")
    assert cache.get("b") is None and cache.get("a") == b"1" and cache.get("c") == b"3"
    cache.put_media_id("a", "M1", NOW)
    assert cache.media_id("a", NOW + MEDIA_ID_TTL - timedelta(seconds=1)) == "M1"
    assert cache.media_id("a", NOW + MEDIA_ID_TTL + timedelta(seconds=1)) is None


async def test_cache_key_depends_on_text_and_language() -> None:
    r = Rig()
    k1 = r.synth.key_for("hello", Language.EN)
    assert k1 == r.synth.key_for("hello", Language.EN)
    assert k1 != r.synth.key_for("hello!", Language.EN)
    assert k1 != r.synth.key_for("hello", Language.HI)
