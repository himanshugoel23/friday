"""Deterministic fake TTS: the "audio" is the (filler-free) text as UTF-8 bytes."""

from __future__ import annotations

from friday.core.container import Container
from friday.core.models import AudioClip, Language, VoiceProfile
from friday.voice.langs import VoiceCatalog
from friday.voice.text import strip_fillers

FAKE_TTS_MIME = "text/plain; x-fake-tts"


class FakeTTS:
    name = "fake"
    supported_languages: frozenset[Language] = frozenset(Language)

    def __init__(self, catalog: VoiceCatalog) -> None:
        self.catalog = catalog
        self.calls: list[tuple[str, Language, VoiceProfile]] = []

    def voice_for(self, language: Language) -> VoiceProfile:
        return self.catalog.profile(language)

    async def synthesize(
        self, text: str, language: Language, *, voice: VoiceProfile | None = None
    ) -> AudioClip:
        clean = strip_fillers(text)
        profile = voice or self.voice_for(language)
        self.calls.append((clean, language, profile))
        return AudioClip(data=clean.encode("utf-8"), mime=FAKE_TTS_MIME, sample_rate=8000)


def build_fake_tts(c: Container) -> FakeTTS:
    catalog = VoiceCatalog(
        "fake",
        c.settings,
        {lang: f"fake-{lang.value}-female-calm" for lang in Language},
        "fake-female-calm",
    )
    return FakeTTS(catalog)
