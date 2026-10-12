"""ElevenLabs text-to-speech (Flash v2.5, multilingual incl. Hindi & Tamil).

REST: ``POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_16000``
with ``xi-api-key``. High ``stability`` and zero ``style`` exaggeration keep the voice
calm and even; text is filler-stripped first. Voice ids come from
``ELEVENLABS_VOICE_ID`` / ``FRIDAY_TTS_VOICES`` and must be female voices.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.models import AudioClip, Language, VoiceProfile
from friday.voice._http import VendorHTTP
from friday.voice.audio import pcm16_to_wav
from friday.voice.langs import VoiceCatalog
from friday.voice.text import strip_fillers
from friday.voice.tts.sarvam import TTSStreamError

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
# ElevenLabs premade "Rachel" - calm, female. Override with ELEVENLABS_VOICE_ID.
DEFAULT_FEMALE_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
_LANG_CODES = {Language.EN: "en", Language.HI: "hi", Language.HINGLISH: "hi", Language.TA: "ta"}


class ElevenLabsTTS:
    name = "elevenlabs"
    supported_languages: frozenset[Language] = frozenset(_LANG_CODES)

    def __init__(
        self,
        api_key: str,
        catalog: VoiceCatalog,
        *,
        model: str = "eleven_flash_v2_5",
        sample_rate: int = 16000,
        streaming: bool = True,
        base_url: str = ELEVENLABS_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.catalog = catalog
        self.streaming = streaming  # live calls: first audio ~170 ms (docs/LATENCY.md)
        self.stream_rate = 8000  # telephony rate: no resampling on the call leg
        self.model = model
        self.sample_rate = sample_rate
        self._http = VendorHTTP(
            "elevenlabs",
            base_url=base_url,
            headers={"xi-api-key": api_key},
            transport=transport,
        )

    def voice_for(self, language: Language) -> VoiceProfile:
        return self.catalog.profile(language)

    def payload(self, text: str, language: Language, voice: VoiceProfile) -> dict:
        return {
            "text": text,
            "model_id": self.model,
            "language_code": _LANG_CODES.get(language, "en"),
            "voice_settings": {
                "stability": 0.75,  # even, calm delivery
                "similarity_boost": 0.8,
                "style": 0.0,  # no dramatic/"humanising" exaggeration
                "use_speaker_boost": True,
                "speed": voice.speaking_rate,
            },
        }

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        clean = strip_fillers(text)
        profile = voice or self.voice_for(language)
        if not clean:
            return AudioClip(data=pcm16_to_wav(b"", self.sample_rate), sample_rate=self.sample_rate)
        resp = await self._http.request(
            "POST",
            f"/v1/text-to-speech/{profile.voice_id}",
            params={"output_format": f"pcm_{self.sample_rate}"},
            json=self.payload(clean, language, profile),
        )
        return AudioClip(
            data=pcm16_to_wav(resp.content, self.sample_rate),
            mime="audio/wav",
            sample_rate=self.sample_rate,
        )

    async def synthesize_stream(
        self, text: str, language: Language, voice: VoiceProfile | None = None
    ) -> AsyncIterator[bytes]:
        """Yield 8 kHz PCM16 mono pieces while ElevenLabs is still making the line.

        ``POST /v1/text-to-speech/{voice}/stream?output_format=pcm_8000``. Raises
        ``TTSStreamError`` (``resume_text`` = what is still unspoken) so the call leg can fall
        back to the plain request."""
        clean = strip_fillers(text)
        if not clean:
            return
        profile = voice or self.voice_for(language)
        got = False
        carry = b""
        try:
            async with self._http._client.stream(
                "POST",
                f"/v1/text-to-speech/{profile.voice_id}/stream",
                params={"output_format": f"pcm_{self.stream_rate}"},
                json=self.payload(clean, language, profile),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                async for raw in resp.aiter_bytes():
                    data = carry + raw
                    n = len(data) // 2 * 2  # whole 16-bit samples only
                    carry = data[n:]
                    if n:
                        got = True
                        yield data[:n]
                if not got:
                    raise ValueError("stream ended without audio")
        except (httpx.HTTPError, ValueError) as e:
            raise TTSStreamError(
                f"elevenlabs streaming failed: {type(e).__name__}: {str(e)[:160]}",
                resume_text="" if got else clean,
                audio_started=got,
            ) from e

    async def aclose(self) -> None:
        await self._http.aclose()


def build_elevenlabs_tts(c: Container) -> ElevenLabsTTS:
    s = c.settings
    if not s.elevenlabs_api_key:
        raise ProviderError("elevenlabs", "ELEVENLABS_API_KEY not set")
    catalog = VoiceCatalog("elevenlabs", s, {}, s.elevenlabs_voice_id or DEFAULT_FEMALE_VOICE_ID)
    primary = ElevenLabsTTS(
        s.elevenlabs_api_key.get_secret_value(),
        catalog,
        model=s.elevenlabs_model,
        streaming=s.elevenlabs_streaming,
    )
    if s.tts_fallback == "sarvam" and s.sarvam_api_key:
        from friday.voice.tts.fallback import FallbackTTS
        from friday.voice.tts.sarvam import build_sarvam_tts

        return FallbackTTS(primary, build_sarvam_tts(c))  # type: ignore[return-value]
    return primary
