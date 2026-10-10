#!/usr/bin/env python3
"""Render the lines of a script draft to audio so the founder can HEAR them before any code changes.

    uv run python deploy/preview_script.py            # lines file -> var/preview/salon_v6/
    uv run python deploy/preview_script.py --dry-run  # list the lines, no network
    uv run python deploy/preview_script.py --pace 0.9 --only 04,05

Needs SARVAM_API_KEY in the environment (or the git-ignored .env). Uses the same voice code as
`friday say` (speaker/pace from Settings; the pace flag overrides). Writes one WAV per line plus
all.wav (all lines in order, 1 s apart), under docs/playbooks/ for the lines file.
Never put stage directions in the text: it gets spoken.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LINES = ROOT / "docs" / "playbooks" / "salon_v6_preview.txt"


def read_lines(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "|" not in raw:
            continue
        key, text = raw.split("|", 1)
        out.append((key.strip(), text.strip()))
    return out


def join_wavs(clips: list[bytes], gap_s: float = 1.0) -> bytes | None:
    """Concatenate WAV clips (same format) with silence between; None if they are not plain WAV."""
    try:
        frames: list[bytes] = []
        params = None
        for data in clips:
            with wave.open(io.BytesIO(data)) as w:
                if params is None:
                    params = w.getparams()
                elif (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (
                    params.nchannels, params.sampwidth, params.framerate):
                    return None
                frames.append(w.readframes(w.getnframes()))
        if params is None:
            return None
        silence = b"\x00" * int(params.framerate * gap_s) * params.nchannels * params.sampwidth
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setparams(params)
            out.writeframes(silence.join(frames))
        return buf.getvalue()
    except (wave.Error, EOFError):
        return None


async def render(
    lines: list[tuple[str, str]], out_dir: Path, pace: float | None
) -> list[tuple[str, Path, bytes]]:
    from friday.core.config import Settings
    from friday.core.models import Language
    from friday.voice.tts.sarvam import build_sarvam_tts

    class _C:  # build_sarvam_tts only reads .settings
        pass

    c = _C()
    c.settings = Settings()
    tts = build_sarvam_tts(c)  # type: ignore[arg-type]
    voice = tts.voice_for(Language.HINGLISH)
    if pace:
        voice = voice.model_copy(update={"speaking_rate": pace})
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    done: list[tuple[str, Path, bytes]] = []
    for key, text in lines:
        clip = await tts.synthesize(text, Language.HINGLISH, voice=voice)
        path = out_dir / f"{key}.wav"
        await asyncio.to_thread(path.write_bytes, clip.data)
        print(f"ok  {key}  ({len(text)} chars)")
        done.append((key, path, clip.data))
    return done


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lines", type=Path, default=DEFAULT_LINES)
    ap.add_argument("--out", type=Path, default=ROOT / "var" / "preview" / "salon_v6")
    ap.add_argument("--pace", type=float, default=0.9, help="0.5-2.0 (founder is happy with 0.9)")
    ap.add_argument("--only", default="", help="comma-separated id prefixes, e.g. 04,05")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    lines = read_lines(args.lines)
    if args.only:
        keep = tuple(x.strip() for x in args.only.split(",") if x.strip())
        lines = [(k, t) for k, t in lines if k.startswith(keep)]
    if not lines:
        print("no lines selected", file=sys.stderr)
        return 2
    if args.dry_run:
        for k, t in lines:
            print(f"{k:24} {t}")
        return 0
    done = asyncio.run(render(lines, args.out, args.pace))
    joined = join_wavs([d for _k, _p, d in done])
    if joined:
        (args.out / "all.wav").write_bytes(joined)
        print(f"all.wav written ({len(done)} lines)")
    print(f"files in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
