# ruff: noqa: E501
"""``friday voice human-preview`` and ``friday voice listening-kit``: render the new audible elements to wav.

Real TTS only if keys exist; otherwise nothing is rendered and a message says so (no key is ever printed).
Everything is written under ``var/preview/human/`` (git-ignored). Every file is an audition sample for the
founder; none of it is live in production until he approves it.
"""

from __future__ import annotations

import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.core.models import AudioClip, Language
from friday.human.layer import HumanLayer
from friday.human.lines import EXISTING_REPEAT_LINE, VARIANTS
from friday.human.numbers import speak_numbers
from friday.human.prosody import apply as apply_prosody
from friday.human.resume import unfinished, with_connector
from friday.voice.audio import clip_to_pcm16, pcm16_to_wav, resample_pcm16

OUT_DIR = Path("var/preview/human")
LANG = {"hinglish": Language.HINGLISH, "hi": Language.HI, "en": Language.EN}
RATE = 8000

SynthFn = Callable[[str, str, float], Awaitable[bytes | None]]  # (text, lang, pace_mult) -> pcm16 @ 8 kHz


@dataclass
class Item:
    group: str
    name: str
    text: str
    lang: str = "hinglish"
    pace: float = 1.0
    pause_before_ms: int = 0
    note: str = ""


def _items() -> list[Item]:
    its: list[Item] = []
    # numbers: digits as written vs spoken Hinglish
    for i, t in enumerate(["Rate 450 rupaye hai", "Kal shaam 5:30 pm tak aa jayenge", "Total 1500 rupaye lagenge", "Number hai 9876543210", "Subah 10 baje 2 log aayenge"]):
        its.append(Item("numbers", f"{i + 1}_before", t, note="digits as written (today)"))
        its.append(Item("numbers", f"{i + 1}_after", speak_numbers(t, "hinglish"), note="spoken Hinglish"))
    # prosody: same line flat vs with its hint
    for i, t in enumerate(["Rate chaar sau pachaas rupaye hai", "Maaf kijiye, aaj slot nahi ho paega", "Aap kal kitne baje aa sakte hain?", "Dhanyavaad, aapka din achha rahe"]):
        text, hint = apply_prosody(t)
        its.append(Item("prosody", f"{i + 1}_flat", t, note="today"))
        its.append(Item("prosody", f"{i + 1}_hint_{hint.kind}", text, pace=hint.rate_mult, note=f"{hint.kind}: pace x{hint.rate_mult}"))
    # every pending variant
    for key, by in VARIANTS.items():
        for lang, opts in by.items():
            for j, o in enumerate(opts):
                its.append(Item("variants", f"{key}.{lang}.{j}", o.format(name="Rahul"), lang=lang, note="PENDING line"))
    # backchannels (also in variants) as short clips for the long-answer demo
    # mood: apology + shortened line
    its.append(Item("mood", "rushed_before", "Namaste. Main Rahul ki taraf se call kar rahi hoon. Kya aap haircut ka rate bata sakte hain? Aur kab khali hain?"))
    layer_text = "Kya aap haircut ka rate bata sakte hain?"
    its.append(Item("mood", "rushed_after", f"{VARIANTS['mood.apology']['hinglish'][1]} {layer_text}", pace=1.05, note="apology once, one question"))
    # match the listener: 3 paces
    for p in (0.8, 0.9, 1.0):
        its.append(Item("listener", f"pace_{p}", "Haircut ka rate bata dijiye, aur kal kab khali hain?", pace=p / 0.9, note=f"approx pace {p}"))
    # right-sized pauses
    for ms in (0, 250, 600):
        its.append(Item("pauses", f"pause_{ms}ms", "Kya isse kam ho sakta hai?", pause_before_ms=ms, note="silence before the line"))
    # resume
    rest = unfinished("Rate poochna tha, kal shaam ke liye haircut. Kya aap bata sakte hain?", 1) or ""
    its.append(Item("resume", "resume_with_connector", with_connector(rest, VARIANTS["resume.connector"]["hinglish"][0]) or rest, note="after a 'haan ji boliye'"))
    # noise: the EXISTING repeat line (approved), for reference
    its.append(Item("noise", "repeat_existing", EXISTING_REPEAT_LINE, note="existing approved line"))
    return its


async def _render(synth: SynthFn, it: Item) -> bytes | None:
    pcm = await synth(it.text, it.lang, it.pace)
    if pcm is None:
        return None
    if it.pause_before_ms:
        pcm = b"\x00\x00" * int(RATE * it.pause_before_ms / 1000) + pcm
    return pcm16_to_wav(pcm, RATE)


async def render_all(synth: SynthFn | None, out: Path = OUT_DIR) -> tuple[list[str], str]:
    """(files written, message). ``synth`` None -> nothing rendered; the item list is still written."""
    items = _items()
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    index = [f"{i.group}/{i.name}\t[{i.lang}] pace x{i.pace:.2f} pause {i.pause_before_ms} ms\t{i.text}\t{i.note}" for i in items]
    (out / "index.tsv").write_text("\n".join(index) + "\n", encoding="utf-8")
    if synth is None:
        return [], "no TTS key found (SARVAM_API_KEY, or ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID): nothing rendered. Wrote the text list only."
    written: list[str] = []
    for it in items:
        wav = await _render(synth, it)
        if wav is None:
            continue
        p = out / it.group / f"{it.name}.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(wav)
        written.append(str(p))
    return written, f"rendered {len(written)} of {len(items)} samples into {out}"


