"""Mirror the user's script in a reply: Devanagari variants of fixed lines, else Roman.

Friday does not transliterate free text into Devanagari (the result would be unapproved wording).
A reply is shown in Devanagari only when an approved-or-pending Devanagari variant of that exact
Roman line is registered here; every other reply stays in Roman Hinglish. The registry is filled by
copy modules (``register_variant``); ``friday/chatbot_media/copy.py`` registers its own lines.
Variants are PENDING_FOUNDER_APPROVAL like the Roman lines they mirror.
"""

from __future__ import annotations

import re
from typing import Literal

Script = Literal["roman", "devanagari"]

_VARIANTS: dict[str, str] = {}


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def register_variant(roman: str, devanagari: str) -> None:
    """Register the Devanagari form of one exact Roman line."""
    if roman.strip() and devanagari.strip():
        _VARIANTS[_key(roman)] = devanagari


def variant_for(roman: str) -> str | None:
    return _VARIANTS.get(_key(roman))


def to_script(text: str, script: Script) -> str:
    """``text`` in the requested script when a variant exists, else unchanged (Roman)."""
    if script != "devanagari" or not text:
        return text
    return variant_for(text) or text


def registered() -> dict[str, str]:
    return dict(_VARIANTS)
