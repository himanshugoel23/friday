"""Sarvam AI text-to-speech (Bulbul). Calm female voices for Indian languages.

REST: ``POST https://api.sarvam.ai/text-to-speech`` (JSON) -> ``{"audios": [b64 wav]}``.
Text is filler-stripped and chunked on sentence boundaries (vendor length limit);
chunks are concatenated into one WAV. ``speech_sample_rate`` defaults to 8 kHz -
telephony quality, no resampling needed for Twilio.
"""

from __future__ import annotations

import base64
import re

import httpx

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.core.models import AudioClip, Language, VoiceProfile
from friday.voice._http import VendorHTTP
from friday.voice.audio import pcm16_to_wav, resample_pcm16, wav_to_pcm16
from friday.voice.langs import SARVAM_LANGUAGES, VoiceCatalog, sarvam_code
from friday.voice.stt.sarvam import SARVAM_BASE_URL
from friday.voice.text import strip_fillers

log = get_logger(__name__)

SARVAM_FEMALE_SPEAKERS = frozenset({"anushka", "manisha", "vidya", "arya"})
DEFAULT_FEMALE_SPEAKER = "anushka"
MAX_CHARS = 450


def chunk_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    sentences = re.split(r"(?<=[.!?।])\s+", text.strip())
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        while len(s) > limit:  # pathological long sentence
            chunks.append(s[:limit])
            s = s[limit:]
        if len(cur) + len(s) + 1 > limit and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


class SarvamTTS:
    name = "sarvam"
    supported_languages: frozenset[Language] = SARVAM_LANGUAGES

    def __init__(
        self,
        api_key: str,
        catalog: VoiceCatalog,
        *,
        model: str = "bulbul:v2",
        sample_rate: int = 8000,
        base_url: str = SARVAM_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.catalog = catalog
        self.model = model
        self.sample_rate = sample_rate
        self._http = VendorHTTP(
            "sarvam",
            base_url=base_url,
            headers={"api-subscription-key": api_key},
            transport=transport,
        )

    def voice_for(self, language: Language) -> VoiceProfile:
        profile = self.catalog.profile(language)
        if profile.voice_id.lower() not in SARVAM_FEMALE_SPEAKERS:
            log.warning(
                "sarvam speaker %r is not a known female voice; using %s",
                profile.voice_id,
                DEFAULT_FEMALE_SPEAKER,
            )
            profile = profile.model_copy(update={"voice_id": DEFAULT_FEMALE_SPEAKER})
        return profile

    def payload(self, text: str, language: Language, voice: VoiceProfile) -> dict:
        return {
            "text": text,
            "target_language_code": sarvam_code(language),
            "speaker": voice.voice_id.lower(),
            "model": self.model,
            "pace": voice.speaking_rate,
            "pitch": 0,
            "loudness": 1.0,
            "speech_sample_rate": self.sample_rate,
            "enable_preprocessing": True,  # numbers/dates read naturally
        }

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        clean = strip_fillers(text)
        if not clean:
            return AudioClip(data=pcm16_to_wav(b"", self.sample_rate), sample_rate=self.sample_rate)
        profile = voice or self.voice_for(language)
        pcm = bytearray()
        for chunk in chunk_text(clean):
            resp = await self._http.request(
                "POST", "/text-to-speech", json=self.payload(chunk, language, profile)
            )
            try:
                audios = resp.json()["audios"]
                wav = base64.b64decode(audios[0])
            except (ValueError, KeyError, IndexError) as e:
                raise ProviderError("sarvam", "unexpected text-to-speech response") from e
            part, rate = wav_to_pcm16(wav)
            pcm += resample_pcm16(part, rate, self.sample_rate)
        return AudioClip(
            data=pcm16_to_wav(bytes(pcm), self.sample_rate),
            mime="audio/wav",
            sample_rate=self.sample_rate,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def build_sarvam_tts(c: Container) -> SarvamTTS:
    s = c.settings
    if not s.sarvam_api_key:
        raise ProviderError("sarvam", "SARVAM_API_KEY not set")
    default = (s.sarvam_tts_speaker or DEFAULT_FEMALE_SPEAKER).lower()
    catalog = VoiceCatalog("sarvam", s, {}, default)
    return SarvamTTS(s.sarvam_api_key.get_secret_value(), catalog)
