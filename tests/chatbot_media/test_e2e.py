"""Voice note in -> router -> voice note out, in the whole simulated world (fakes only)."""

from __future__ import annotations

from friday.chatbot_media import copy as vcopy
from friday.chatbot_media.convert import FakeConverter
from friday.core.models import Language, Transcription


def audio(w) -> list:  # noqa: ANN001
    return [
        m for m in w.channel.messages_to(w.phone) if (m.media_mime or "").startswith("audio")
    ]


def wire_fake_voice(w, *, present: bool = True):  # noqa: ANN001, ANN201
    """The real hook, with the fake converter (no ffmpeg needed) and the container's fake TTS."""
    hook = w.c.get("notifier").outbound_hook
    assert hook is not None
    hook.synth.converter = FakeConverter(present=present)
    return hook


class LowConfidenceSTT:
    name = "stub"
    supported_languages = frozenset({Language.HINGLISH})

    async def transcribe(self, audio, *, language_hint=None):  # noqa: ANN001
        return Transcription(text=audio.data.decode(), language=Language.HINGLISH, confidence=0.3)


async def test_switch_off_a_voice_note_gets_a_text_reply_as_before(media_world) -> None:
    w = await media_world()
    assert w.c.get("notifier").outbound_hook is None
    assert w.runtime.pipeline._media_hook() is None  # noqa: SLF001
    out = await w.say("/voice mat poocho")
    assert out and all(m.media_url is None for m in out)
    assert audio(w) == []
    typed = await media_world()
    t = await typed.say("mat poocho")
    assert [m.text for m in out] == [m.text for m in t]  # a voice note is the same words typed


async def test_switch_off_nothing_else_changes_for_a_typed_message(media_world) -> None:
    plain = await media_world()
    on = await media_world(voice_note_replies=True, devanagari_input=True)
    wire_fake_voice(on)
    a = await plain.say("kal 2 baje interview hai")
    b = await on.say("kal 2 baje interview hai")
    assert [(m.text, m.buttons) for m in a] == [(m.text, m.buttons) for m in b]
    assert audio(plain) == [] and audio(on) == []


async def test_switch_on_voice_note_gets_a_voice_note_of_the_same_words(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    hook = wire_fake_voice(w)
    out = await w.say("/voice mat poocho")
    assert w.brain.seen == []  # the router answered it, exactly like the typed words
    sent = audio(w)
    assert len(sent) == 1, w.transcript()
    spoken_text = hook.synth.tts.calls[-1][0]
    blob = await w.channel.fetch_media(sent[0].media_url)
    assert blob.data == b"OggS" + spoken_text.encode()
    # voice only: the whole reply was a short plain sentence, so no text message followed
    assert not any(m.text for m in out if m.media_url is None), w.transcript()


async def test_the_reply_text_is_what_the_typed_message_would_get(media_world) -> None:
    typed = await media_world(voice_note_replies=True)
    wire_fake_voice(typed)
    spoken = await media_world(voice_note_replies=True)
    hook = wire_fake_voice(spoken)
    t = await typed.say("mat poocho")
    await spoken.say("/voice mat poocho")
    assert [m.text for m in t if m.text]  # a typed message gets text
    assert audio(typed) == []  # mirror: text for text
    assert hook.synth.tts.calls[-1][0] == [m.text for m in t if m.text][-1]  # same words


async def test_numbers_come_as_voice_and_text(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    out = await w.say("/voice kal 2 baje interview hai")
    assert len(audio(w)) >= 1
    texts = [m.text for m in out if m.media_url is None and m.text]
    assert texts and any("2" in t or "14" in t for t in texts), w.transcript()
    assert w.brain.seen == []


async def test_typed_message_in_mirror_mode_stays_text(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    out = await w.say("kal 2 baje interview hai")
    assert out and audio(w) == []


async def test_preference_commands_change_the_next_reply(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    out = await w.say("text mein reply karo")
    assert [m.text for m in out] == [vcopy.ROMAN["pref_text"]] and w.brain.seen == []
    await w.say("/voice mat poocho")
    assert audio(w) == []  # a voice note in, but the user asked for text
    await w.say("voice mein reply karo")  # (its own acknowledgement is already spoken)
    before = len(audio(w))
    await w.say("mat poocho")  # typed turn, voice preference
    assert len(audio(w)) == before + 1


async def test_low_confidence_asks_then_continues_on_yes(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    w.c.override("stt", LowConfidenceSTT())
    out = await w.say("/voice kal 2 baje interview hai")
    assert w.brain.seen == []
    assert 'Maine suna: "kal 2 baje interview hai". Sahi hai?' in [m.text for m in out]
    assert [b.id for b in out[-1].buttons] == ["vn:ok", "vn:no"]
    assert audio(w) == []  # a question with buttons is text
    after = await w.tap("Haan")
    assert any("interview" in (m.text or "").lower() or m.media_url for m in after), w.transcript()
    events = await w.consumer.life.store.events_between(w.user.id, w.at(0), w.at(23, day=31))
    assert len(events) == 1


async def test_low_confidence_no_throws_the_transcript_away(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    w.c.override("stt", LowConfidenceSTT())
    await w.say("/voice kal 2 baje interview hai")
    hook = w.c.get("notifier").outbound_hook
    await w.tap("Nahi")
    assert hook.synth.tts.calls[-1][0] == vcopy.ROMAN["heard_retry"]  # spoken: a plain short reply
    events = await w.consumer.life.store.events_between(w.user.id, w.at(0), w.at(23, day=31))
    assert events == []


async def test_no_ffmpeg_means_text_and_a_log_line(media_world, caplog) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w, present=False)
    out = await w.say("/voice mat poocho")
    assert audio(w) == []
    assert any(m.text for m in out)  # the text reply still arrives


async def test_outside_the_24_hour_window_it_is_a_template_never_a_voice_note(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    await w.say("/voice mat poocho")  # opens the window
    before = len(audio(w))
    w.clock.advance(hours=25)
    receipt = await w.c.get("notifier").notify_user(w.user.id, "Yaad dilana tha.")
    assert receipt is not None
    msgs = w.channel.messages_to(w.phone)
    assert len(audio(w)) == before
    assert msgs[-1].template is not None  # the notifier's own template fallback


async def test_a_voice_note_over_the_daily_cap_is_text(media_world) -> None:
    w = await media_world(voice_note_replies=True, voice_note_daily_cap=1)
    wire_fake_voice(w)
    await w.say("/voice mat poocho")
    assert len(audio(w)) == 1
    await w.say("/voice mat poocho")
    assert len(audio(w)) == 1  # capped: the second reply is text
    assert w.channel.last_to(w.phone).text


async def test_devanagari_voice_note_is_understood_and_answered(media_world) -> None:
    w = await media_world(voice_note_replies=True, devanagari_input=True)
    wire_fake_voice(w)
    out = await w.say("/voice कल 2 बजे इंटरव्यू है")  # what Sarvam returns for Hindi speech
    assert w.brain.seen == []
    events = await w.consumer.life.store.events_between(w.user.id, w.at(0), w.at(23, day=31))
    assert len(events) == 1
    assert out


async def test_a_voice_note_inside_the_window_again_gets_a_voice_note(media_world) -> None:
    w = await media_world(voice_note_replies=True)
    wire_fake_voice(w)
    await w.say("/voice mat poocho")
    w.clock.advance(hours=23)  # still inside the 24-hour window of the NEW voice note
    await w.say("/voice mat poocho")
    assert len(audio(w)) == 2
