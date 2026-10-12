"""Primary voice with a spare: if the primary vendor fails, the line is spoken by the secondary.

Used for ElevenLabs (primary) with Sarvam (spare), so a vendor outage never drops a live call.
The secondary speaks in ITS OWN voice (the primary's voice id is meaningless to it). Streaming is
the primary's; when a stream fails before audio, the call leg's plain-request fallback calls
``synthesize`` here, which then reaches the secondary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger
from friday.core.models import AudioClip, Language, VoiceProfile

log = get_logger(__name__)


class FallbackTTS:
    def __init__(self, primary: Any, secondary: Any) -> None:
        self.primary = primary
        self.secondary = secondary
        self.name = primary.name
        self.supported_languages = frozenset(primary.supported_languages)
        self.streaming = bool(getattr(primary, "streaming", False))
        self.fallbacks = 0

    def voice_for(self, language: Language) -> VoiceProfile:
        return self.primary.voice_for(language)

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        try:
            return await self.primary.synthesize(text, language, voice=voice)
        except ProviderError as e:
            self.fallbacks += 1
            log.warning("tts %s failed (%s); speaking with %s", self.primary.name, e,
                        self.secondary.name)
            return await self.secondary.synthesize(text, language)  # its own default voice

    async def synthesize_stream(
        self, text: str, language: Language, voice: VoiceProfile | None = None
    ) -> AsyncIterator[bytes]:
        async for pcm in self.primary.synthesize_stream(text, language, voice=voice):
            yield pcm

    def __getattr__(self, item: str) -> Any:  # aclose, payload, ... come from the primary
        return getattr(self.primary, item)

    async def aclose(self) -> None:
        for t in (self.primary, self.secondary):
            close = getattr(t, "aclose", None)
            if close is not None:
                await close()
