"""ElevenLabs streaming into the call, and the Sarvam spare (no network: mock transport)."""

from __future__ import annotations

import httpx
import pytest

from friday.core.config import Settings
from friday.core.interfaces import ProviderError
from friday.core.models import AudioClip, Language
from friday.voice.langs import VoiceCatalog
from friday.voice.tts.elevenlabs import ElevenLabsTTS
from friday.voice.tts.fallback import FallbackTTS
from friday.voice.tts.sarvam import TTSStreamError


def make(handler, **kw):
    cat = VoiceCatalog("elevenlabs", Settings(), {}, "VOICEID")
    return ElevenLabsTTS("k", cat, transport=httpx.MockTransport(handler), **kw)


PCM = b"\x01\x00" * 400  # 400 samples


async def collect(agen):
    return b"".join([c async for c in agen])


async def test_stream_yields_whole_samples_from_the_stream_endpoint():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(200, content=PCM + b"\x07")  # odd trailing byte must not be emitted

    tts = make(handler)
    out = await collect(tts.synthesize_stream("Hello ji", Language.HINGLISH))
    assert out == PCM
    assert "/v1/text-to-speech/VOICEID/stream" in seen["url"] and "pcm_8000" in seen["url"]
    assert tts.streaming is True


async def test_stream_error_before_audio_asks_for_the_whole_line_again():
    tts = make(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(TTSStreamError) as ei:
        await collect(tts.synthesize_stream("Namaste ji", Language.HINGLISH))
    assert ei.value.resume_text == "Namaste ji" and not ei.value.audio_started


async def test_streaming_can_be_switched_off():
    assert make(lambda r: httpx.Response(200), streaming=False).streaming is False


class Spare:
    name = "sarvam"
    supported_languages = frozenset({Language.HINGLISH})

    def __init__(self):
        self.calls = 0

    async def synthesize(self, text, language, *, voice=None):
        self.calls += 1
        assert voice is None  # the spare uses its own voice, never the primary's id
        return AudioClip(data=b"RIFFspare", sample_rate=8000)


async def test_fallback_speaks_with_the_spare_when_the_primary_fails():
    primary = make(lambda r: httpx.Response(503, text="down"))
    primary._http.retries = 0
    spare = Spare()
    tts = FallbackTTS(primary, spare)
    clip = await tts.synthesize("Namaste", Language.HINGLISH)
    assert clip.data == b"RIFFspare" and spare.calls == 1 and tts.fallbacks == 1
    assert tts.streaming is True and tts.name == "elevenlabs"
    assert tts.voice_for(Language.HINGLISH).voice_id == "VOICEID"


async def test_fallback_does_not_hide_a_failing_spare():
    class BadSpare(Spare):
        async def synthesize(self, *a, **k):
            raise ProviderError("sarvam", "also down")

    primary = make(lambda r: httpx.Response(503, text="down"))
    primary._http.retries = 0
    with pytest.raises(ProviderError):
        await FallbackTTS(primary, BadSpare()).synthesize("x", Language.HINGLISH)
