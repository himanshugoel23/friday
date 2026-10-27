# ruff: noqa: E501
"""Pronunciation lab: add a word and its preferred spoken form, test it through the TTS dictionary
path, and (after listening) sync it. No model training, no voice cloning.

``add`` edits ``friday/voice/tts/pronunciations.json`` (the same file ``friday tts-dict`` syncs).
``test`` renders the word with the dictionary applied; the real TTS is used only if keys exist.
Offline, ``dictionary_view`` shows exactly what the voice would be told to say.
"""

from __future__ import annotations

import json
from pathlib import Path

from friday.voice.tts import pronunciation as pron

LANG_CODES = ("hi-IN", "en-IN")


def add(word: str, spoken: str, *, langs: tuple[str, ...] = LANG_CODES, file: Path = pron.DEFAULT_FILE) -> dict[str, str]:
    word, spoken = word.strip(), spoken.strip()
    if not word or not spoken:
        raise ValueError("word and spoken form must be non-empty")
    data = json.loads(file.read_text(encoding="utf-8"))
    prons = data.setdefault("pronunciations", {})
    for lang in langs:
        prons.setdefault(lang, {})[word] = spoken
    total = sum(len(v) for v in prons.values())
    if total > pron.MAX_WORDS:
        raise ValueError(f"{total} words; Sarvam allows {pron.MAX_WORDS} per dictionary")
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {lang: prons[lang][word] for lang in langs}


def remove(word: str, file: Path = pron.DEFAULT_FILE) -> int:
    data = json.loads(file.read_text(encoding="utf-8"))
    n = 0
    for words in data.get("pronunciations", {}).values():
        if word in words:
            del words[word]
            n += 1
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def dictionary_view(text: str, lang: str = "hi-IN", file: Path = pron.DEFAULT_FILE) -> str:
    """The text as the dictionary would respell it (what the voice is told to say)."""
    words = pron.load(file).get(lang, {})
    out = text
    for w in sorted(words, key=len, reverse=True):
        out = out.replace(w, words[w])
    return out
