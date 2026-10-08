"""Sarvam AI text-to-speech (Bulbul). Calm female voices for Indian languages.

REST: ``POST https://api.sarvam.ai/text-to-speech`` (JSON) -> ``{"audios": [b64 wav]}``.
Models: ``bulbul:v3`` (default) or ``bulbul:v4-flash`` (see constants below).
Text is filler-stripped and chunked on sentence boundaries (vendor length limit);
chunks are concatenated into one WAV. ``speech_sample_rate`` defaults to 8 kHz -
telephony quality, no resampling needed for Twilio.
"""

from __future__ import annotations

import base64
import os
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

# VERIFIED (docs.sarvam.ai/api-reference/text-to-speech/convert, 2026-10-08): bulbul:v2 is
# deprecated (HTTP 400). ``bulbul:v3`` is the stable API default (short speaker names, pace
# 0.5-2.0, temperature, NO pitch / loudness / enable_preprocessing). ``bulbul:v4-flash`` has the
# same contract but speakers are personas ``<name>_<lang>_<style>``; v3 short names are invalid.
DEFAULT_MODEL = "bulbul:v3"
# Founder decision: calm FEMALE voice only. Female bulbul:v3 speakers (docs list; gender per
# the Voices guide / founder review).
SARVAM_FEMALE_SPEAKERS = frozenset({
    "priya", "ritu", "neha", "simran", "kavya", "ishita", "shreya", "roopa", "pooja",
    "tanya", "shruti", "suhani", "kavitha", "rupali",
})  # fmt: skip
DEFAULT_FEMALE_SPEAKER = "ritu"  # tested live 2026-10-08, see docs/SARVAM_QUESTIONS.md
# First names of v4-flash personas that are female (persona = name_lang_style).
_V4_FEMALE_NAMES = SARVAM_FEMALE_SPEAKERS | frozenset({
    "aditi", "aparna", "chandrika", "nupur", "sanchita", "shabana", "shalini", "zarina",
    "amelia", "sophia", "payal", "chhavi", "sarika", "suchitra", "shilpa", "aarti", "suman",
    "vandana", "chaitra",
})  # fmt: skip
# Default female v4-flash persona per language (only languages the docs list a female one for).
V4_DEFAULT_PERSONAS: dict[Language, str] = {
    Language.EN: "simran_en_customer",
    Language.HI: "ritu_hi_customer",
    Language.HINGLISH: "simran_enhi_customer",
    Language.BN: "roopa_bn_conversational",
    Language.GU: "pooja_gu_conversational",
    Language.MR: "rupali_mr_stories",
    Language.TE: "kavitha_te_conversation",
    Language.KN: "chaitra_kn_conversation",
}
SAMPLE_RATES = (8000, 16000, 22050, 24000)
MAX_CHARS = 450  # docs allow 2500 for v3 / v4-flash; short chunks keep time-to-first-audio low


def is_v4(model: str) -> bool:
    return model.startswith("bulbul:v4")


def _persona_languages(language: Language) -> frozenset[str]:
    base = sarvam_code(language).split("-")[0]
    return frozenset({"en", "enhi", "hi"}) if language == Language.HINGLISH else frozenset({base})


def is_female_speaker(
    speaker: str, model: str = DEFAULT_MODEL, language: Language | None = None
) -> bool:
    sp = speaker.lower()
    if is_v4(model):
        parts = sp.split("_")
        if len(parts) < 3 or parts[0] not in _V4_FEMALE_NAMES:
            return False
        return language is None or parts[1] in _persona_languages(language)
    return sp in SARVAM_FEMALE_SPEAKERS


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
        model: str = DEFAULT_MODEL,
        temperature: float | None = None,
        sample_rate: int = 8000,
        base_url: str = SARVAM_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.catalog = catalog
        self.model = model
        self.temperature = temperature
        if sample_rate not in SAMPLE_RATES:
            raise ValueError(f"sarvam TTS sample rate must be one of {SAMPLE_RATES}")
        self.sample_rate = sample_rate
        self._http = VendorHTTP(
            "sarvam",
            base_url=base_url,
            headers={"api-subscription-key": api_key},
            transport=transport,
        )

    def model_for(self, language: Language) -> str:
        """v4-flash only has female personas for some languages; others use v3 for that call."""
        if is_v4(self.model) and language not in V4_DEFAULT_PERSONAS:
            return DEFAULT_MODEL
        return self.model

    def voice_for(self, language: Language) -> VoiceProfile:
        profile = self.catalog.profile(language)
        model = self.model_for(language)
        if not is_female_speaker(profile.voice_id, model, language):
            fallback = (
                V4_DEFAULT_PERSONAS[language] if is_v4(model) else DEFAULT_FEMALE_SPEAKER
            )
            log.info(
                "sarvam speaker %r is not a known female %s voice; using %s",
                profile.voice_id,
                model,
                fallback,
            )
            profile = profile.model_copy(update={"voice_id": fallback})
        return profile

    def payload(self, text: str, language: Language, voice: VoiceProfile) -> dict:
        model = self.model_for(language)
        pace = min(2.0, max(0.5, voice.speaking_rate))
        body = {
            "text": text,
            "target_language_code": sarvam_code(language),
            "speaker": voice.voice_id.lower(),
            "model": model,
            "pace": pace,
            "speech_sample_rate": self.sample_rate,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        return body

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
    # Settings has no model field yet (proposed in docs/CORE_CHANGES.md): use it when core adds
    # it, else the FRIDAY_SARVAM_TTS_MODEL env var, else the stable default.
    model = (
        getattr(s, "sarvam_tts_model", None)
        or os.environ.get("FRIDAY_SARVAM_TTS_MODEL")
        or DEFAULT_MODEL
    )
    # A leftover bulbul:v2 name (the old Settings default "anushka") falls back in voice_for.
    default = (s.sarvam_tts_speaker or DEFAULT_FEMALE_SPEAKER).lower()
    if not is_v4(model) and not is_female_speaker(default, model):
        default = DEFAULT_FEMALE_SPEAKER
    catalog = VoiceCatalog("sarvam", s, {}, default)
    return SarvamTTS(s.sarvam_api_key.get_secret_value(), catalog, model=model)
