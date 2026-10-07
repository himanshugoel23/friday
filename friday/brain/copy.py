"""User-facing copy helpers for the deterministic path: pick the user's language,
apply the tone (friendly / formal / playful). Friday is female: Hindi/Hinglish
copy always uses feminine first-person forms ("karti hoon", "bata dungi").
"""

from __future__ import annotations

import re

from friday.core.models import Language, Tone

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF☀-➿⭐✅⚠️]+", flags=re.UNICODE
)


def pick(lang: Language | str | None, *, en: str, hinglish: str | None = None,
         hi: str | None = None) -> str:
    """Choose copy for the user's language (regional -> English for chat copy)."""
    lang = Language(lang) if lang else Language.HINGLISH
    if lang == Language.HI:
        return hi or hinglish or en
    if lang == Language.HINGLISH:
        return hinglish or en
    return en


def toned(text: str, tone: Tone | str | None, *, playful_tail: str = " 😄") -> str:
    """FORMAL: no emoji, no exclamation; PLAYFUL: a light emoji at the end;
    FRIENDLY (default): unchanged."""
    tone = Tone(tone) if tone else Tone.FRIENDLY
    if tone == Tone.FORMAL:
        out = _EMOJI.sub("", text)
        out = out.replace("!", ".").replace("..", ".")
        out = re.sub(r"[ \t]{2,}", " ", out)
        return re.sub(r" +\n", "\n", out).strip()
    if tone == Tone.PLAYFUL:
        if _EMOJI.search(text[-4:]):
            return text
        return text.rstrip() + playful_tail
    return text


def say(lang: Language | str | None, tone: Tone | str | None, *, en: str,
        hinglish: str | None = None, hi: str | None = None, playful_tail: str = " 😄") -> str:
    return toned(pick(lang, en=en, hinglish=hinglish, hi=hi), tone, playful_tail=playful_tail)


def first_name(name: str | None, fallback: str = "") -> str:
    if not name:
        return fallback
    parts = name.strip().split()
    if parts and parts[0].lower().rstrip(".") in {"dr", "mr", "mrs", "ms", "shri", "smt"}:
        return " ".join(parts[:2])
    return parts[0] if parts else fallback
