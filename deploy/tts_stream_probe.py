"""Opt-in latency probe: Sarvam TTS REST vs streaming, with the real key (costs a few paise).

    uv run python deploy/tts_stream_probe.py ["line to speak"] [--runs 2]

Reads settings the same way the CLI does (``Settings()``); never run by the test suite.
Prints first-audio and total milliseconds for both paths, same voice, pace and dictionary.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from types import SimpleNamespace

from friday.core.config import Settings
from friday.core.models import Language
from friday.voice.tts.sarvam import build_sarvam_tts

LINE = (
    "Haan ji, main Friday baat kar rahi hoon, Himanshu sir ki virtual assistant. "
    "Unko haircut aur beard trim karwana hai, toh charges bata dijiye."
)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default=LINE)
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()
    settings = Settings()
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY is not set")
        return 2
    tts = build_sarvam_tts(SimpleNamespace(settings=settings))  # type: ignore[arg-type]
    lang = Language.HINGLISH
    print(f"{len(args.text)} chars, model {tts.model}, voice {tts.voice_for(lang).voice_id}")
    try:
        for i in range(args.runs):
            t0 = time.perf_counter()
            clip = await tts.synthesize(args.text, lang)
            ms = (time.perf_counter() - t0) * 1000
            print(f"run {i + 1} REST    first-audio {ms:6.0f} ms  total {ms:6.0f} ms"
                  f"  ({len(clip.data)} bytes)")
            t0 = time.perf_counter()
            first = None
            n = 0
            async for pcm in tts.synthesize_stream(args.text, lang):
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
                n += len(pcm)
            total = (time.perf_counter() - t0) * 1000
            print(f"run {i + 1} STREAM  first-audio {first or 0:6.0f} ms  total {total:6.0f} ms"
                  f"  ({n} pcm bytes = {n / 16000:.1f} s of audio)")
    finally:
        await tts.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
