"""ElevenLabs text-to-speech (Flash v2.5, multilingual incl. Hindi & Tamil).

REST: ``POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_16000``
with ``xi-api-key``. High ``stability`` and zero ``style`` exaggeration keep the voice
calm and even; text is filler-stripped first. Voice ids come from
``ELEVENLABS_VOICE_ID`` / ``FRIDAY_TTS_VOICES`` and must be female voices.
"""

from __future__ import annotations

import httpx

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.models import AudioClip, Language, VoiceProfile
from friday.voice._http import VendorHTTP
from friday.voice.audio import pcm16_to_wav
from friday.voice.langs import VoiceCatalog
from friday.voice.text import strip_fillers

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
        base_url: str = ELEVENLABS_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.catalog = catalog
        self.model = model
        self.sample_rate = sample_rate
        self._http = VendorHTTP(
            "elevenlabs", base_url=base_url, headers={"xi-api-key": api_key},
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
            data=pcm16_to_wav(resp.content, self.sample_rate), mime="audio/wav",
            sample_rate=self.sample_rate,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def build_elevenlabs_tts(c: Container) -> ElevenLabsTTS:
    s = c.settings
    if not s.elevenlabs_api_key:
        raise ProviderError("elevenlabs", "ELEVENLABS_API_KEY not set")
    catalog = VoiceCatalog("elevenlabs", s, {}, s.elevenlabs_voice_id or DEFAULT_FEMALE_VOICE_ID)
    return ElevenLabsTTS(s.elevenlabs_api_key.get_secret_value(), catalog)
