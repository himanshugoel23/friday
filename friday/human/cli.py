# ruff: noqa: E501
"""``friday voice ...``: selftest, switches, human-preview, listening-kit, pron-add, pron-test, metrics."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    v = sub.add_parser("voice", help="human-like voice tools (selftest, previews, pronunciation lab, metrics)")
    vs = v.add_subparsers(dest="voice_cmd", required=True)
    vs.add_parser("selftest", help="offline checks of every human-voice element + ON/OFF of each switch")
    vs.add_parser("switches", help="ON/OFF of every voice switch in the current settings")
    p = vs.add_parser("human-preview", help="render every new audible element to wav (real TTS if keys exist)")
    p.add_argument("--out", default="var/preview/human")
    k = vs.add_parser("listening-kit", help="blind A/B pairs + mini calls (old vs new treatment) to rate")
    k.add_argument("--pairs", type=int, default=6)
    k.add_argument("--out", default="var/preview/human/listening")
    pa = vs.add_parser("pron-add", help="add a word and its preferred spoken form to the pronunciation dictionary")
    pa.add_argument("word")
    pa.add_argument("spoken")
    pt = vs.add_parser("pron-test", help="show how a line is respelled by the dictionary; render it if keys exist")
    pt.add_argument("text")
    pt.add_argument("--out", default="var/preview/human/pron_test.wav")
    m = vs.add_parser("metrics", help="human-feel report from var/human/metrics.jsonl")
    m.add_argument("--file", default=None)


def handles(args: argparse.Namespace) -> bool:
    return getattr(args, "cmd", None) == "voice"


def run(args: argparse.Namespace) -> int:
    from friday.core.config import Settings

    cmd = args.voice_cmd
    settings = Settings()
    if cmd == "selftest":
        from friday.human.selftest import run as selftest

        return selftest(settings)
    if cmd == "switches":
        from friday.human.profile import format_report

        print(format_report(settings))
        return 0
    if cmd == "metrics":
        from friday.human import metrics as hm

        rows = hm.load(Path(args.file)) if args.file else hm.load()
        print(hm.report(rows))
        return 0
    if cmd == "pron-add":
        from friday.human.pronlab import add

        try:
            done = add(args.word, args.spoken)
        except ValueError as e:
            print(f"REFUSED: {e}")
            return 2
        print(f"added {args.word!r} -> {args.spoken!r} for {', '.join(done)}.")
        print("Next: `friday voice pron-test \"<a line with the word>\"`, listen, then `friday tts-dict sync` and restart Friday.")
        return 0
    from friday.human import preview

    synth = preview.make_synth(settings)
    if cmd == "pron-test":
        from friday.human.pronlab import dictionary_view

        print("as the dictionary respells it:", dictionary_view(args.text))
        if synth is None:
            print("no TTS key found: not rendered (keys are never printed).")
            return 0
        from friday.voice.audio import pcm16_to_wav

        pcm = asyncio.run(synth(args.text, "hinglish", 1.0))
        if pcm:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(pcm16_to_wav(pcm, 8000))
            print(f"wrote {out} (uses the dictionary id synced at Sarvam; run `friday tts-dict sync` first)")
        return 0
    if cmd == "human-preview":
        files, msg = asyncio.run(preview.render_all(synth, Path(args.out)))
        print(msg)
        return 0
    if cmd == "listening-kit":
        _, msg = asyncio.run(preview.build_listening_kit(synth, max(1, args.pairs), Path(args.out)))
        print(msg)
        return 0
    return 2
