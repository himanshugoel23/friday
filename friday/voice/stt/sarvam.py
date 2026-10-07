"""Sarvam AI speech-to-text (Saarika). Indian languages incl. code-mixed Hinglish.

REST: ``POST https://api.sarvam.ai/speech-to-text`` (multipart ``file``), header
``api-subscription-key``. ``language_code="unknown"`` asks Sarvam to DETECT the
language, which we map back to ``Language`` (Roman-script Hindi -> HINGLISH).
"""

from __future__ import annotations

import httpx

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.models import AudioClip, Language, Transcription
from friday.voice._http import VendorHTTP
from friday.voice.langs import SARVAM_LANGUAGES, from_vendor_code, refine_hindi, sarvam_code
from friday.voice.text import detect_language

SARVAM_BASE_URL = "https://api.sarvam.ai"


def _filename(audio: AudioClip) -> tuple[str, str]:
    mime = (audio.mime or "audio/wav").split(";")[0]
    ext = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/mpeg": "mp3",
           "audio/mp4": "m4a", "audio/webm": "webm", "audio/flac": "flac"}.get(mime, "wav")  # fmt: skip
    return f"audio.{ext}", mime


class SarvamSTT:
    name = "sarvam"
    supported_languages: frozenset[Language] = SARVAM_LANGUAGES

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "saarika:v2.5",
        base_url: str = SARVAM_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._http = VendorHTTP(
            "sarvam",
            base_url=base_url,
            headers={"api-subscription-key": api_key},
            transport=transport,
        )

    async def transcribe(
        self, audio: AudioClip, *, language_hint: Language | None = None
    ) -> Transcription:
        name, mime = _filename(audio)
        # "unknown" = auto-detect; we always want the DETECTED language (mirroring).
        data = {"model": self.model, "language_code": "unknown"}
        resp = await self._http.request(
            "POST", "/speech-to-text", data=data, files={"file": (name, audio.data, mime)}
        )
        try:
            body = resp.json()
        except ValueError as e:
            raise ProviderError("sarvam", "invalid JSON from speech-to-text") from e
        text = (body.get("transcript") or "").strip()
        lang = from_vendor_code(body.get("language_code"))
        lang = refine_hindi(lang, text) or detect_language(
            text, default=language_hint or Language.HINGLISH
        )
        conf = body.get("language_probability")
        return Transcription(
            text=text, language=lang, confidence=float(conf) if conf is not None else None
        )

    @staticmethod
    def code_for(language: Language) -> str:
        return sarvam_code(language)

    async def aclose(self) -> None:
        await self._http.aclose()


def _key(settings: Settings) -> str:
    if not settings.sarvam_api_key:
        raise ProviderError("sarvam", "SARVAM_API_KEY not set")
    return settings.sarvam_api_key.get_secret_value()


def build_sarvam_stt(c: Container) -> SarvamSTT:
    return SarvamSTT(_key(c.settings))
