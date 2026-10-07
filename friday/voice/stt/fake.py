"""Deterministic fake STT: the "audio" is the text itself.

* plain bytes -> decoded as UTF-8 (simulator channel voice notes: ``/voice <text>``)
* Ogg/Opus voice notes -> the ``TRANSCRIPT`` (or ``FRIDAY_TRANSCRIPT`` / ``TITLE``)
  Vorbis comment, so real-container fixtures transcribe offline
* anything else -> empty transcript with confidence 0

The DETECTED language is always filled (script + romanised-Hindi heuristic).
"""

from __future__ import annotations

from friday.core.container import Container
from friday.core.models import AudioClass, AudioClip, Language, Transcription
from friday.voice.audio import is_ogg, parse_opus_ogg
from friday.voice.classifier import HeuristicAudioClassifier
from friday.voice.text import detect_language

_TAG_KEYS = ("TRANSCRIPT", "FRIDAY_TRANSCRIPT", "TITLE", "DESCRIPTION")


class FakeSTT:
    name = "fake"
    supported_languages: frozenset[Language] = frozenset(Language)

    def __init__(self) -> None:
        self.calls: list[AudioClip] = []
        self._classifier = HeuristicAudioClassifier()

    @staticmethod
    def text_of(audio: AudioClip) -> str | None:
        data = audio.data
        if is_ogg(data):
            try:
                tags = parse_opus_ogg(data).tags
            except ValueError:
                return None
            return next((tags[k] for k in _TAG_KEYS if tags.get(k)), None)
        if data[:4] == b"RIFF":
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def transcribe(
        self, audio: AudioClip, *, language_hint: Language | None = None
    ) -> Transcription:
        self.calls.append(audio)
        text = (self.text_of(audio) or "").strip()
        if not text:
            return Transcription(
                text="",
                language=language_hint or Language.EN,
                confidence=0.0,
                audio_class=AudioClass.SILENCE,
            )
        lang = detect_language(text, default=language_hint or Language.EN)
        cls = self._classifier.classify_text(text)
        return Transcription(
            text=text,
            language=lang,
            confidence=0.99,
            audio_class=cls.audio_class if cls else AudioClass.HUMAN,
        )


def build_fake_stt(c: Container) -> FakeSTT:
    return FakeSTT()
