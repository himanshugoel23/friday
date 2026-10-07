"""Deepgram speech-to-text (Nova-3). Strong English/Hindi incl. code-switching.

REST: ``POST https://api.deepgram.com/v1/listen`` with raw audio body and
``Authorization: Token <key>``. For Hindi/Hinglish hints we use ``language=multi``
(code-switching); otherwise ``detect_language=true``. Detected language is mapped
back to ``Language`` (Roman-script Hindi -> HINGLISH).
"""

from __future__ import annotations

import httpx

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.models import AudioClip, Language, Transcription
from friday.voice._http import VendorHTTP
from friday.voice.langs import from_vendor_code, refine_hindi
from friday.voice.text import detect_language

DEEPGRAM_BASE_URL = "https://api.deepgram.com"


class DeepgramSTT:
    name = "deepgram"
    supported_languages: frozenset[Language] = frozenset(
        {Language.EN, Language.HI, Language.HINGLISH, Language.TA, Language.TE, Language.KN,
         Language.MR, Language.BN, Language.GU, Language.ML, Language.PA}
    )  # fmt: skip

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "nova-3",
        base_url: str = DEEPGRAM_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._http = VendorHTTP(
            "deepgram", base_url=base_url, headers={"Authorization": f"Token {api_key}"},
            transport=transport,
        )

    def params_for(self, language_hint: Language | None) -> dict[str, str]:
        params = {"model": self.model, "smart_format": "true", "punctuate": "true"}
        if language_hint in (Language.HI, Language.HINGLISH, None):
            params["language"] = "multi"
        else:
            params["detect_language"] = "true"
        return params

    async def transcribe(
        self, audio: AudioClip, *, language_hint: Language | None = None
    ) -> Transcription:
        mime = (audio.mime or "audio/wav").split(";")[0]
        resp = await self._http.request(
            "POST", "/v1/listen", params=self.params_for(language_hint),
            content=audio.data, headers={"Content-Type": mime},
        )
        try:
            body = resp.json()
            channel = body["results"]["channels"][0]
            alt = channel["alternatives"][0]
        except (ValueError, KeyError, IndexError) as e:
            raise ProviderError("deepgram", "unexpected response shape") from e
        text = (alt.get("transcript") or "").strip()
        code = channel.get("detected_language") or (alt.get("languages") or [None])[0]
        lang = refine_hindi(from_vendor_code(code), text) or detect_language(
            text, default=language_hint or Language.EN
        )
        if lang == Language.EN and detect_language(text) == Language.HINGLISH:
            lang = Language.HINGLISH  # multi mode tags code-mixed speech as "en"
        return Transcription(text=text, language=lang, confidence=alt.get("confidence"))

    async def aclose(self) -> None:
        await self._http.aclose()


def build_deepgram_stt(c: Container) -> DeepgramSTT:
    if not c.settings.deepgram_api_key:
        raise ProviderError("deepgram", "DEEPGRAM_API_KEY not set")
    return DeepgramSTT(c.settings.deepgram_api_key.get_secret_value())
