"""Language-code mapping and voice catalogue shared by STT/TTS providers."""

from __future__ import annotations

from friday.core.config import Settings
from friday.core.models import Language, VoiceProfile

# Sarvam uses BCP-47-ish codes; Odia is "od-IN" there.
_SARVAM_CODES: dict[Language, str] = {
    Language.EN: "en-IN",
    Language.HI: "hi-IN",
    Language.HINGLISH: "hi-IN",
    Language.TA: "ta-IN",
    Language.TE: "te-IN",
    Language.KN: "kn-IN",
    Language.MR: "mr-IN",
    Language.BN: "bn-IN",
    Language.GU: "gu-IN",
    Language.ML: "ml-IN",
    Language.PA: "pa-IN",
    Language.OR: "od-IN",
}
SARVAM_LANGUAGES: frozenset[Language] = frozenset(_SARVAM_CODES)


def sarvam_code(language: Language) -> str:
    return _SARVAM_CODES.get(language, "hi-IN")


def from_vendor_code(code: str | None) -> Language | None:
    """'hi-IN' / 'hi' / 'od-IN' / 'en-US' -> Language (None if unknown)."""
    if not code:
        return None
    base = code.split("-")[0].split("_")[0].lower()
    if base == "od":
        base = "or"
    try:
        return Language(base)
    except ValueError:
        return None


def refine_hindi(language: Language | None, text: str) -> Language | None:
    """Vendors report Hinglish as 'hi'. Mostly-Roman Hindi text -> HINGLISH."""
    if language != Language.HI or not text:
        return language
    latin = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    deva = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    return Language.HINGLISH if latin > deva else Language.HI


class VoiceCatalog:
    """Per-language calm female voice, overridable via ``Settings.tts_voices``.

    ``tts_voices`` keys are language values ("hi", "en", "hinglish", "ta"...) or "*".
    """

    def __init__(
        self,
        provider: str,
        settings: Settings,
        defaults: dict[Language, str],
        fallback: str,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.defaults = defaults
        self.fallback = fallback

    def voice_id(self, language: Language) -> str:
        overrides = self.settings.tts_voices or {}
        return (
            overrides.get(language.value)
            or (overrides.get("hi") if language == Language.HINGLISH else None)
            or overrides.get("*")
            or self.defaults.get(language)
            or self.fallback
        )

    def profile(self, language: Language) -> VoiceProfile:
        return VoiceProfile(
            provider=self.provider,
            voice_id=self.voice_id(language),
            language=language,
            speaking_rate=self.settings.tts_speaking_rate,
            style=self.settings.tts_style or "calm",
            gender=self.settings.tts_voice_gender,  # always "female"
        )
