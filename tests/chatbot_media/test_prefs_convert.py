"""Preference commands, turn state, the ffmpeg converter (missing binary, fake, real if present)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from friday.chatbot_media.convert import (
    FakeConverter,
    FfmpegConverter,
    ffmpeg_args,
    ffmpeg_path,
)
from friday.chatbot_media.prefs import TurnState, VoiceState, parse_pref_command
from friday.core.models import AudioClip
from friday.core.scale import MemoryCache


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("text mein reply karo", "text"),
        ("sirf text", "text"),
        ("text hi bhejo", "text"),
        ("voice note mat bhejo", "text"),
        ("voice band karo", "text"),
        ("टेक्स्ट में जवाब दो", "text"),
        ("voice mein reply karo", "voice"),
        ("voice note bhejo", "voice"),
        ("sirf voice", "voice"),
        ("वॉइस में रिप्लाई करो", "voice"),
        ("voice aur text dono", "both"),
        ("dono bhejo", "both"),
        ("jaisa main bhejun waisa reply", "mirror"),
        ("mirror mode", "mirror"),
    ],
)
def test_preference_commands(text: str, mode: str) -> None:
    assert parse_pref_command(text) == mode


@pytest.mark.parametrize(
    "text",
    [
        "kal 2 baje interview hai",
        "mummy ko phone karo",
        "interview ke baad voice note bhejo",  # topic-bound: belongs to the follow-up settings
        "mujhe text message mein ek lamba paragraph likhna hai uske baare mein reply karo please",
        "",
        "hello",
    ],
)
def test_ordinary_messages_are_not_preference_commands(text: str) -> None:
    assert parse_pref_command(text) is None


async def test_state_defaults_and_roundtrip() -> None:
    st = VoiceState(MemoryCache())
    assert await st.mode("u1") == "mirror"
    await st.set_mode("u1", "both")
    assert await st.mode("u1") == "both" and await st.mode("u2") == "mirror"
    assert await st.turn("u1") is None
    now = datetime(2026, 10, 22, 4, 30, tzinfo=UTC)
    await st.set_turn("u1", TurnState(True, "devanagari", "hi", now))
    turn = await st.turn("u1")
    assert turn == TurnState(True, "devanagari", "hi", now)
    await st.clear("u1")
    assert await st.mode("u1") == "mirror" and await st.turn("u1") is None


async def test_fake_converter_paths() -> None:
    clip = AudioClip(data=b"hello", mime="text/plain")
    ok = FakeConverter()
    assert await ok.to_ogg_opus(clip) == b"OggSHello".replace(b"H", b"h")
    assert await FakeConverter(fail=True).to_ogg_opus(clip) is None
    assert not FakeConverter(present=False).available


async def test_missing_ffmpeg_returns_none_and_logs_once(caplog) -> None:
    caplog.set_level(logging.WARNING)
    conv = FfmpegConverter(binary=None)
    conv._binary = None  # a server without ffmpeg, whatever this machine has
    assert not conv.available
    clip = AudioClip(data=b"RIFF....", mime="audio/wav")
    assert await conv.to_ogg_opus(clip) is None
    assert await conv.to_ogg_opus(clip) is None
    assert caplog.text.count("ffmpeg not found") == 1


async def test_an_ogg_clip_passes_through_without_ffmpeg() -> None:
    conv = FfmpegConverter(binary="/definitely/not/here")
    ogg = AudioClip(data=b"OggS\x00data", mime="audio/ogg")
    assert await conv.to_ogg_opus(ogg) == b"OggS\x00data"


async def test_unstartable_ffmpeg_degrades() -> None:
    conv = FfmpegConverter(binary="/definitely/not/here/ffmpeg")
    assert await conv.to_ogg_opus(AudioClip(data=b"RIFFxxxx", mime="audio/wav")) is None


def test_ffmpeg_command_is_a_list_with_opus_voip_mono() -> None:
    args = ffmpeg_args("/usr/bin/ffmpeg")
    assert args[0] == "/usr/bin/ffmpeg" and isinstance(args, list)
    joined = " ".join(args)
    assert "-c:a libopus" in joined and "-ac 1" in joined and "-f ogg" in joined
    assert "pipe:0" in args and "pipe:1" in args and "-application voip" in joined


@pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg is not installed on this machine")
async def test_real_ffmpeg_makes_ogg_opus_from_wav() -> None:
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * 8000)
    out = await FfmpegConverter().to_ogg_opus(AudioClip(data=buf.getvalue(), mime="audio/wav"))
    assert out is not None and out[:4] == b"OggS" and b"OpusHead" in out[:200]
