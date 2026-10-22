"""Text -> WhatsApp-ready voice note bytes (TTS, then Ogg/Opus), with a hold cache.

The TTS is the existing ``TTSProvider`` (Sarvam by default, ElevenLabs when configured) and speaks
the text verbatim. The cache keeps finished Ogg bytes in this process only (a reply may carry
personal details, so it never goes in the shared cache), keyed by a hash of provider, voice,
language and text: an identical reply is synthesised once. It also keeps the WhatsApp media id of
an upload for a few days so an identical reply is not uploaded again either.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

from friday.chatbot_media.convert import AudioConverter
from friday.core.interfaces import TTSProvider
from friday.core.logging import get_logger
from friday.core.models import Language
from friday.voice.text import detect_language

log = get_logger(__name__)

MEDIA_ID_TTL = timedelta(days=20)  # WhatsApp keeps an uploaded media id for 30 days


@dataclass(frozen=True)
class Spoken:
    ogg: bytes
    chars: int
    cached: bool
    key: str


def reply_language(text: str) -> Language:
    """Language to speak ``text`` in: Devanagari -> Hindi, Roman Hinglish -> Hinglish."""
    return detect_language(text, default=Language.HINGLISH)


class SpeechCache:
    """In-process LRU of finished voice notes and of uploaded media ids."""

    def __init__(self, max_items: int = 128) -> None:
        self.max_items = max_items
        self._audio: OrderedDict[str, bytes] = OrderedDict()
        self._media: dict[str, tuple[str, datetime]] = {}

    def get(self, key: str) -> bytes | None:
        data = self._audio.get(key)
        if data is not None:
            self._audio.move_to_end(key)
        return data

    def put(self, key: str, data: bytes) -> None:
        self._audio[key] = data
        self._audio.move_to_end(key)
        while len(self._audio) > self.max_items:
            self._audio.popitem(last=False)

    def media_id(self, key: str, now: datetime) -> str | None:
        hit = self._media.get(key)
        if hit is None or now - hit[1] > MEDIA_ID_TTL:
            return None
        return hit[0]

    def put_media_id(self, key: str, media_id: str, now: datetime) -> None:
        self._media[key] = (media_id, now)
        if len(self._media) > self.max_items * 2:
            self._media.pop(next(iter(self._media)))


class VoiceSynthesizer:
    def __init__(
        self, tts: TTSProvider, converter: AudioConverter, cache: SpeechCache | None = None
    ) -> None:
        self.tts, self.converter = tts, converter
        self.cache = cache or SpeechCache()

    def key_for(self, text: str, language: Language) -> str:
        voice = self.tts.voice_for(language)
        raw = f"{self.tts.name}|{voice.voice_id}|{language.value}|{voice.speaking_rate}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def speak(self, text: str) -> Spoken | None:
        """Ogg/Opus for ``text`` or None (the caller then sends text). Never raises."""
        language = reply_language(text)
        try:
            key = self.key_for(text, language)
            if (hit := self.cache.get(key)) is not None:
                return Spoken(hit, len(text), True, key)
            if not self.converter.available:
                return None
            clip = await self.tts.synthesize(text, language)
            ogg = await self.converter.to_ogg_opus(clip)
        except Exception as e:  # noqa: BLE001 - a voice failure degrades to text
            log.warning("voice reply synthesis failed: %s", type(e).__name__)
            return None
        if not ogg:
            return None
        self.cache.put(key, ogg)
        return Spoken(ogg, len(text), False, key)