def make_synth(settings: Any) -> SynthFn | None:
    """A synth function over the real TTS, or None when no key is configured. Never prints a key."""
    try:
        if getattr(settings, "sarvam_api_key", None):
            from friday.voice.tts.sarvam import build_sarvam_tts

            class _C:
                pass

            c = _C()
            c.settings = settings  # type: ignore[attr-defined]
            tts = build_sarvam_tts(c)  # type: ignore[arg-type]
        elif getattr(settings, "elevenlabs_api_key", None) and getattr(settings, "elevenlabs_voice_id", None):
            from friday.core.container import Container
            from friday.voice.tts.elevenlabs import build_elevenlabs_tts

            tts = build_elevenlabs_tts(Container(settings))
        else:
            return None
    except Exception:  # noqa: BLE001
        return None

    async def synth(text: str, lang: str, pace: float) -> bytes | None:
        language = LANG.get(lang, Language.HINGLISH)
        voice = tts.voice_for(language)
        if pace != 1.0:
            voice = voice.model_copy(update={"speaking_rate": round(voice.speaking_rate * pace, 3)})
        clip: AudioClip = await tts.synthesize(text, language, voice=voice)
        dec = clip_to_pcm16(clip)
        if dec is None:
            return None
        pcm, rate = dec
        return resample_pcm16(pcm, rate, RATE)

    return synth


# ---------------------------------------------------------------- blind listening kit
KIT_LINES = [
    "Rate 450 rupaye hai, kal shaam 5:30 pm tak.",
    "Maaf kijiye, aaj slot nahi ho paega.",
    "Kya aap kal subah 10 baje aa sakte hain?",
    "Total 1500 rupaye lagenge, theek hai?",
    "Hold karne ke liye dhanyavaad. Main abhi Rahul ke jawab ka intezaar kar rahi hoon.",
    "Dhanyavaad, aapka din achha rahe.",
]


def _new_treatment(text: str) -> tuple[str, float]:
    t = speak_numbers(text, "hinglish")
    t, hint = apply_prosody(t)
    return t, hint.rate_mult


async def build_listening_kit(synth: SynthFn | None, pairs: int, out: Path, *, seed: int = 7) -> tuple[list[str], str]:
    """N blind pairs (A/B order shuffled, the key kept apart) plus a rating sheet, and two mini calls."""
    rnd = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    lines = [KIT_LINES[i % len(KIT_LINES)] for i in range(pairs)]
    key: dict[str, dict[str, str]] = {}
    sheet = ["pair,which_sounds_more_natural(A/B),natural_A(1-5),natural_B(1-5),bot_or_person_A,bot_or_person_B,notes"]
    written: list[str] = []
    for n, text in enumerate(lines, 1):
        new_text, mult = _new_treatment(text)
        old_first = rnd.random() < 0.5
        a, b = ((text, 1.0), (new_text, mult)) if old_first else ((new_text, mult), (text, 1.0))
        key[f"pair_{n:02d}"] = {"A": "old" if old_first else "new", "B": "new" if old_first else "old", "text": text}
        sheet.append(f"{n},,,,,,")
        if synth is not None:
            for tag, (t, p) in (("A", a), ("B", b)):
                pcm = await synth(t, "hinglish", p)
                if pcm is not None:
                    f = out / f"pair_{n:02d}_{tag}.wav"
                    f.write_bytes(pcm16_to_wav(pcm, RATE))
                    written.append(str(f))
    # two mini calls: Friday's lines only, the same dialogue with the layer off and on
    if synth is not None:
        for tag, on in (("old", False), ("new", True)):
            class _S:
                human_numbers = human_prosody = human_variants = human_mirror = on
                human_mood = human_match_listener = human_pauses = human_backchannels = False
                human_resume = human_noise_adapt = human_metrics = False

            layer = HumanLayer(_S(), "kit-call")
            pcm = b""
            for t in KIT_LINES[:4]:
                sh = layer.shape(t, "hinglish", name="Rahul")
                seg = await synth(sh.text, "hinglish", sh.pace_mult)
                if seg:
                    pcm += seg + b"\x00\x00" * int(RATE * 0.6)
            if pcm:
                f = out / f"call_{tag}_ABKEY.wav"
                f.write_bytes(pcm16_to_wav(pcm, RATE))
                written.append(str(f))
        # blind names for the two calls
        order = ["call_old_ABKEY.wav", "call_new_ABKEY.wav"]
        rnd.shuffle(order)
        for blind, real in zip(("call_1.wav", "call_2.wav"), order, strict=True):
            (out / real).rename(out / blind)
            key[blind] = {"is": "old" if "old" in real else "new"}
        written = [w for w in written if "ABKEY" not in w] + [str(out / "call_1.wav"), str(out / "call_2.wav")]
    (out / "KEY_do_not_open_before_rating.json").write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "rating_sheet.csv").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    msg = (f"wrote {len(written)} wav files + rating_sheet.csv + KEY file in {out}" if synth is not None
           else "no TTS key found: wrote the rating sheet and key only (no audio). Run on the server with the keys.")
    return written, msg
