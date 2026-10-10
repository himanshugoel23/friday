"""``friday tts-check``: automated pronunciation QA for names.

For each name: build the spoken form (friday/voice/names.py), synthesise it with the real TTS,
transcribe it back with the real STT, and compare the two on a consonant skeleton (so Devanagari
and Roman spellings of the same sound match). A row is PASS when the heard text is close enough
to what we meant to say; otherwise REVIEW: only those need a human listen. Fix a REVIEW name by
adding it to ``friday/voice/name_overrides.json``.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.core.models import AudioClip, Language

# Devanagari consonants -> a rough Roman consonant (vowels and matras are dropped)
_DEV = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n", "च": "c", "छ": "c", "ज": "j", "झ": "j",
    "ञ": "n", "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n", "त": "t", "थ": "t", "द": "d",
    "ध": "d", "न": "n", "प": "p", "फ": "p", "ब": "b", "भ": "b", "म": "m", "य": "", "र": "r",
    "ल": "l", "व": "v", "श": "s", "ष": "s", "स": "s", "ह": "h", "ं": "n", "ँ": "n",
    "क़": "k", "ख़": "k", "ग़": "g", "ज़": "j", "ड़": "r", "ढ़": "r", "फ़": "p",
}
_DIGRAPHS = (("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("th", "t"), ("dh", "d"),
             ("ph", "p"), ("bh", "b"), ("ck", "k"), ("ee", ""), ("oo", ""))
_ROMAN_MAP = str.maketrans({"q": "k", "x": "k", "z": "j", "w": "v", "f": "p", "y": ""})


def skeleton(text: str) -> str:
    """Consonant skeleton of a Devanagari / Roman text ("श्रेया saloon" ~ "Shreya saloon")."""
    t = unicodedata.normalize("NFC", (text or "").lower())
    out = []
    for ch in t:
        if "ऀ" <= ch <= "ॿ":
            out.append(_DEV.get(ch, ""))
        else:
            out.append(ch)
    s = "".join(out)
    s = re.sub(r"[^a-z\s]", " ", s)
    for a, b in _DIGRAPHS:
        s = s.replace(a, b)
    s = s.translate(_ROMAN_MAP)
    s = re.sub(r"[aeiou]", "", s)
    s = re.sub(r"\s+", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def similarity(a: str, b: str) -> float:
    sa, sb = skeleton(a), skeleton(b)
    if not sa or not sb:
        return 0.0
    return difflib.SequenceMatcher(None, sa, sb).ratio()


@dataclass
class Row:
    name: str
    spoken: str
    heard: str
    score: float
    flag: str  # PASS | REVIEW
    audio: bytes = field(default=b"", repr=False)
    note: str = ""


async def check_names(
    names: list[str],
    *,
    speller: Any,
    tts: Any,
    stt: Any,
    voice: Any = None,
    threshold: float = 0.7,
) -> list[Row]:
    rows: list[Row] = []
    for name in names:
        spoken = speller.spoken(name)
        try:
            clip: AudioClip = await tts.synthesize(spoken, Language.HINGLISH, voice=voice)
            heard = (await stt.transcribe(clip, language_hint=Language.HINGLISH)).text
        except Exception as e:  # noqa: BLE001 - one bad name must not stop the table
            rows.append(Row(name, spoken, "", 0.0, "REVIEW", note=f"{type(e).__name__}"))
            continue
        # compared with what we meant to say AND with the plain name (either may be what STT hears)
        score = max(similarity(heard, spoken), similarity(heard, name))
        rows.append(
            Row(name, spoken, heard, score, "PASS" if score >= threshold else "REVIEW", clip.data)
        )
    return rows


def render_table(rows: list[Row]) -> str:
    w1 = max([len(r.name) for r in rows] + [4])
    w2 = max([len(r.spoken) for r in rows] + [6])
    w3 = max([len(r.heard) for r in rows] + [5])
    head = f"{'name':<{w1}}  {'spoken':<{w2}}  {'heard back':<{w3}}  {'match':>5}  flag"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(
            f"{r.name:<{w1}}  {r.spoken:<{w2}}  {r.heard:<{w3}}  {r.score:>5.0%}  {r.flag}"
            + (f" ({r.note})" if r.note else "")
        )
    review = [r for r in rows if r.flag == "REVIEW"]
    lines.append("-" * len(head))
    lines.append(
        f"{len(rows) - len(review)} PASS, {len(review)} REVIEW"
        + ("  (listen to the REVIEW rows; fix with friday/voice/name_overrides.json)" if review else "")  # noqa: E501
    )
    return "\n".join(lines)


def read_names(names: list[str], from_file: str | None) -> list[str]:
    out = [n.strip() for n in names if n.strip()]
    if from_file:
        for line in Path(from_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return list(dict.fromkeys(out))


def save_flagged(rows: list[Row], directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    saved = []
    for r in rows:
        if r.flag == "REVIEW" and r.audio:
            safe = re.sub(r"[^A-Za-z0-9]+", "_", r.name).strip("_") or "name"
            p = directory / f"{safe}.wav"
            p.write_bytes(r.audio)
            saved.append(p)
    return saved


def run_tts_check_command(args: Any, settings: Any) -> int:
    names = read_names(list(args.names or []), args.from_file)
    if not names:
        print('Give names: friday tts-check "Shreya Salon" "Looks Unisex Salon"  (or --from-file F)')  # noqa: E501
        return 2
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY is not set (the check uses the real voice and the real listener).")
        return 2
    from friday.voice.names import NameSpeller, sarvam_transliterator
    from friday.voice.stt.sarvam import SarvamSTT
    from friday.voice.tts.sarvam import build_sarvam_tts

    key = settings.sarvam_api_key.get_secret_value()

    class _C:  # build_sarvam_tts only reads .settings
        pass

    c = _C()
    c.settings = settings
    tts = build_sarvam_tts(c)  # type: ignore[arg-type]
    stt = SarvamSTT(key)
    speller = NameSpeller(sarvam_transliterator(key))
    voice = tts.voice_for(Language.HINGLISH)

    async def go() -> list[Row]:
        try:
            return await check_names(
                names, speller=speller, tts=tts, stt=stt, voice=voice, threshold=args.threshold
            )
        finally:
            await stt.aclose()
            await tts.aclose()

    rows = asyncio.run(go())
    print(render_table(rows))
    if args.save_audio:
        for p in save_flagged(rows, Path(args.save_audio)):
            print(f"saved {p}")
    return 0 if all(r.flag == "PASS" for r in rows) else 1
