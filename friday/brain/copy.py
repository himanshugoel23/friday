"""User-facing copy helpers for the deterministic path: pick the user's language,
apply the tone (friendly / formal / playful). Friday is female: Hindi/Hinglish
copy always uses feminine first-person forms ("karti hoon", "bata dungi").
"""

from __future__ import annotations

import re

from friday.core.models import Language, Tone

_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⭐✅⚠️]+", flags=re.UNICODE)


def pick(
    lang: Language | str | None, *, en: str, hinglish: str | None = None, hi: str | None = None
) -> str:
    """Choose copy for the user's language (regional -> English for chat copy)."""
    lang = Language(lang) if lang else Language.HINGLISH
    if lang == Language.HI:
        return hi or hinglish or en
    if lang == Language.HINGLISH:
        return hinglish or en
    return en


_SERIOUS = re.compile(
    r"\b(consent|agree|terms|pin|otp|password|delete|erase|ticket|complaint|refund|112|108|"
    r"unwell|dizzy|medicine|dawai|doctor|clinic|health|tabiyat|alert|warning|verify|"
    r"verification|emergency|scam|fraud|privacy|data)\b|सहमत|दवाई",
    re.I,
)


def is_serious(text: str) -> bool:
    """Consent, PIN/OTP, health, customer care, crises: never any emoji."""
    return bool(_SERIOUS.search(text))


def toned(text: str, tone: Tone | str | None, *, playful_tail: str = "") -> str:
    """Calm by default (JARVIS / F.R.I.D.A.Y.): FRIENDLY and FORMAL carry no emoji;
    FORMAL also drops exclamation marks. PLAYFUL gets at most the one emoji the caller
    asked for via ``playful_tail`` (an occasional light touch), never on serious topics."""
    tone = Tone(tone) if tone else Tone.FRIENDLY
    out = _EMOJI.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +\n", "\n", out).strip()
    if tone == Tone.FORMAL:
        return out.replace("!", ".").replace("..", ".")
    if tone == Tone.PLAYFUL and playful_tail and not is_serious(out):
        return out.rstrip() + playful_tail
    return out


def say(
    lang: Language | str | None,
    tone: Tone | str | None,
    *,
    en: str,
    hinglish: str | None = None,
    hi: str | None = None,
    playful_tail: str = "",
) -> str:
    return toned(pick(lang, en=en, hinglish=hinglish, hi=hi), tone, playful_tail=playful_tail)


def first_name(name: str | None, fallback: str = "") -> str:
    if not name:
        return fallback
    parts = name.strip().split()
    if parts and parts[0].lower().rstrip(".") in {"dr", "mr", "mrs", "ms", "shri", "smt"}:
        return " ".join(parts[:2])
    return parts[0] if parts else fallback
