"""``friday receptionist-sim`` and ``friday receptionist codes|lines|probe|setup`` (all offline).

None of these reads .env, uses the network or places a call. ``probe --show`` only reads the
masked probe file written by a live server with FRIDAY_RECEPTIONIST_PROBE=true.
"""

from __future__ import annotations

import argparse
from pathlib import Path

CMDS = {"receptionist", "receptionist-sim"}


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    from friday.receptionist.sim import add_parser as add_sim

    add_sim(sub)
    r = sub.add_parser("receptionist", help="voicemail receptionist tools (offline)")
    rs = r.add_subparsers(dest="receptionist_cmd", required=True)
    codes = rs.add_parser("codes", help="print the forwarding codes for a carrier (to verify)")
    codes.add_argument("--carrier", required=True, help="jio | airtel | vi | bsnl")
    codes.add_argument("--number", required=True, help="Friday's inbound number")
    codes.add_argument("--rings", type=int, default=5, help="3 to 6 (default 5)")
    codes.add_argument("--no-busy", action="store_true")
    codes.add_argument("--no-unreachable", action="store_true")
    codes.add_argument("--national", action="store_true", help="10-digit number instead of +91")
    codes.add_argument("--lang", choices=["hinglish", "en"], default="hinglish")
    rs.add_parser("lines", help="list every spoken line and WhatsApp text (all PENDING approval)")
    probe = rs.add_parser("probe", help="forwarding probe: steps, or --show the recorded webhooks")
    probe.add_argument("--show", action="store_true")
    probe.add_argument("--file", default=None, help="probe file (default var/receptionist/probe.jsonl)")
    probe.add_argument("--demo", action="store_true", help="analyse an invented example webhook")


def handles(args: argparse.Namespace) -> bool:
    return getattr(args, "cmd", None) in CMDS


def run(args: argparse.Namespace) -> int:
    if args.cmd == "receptionist-sim":
        from friday.receptionist.sim import run_command

        return run_command(args)
    cmd = args.receptionist_cmd
    if cmd == "codes":
        from friday.receptionist.carriers import codes_for
        from friday.receptionist.models import ReceptionistConfig
        from friday.receptionist.setup import setup_text

        cfg = ReceptionistConfig(
            rings=max(3, min(6, args.rings)),
            forward_busy=not args.no_busy,
            forward_unreachable=not args.no_unreachable,
        )
        try:
            cs = codes_for(args.carrier, cfg, args.number, number_style="national" if args.national else "e164")
        except ValueError as e:
            print(e)
            return 2
        print(setup_text(cs, args.lang))
        print("\nTap-to-dial links (the # is encoded as %23):")
        for ln in cs.activate:
            print(f"  {ln.tel_link}")
        return 0
    if cmd == "lines":
        from friday.receptionist import copy, lines

        print("# Spoken lines (PENDING_FOUNDER_APPROVAL; no audio generated)")
        for pl in lines.all_lines():
            print(f"{pl.id}\t{pl.status}\t{pl.text}")
        print("\n# WhatsApp texts and buttons (PENDING_FOUNDER_APPROVAL)")
        for lid, _lang, text in copy.all_texts():
            print(f"{lid}\t{copy.LINE_STATUS}\t{text}")
        return 0
    if cmd == "probe":
        from friday.receptionist import probe as pr
        from friday.receptionist.setup import PROBE_STEPS

        if args.demo:
            e = pr.analyse(
                {"From": "9191000000", "To": "+918000000099", "CallUUID": "x", "Diversion": "<sip:+919800000001@h>;reason=no-answer"},
                ["Diversion"],
            )
            print(pr.format_report([e.to_json()]))
            return 0
        if args.show:
            path = Path(args.file) if args.file else Path("var/receptionist") / pr.PROBE_FILE
            print(pr.format_report(pr.load(path)))
            return 0
        print("\n".join(PROBE_STEPS))
        return 0
    return 2
