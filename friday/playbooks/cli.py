"""``friday playbook list | validate <name> | dry-run <name> | draft <type> | promote <type>``
(wired from friday/cli.py).

    friday playbook list
    friday playbook validate salon_booking
    friday playbook dry-run salon_booking                       all personas, scored
    friday playbook dry-run salon_booking --scenarios hold,rude only these (id contains)
    friday playbook dry-run salon_booking --show friendly_free_slot   print one transcript
    friday playbook dry-run salon_booking --brain               through the (fake) LLM path
    friday playbook dry-run salon_booking --update-baseline     accept these scores
    friday playbook types                                       business types we can draft
    friday playbook draft clinic_appointment [--live] [--rounds 3] [--out DIR]   (offline author)
    friday playbook promote clinic_appointment                  typed confirmation, never automatic

Exit codes: 0 fine, 1 a check failed / regression vs the baseline, 2 a SAFETY VIOLATION (or the
playbook is invalid / cannot run).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register(sub: Any) -> None:
    pb = sub.add_parser("playbook", help="scripted calls: list, validate, dry-run a playbook")
    psub = pb.add_subparsers(dest="playbook_cmd")
    psub.add_parser("list", help="the playbooks and whether they are valid")
    val = psub.add_parser("validate", help="check a playbook file; lists every problem")
    val.add_argument("name", help="a playbook name, or a path to a .yaml/.json file")
    dry = psub.add_parser("dry-run", help="play simulated salons against the playbook, scored")
    dry.add_argument("name")
    dry.add_argument("--scenarios", default=None, help="comma list; persona ids containing these")
    dry.add_argument("--brain", action="store_true", help="classify through the (fake) LLM path")
    dry.add_argument("--llm-mode", choices=["never", "auto", "always"], default=None,
                     help="when to ask the model (default: never offline, always with --brain)")
    dry.add_argument("--update-baseline", action="store_true")
    dry.add_argument("--baseline", default=None, help="baseline file (default: the shipped one)")
    dry.add_argument("--show", default=None, help="print the transcript of this persona")
    dry.add_argument("--paths", action="store_true", help="print the steps each persona visited")
    dry.add_argument("--save-transcripts", default=None, metavar="DIR",
                     help="write redacted simulated transcripts to DIR")
    prev = psub.add_parser(
        "preview", help="hear the REAL script (names, voice, pauses) as one wav, before any call")
    prev.add_argument("name", help="playbook, e.g. salon_booking")
    prev.add_argument("--mode", choices=["book", "quote_only", "quote-only"], default="quote_only")
    prev.add_argument("--business", required=True, help='e.g. "Shreya Salon"')
    prev.add_argument("--user", required=True, help="the owner's first name, e.g. Himanshu")
    prev.add_argument("--services", default="haircut", help='e.g. "haircut, beard trim"')
    prev.add_argument("--when", default=None, help="book mode: e.g. 'aaj shaam 5 baje'")
    prev.add_argument("--fallback-when", default=None, help="book mode: e.g. 'kal shaam 5 baje'")
    prev.add_argument("--branch", default=None,
                      help="book: free | busy_then_fallback (default free); quote_only: quote")
    prev.add_argument("--budget", type=int, default=600, help="book mode price ceiling (Rs)")
    prev.add_argument("--honorific", default="sir")
    prev.add_argument("--pace", type=float, default=0.9,
                      help="voice pace (default 0.9, what the founder approved; the live call "
                           "uses FRIDAY_TTS_SPEAKING_RATE)")
    prev.add_argument("--silence", type=float, default=1.8,
                      help="seconds of silence where the salon would speak (default 1.8)")
    prev.add_argument("--out", required=True, metavar="DIR", help="folder for the wav")
    draft = psub.add_parser(
        "draft", help="OFFLINE script author: draft a playbook for a new business type")
    draft.add_argument("business_type", help="e.g. clinic_appointment (see: friday playbook types)")
    draft.add_argument("--live", action="store_true",
                       help="use the real LLM (costs money; needs an LLM key); "
                            "default: offline template")
    draft.add_argument("--rounds", type=int, default=3, metavar="N",
                       help="max improvement rounds after the first draft (default 3)")
    draft.add_argument("--out", default=None, metavar="DIR",
                       help="drafts folder (default var/playbook_drafts); files go in DIR/<type>/")
    draft.add_argument("--max-tokens", type=int, default=None,
                       help="--live only: max output tokens per model call (default 14000)")
    promote = psub.add_parser(
        "promote", help="copy a reviewed draft into friday/playbooks/data (typed confirmation)")
    promote.add_argument("business_type")
    promote.add_argument("--from", dest="drafts", default=None, metavar="DIR",
                         help="drafts folder (default var/playbook_drafts)")
    psub.add_parser("types", help="the business types the script author knows")


def run_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "playbook_cmd", None) or "list"
    from friday.playbooks.model import (
        PlaybookError,
        list_playbooks,
        load_playbook,
        playbook_files,
    )

    if cmd == "list":
        rows = list_playbooks()
        if not rows:
            print("No playbooks found.")
            return 0
        for name, status, detail in rows:
            print(f"{name:<24} {status:<8} {detail}")
        return 0 if all(s == "ok" for _n, s, _d in rows) else 2

    if cmd == "validate":
        path = Path(args.name)
        if not path.suffix:
            files = playbook_files()
            if args.name not in files:
                print(f"No playbook named '{args.name}'. Have: {', '.join(sorted(files)) or '-'}")
                return 2
            path = files[args.name]
        try:
            pb = load_playbook(path)
        except PlaybookError as e:
            print(f"INVALID: {path.name}")
            for p in e.problems:
                print(f"  - {p}")
            return 2
        print(f"OK: {path.name}  (id {pb.id}, version {pb.version}, {len(pb.steps)} steps, "
              f"{len(pb.lines)} lines)")
        for w in pb.warnings:
            print(f"  warning: {w}")
        return 0

    if cmd == "dry-run":
        return _dry_run(args)
    if cmd == "preview":
        return _preview(args)
    if cmd in ("draft", "promote", "types"):
        from friday.playbooks.authoring import cli as authoring_cli

        return authoring_cli.run(cmd, args)
    print("Usage: friday playbook list | validate <name> | dry-run <name> | draft <type> | "
          "promote <type> | types")
    return 2


def _preview(args: argparse.Namespace) -> int:
    import asyncio

    from friday.core.config import Settings
    from friday.core.models import Language
    from friday.playbooks.model import PlaybookError
    from friday.playbooks.preview import render_preview
    from friday.voice.names import NameSpeller, sarvam_transliterator
    from friday.voice.tts.sarvam import build_sarvam_tts

    settings = Settings()
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY is not set (the preview uses the real voice).")
        return 2

    class _C:  # build_sarvam_tts only reads .settings
        pass

    c = _C()
    c.settings = settings
    tts = build_sarvam_tts(c)  # type: ignore[arg-type]
    voice = tts.voice_for(Language.HINGLISH).model_copy(update={"speaking_rate": args.pace})
    speller = NameSpeller(sarvam_transliterator(settings.sarvam_api_key.get_secret_value()))

    async def go() -> Any:
        try:
            return await render_preview(
                tts=tts, voice=voice, out_dir=Path(args.out), silence_s=args.silence,
                mode=args.mode, branch=args.branch, business=args.business, user=args.user,
                services=args.services, when=args.when, fallback_when=args.fallback_when,
                budget=args.budget, honorific=args.honorific, speller=speller,
                playbook=args.name,
            )
        finally:
            await tts.aclose()

    try:
        res = asyncio.run(go())
    except PlaybookError as e:
        print("Cannot preview: " + "; ".join(e.problems))
        return 2
    for i, line in enumerate(res.lines, 1):
        print(f"{i}. {line}")
    print(f"\nOutcome of this branch: {res.outcome}. {res.seconds:.0f} s at pace {args.pace}.")
    print(f"Wrote {res.wav_path}")
    return 0


def _dry_run(args: argparse.Namespace) -> int:
    from friday.playbooks import dryrun
    from friday.playbooks.model import PlaybookError

    only = [s.strip() for s in args.scenarios.split(",") if s.strip()] if args.scenarios else None
    mode = args.llm_mode or ("always" if args.brain else "never")
    try:
        report = dryrun.run_sync(args.name, only=only, llm_mode=mode, via_brain=args.brain)
    except PlaybookError as e:
        print(f"INVALID playbook '{args.name}':")
        for p in e.problems:
            print(f"  - {p}")
        return 2
    except FileNotFoundError as e:
        print(str(e))
        return 2
    if not report.runs:
        print("No matching scenarios.")
        return 2
    path = Path(args.baseline) if args.baseline else dryrun.baseline_path(args.name)
    baseline = dryrun.load_baseline(args.name, path)
    print(dryrun.render_table(report, baseline))
    if args.paths:
        print("\nSteps visited:\n" + dryrun.render_paths(report))
    if args.show:
        run = next((r for r in report.runs if args.show in r.persona), None)
        if run is None:
            print(f"\nNo persona matching '{args.show}'.")
        else:
            print(f"\nTranscript: {run.persona} ({run.title})\n{dryrun.render_transcript(run)}")
    if args.save_transcripts:
        saved = dryrun.save_transcripts(report, Path(args.save_transcripts))
        print(f"\nSimulated transcripts (redacted) saved to {saved}")
    if report.safety_violations:
        print("\nFAILED: safety violation(s). Fix the playbook or engine before any live call.")
        return 2
    if args.update_baseline:
        saved = dryrun.save_baseline(report, path)
        print(f"\nBaseline saved to {saved}")
        return 0
    problems = dryrun.find_regressions(report, baseline)
    if baseline is None:
        print("\nNo baseline yet. Run with --update-baseline to save one.")
    if problems:
        print("\nREGRESSION vs baseline:")
        for p in problems:
            print(f"  - {p}")
        return 1
    if any(r.failed for r in report.runs):
        print("\nSome checks fail (see above). Not a regression, but worth fixing.")
        return 1
    print("\nAll checks pass." + ("" if baseline else ""))
    return 0
