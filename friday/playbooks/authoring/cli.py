"""``friday playbook draft | promote | types`` (called from friday/playbooks/cli.py).

Offline by default: nothing here reads .env or touches the network unless ``--live`` is given.
Exit codes: 0 fine, 1 the draft needs work, 2 refused / invalid / safety violation.
"""

from __future__ import annotations

import argparse

from friday.playbooks.authoring import author, backends, promote
from friday.playbooks.authoring.knowledge import KnowledgeError, get_business_type, load_knowledge


def run(cmd: str, args: argparse.Namespace) -> int:
    if cmd == "types":
        for k, bt in load_knowledge().business_types.items():
            print(f"{k:<22} {bt.title}")
        return 0
    if cmd == "promote":
        return _promote(args)
    return _draft(args)


def _draft(args: argparse.Namespace) -> int:
    try:
        get_business_type(args.business_type)
    except KnowledgeError as e:
        print(str(e))
        return 2
    rounds = args.rounds
    if rounds < 0 or rounds > 6:
        print("--rounds must be between 0 and 6")
        return 2
    backend: backends.AuthorBackend
    if args.live:
        try:
            backend = backends.build_live_author(args.max_tokens or backends.DEFAULT_MAX_TOKENS)
        except backends.LiveRefused as e:
            print(f"REFUSED: {e}")
            return 2
    else:
        if args.max_tokens:
            print("note: --max-tokens only matters with --live")
        backend = backends.OfflineAuthor()
    plan = author.plan_budget(backend, rounds)
    print(plan.describe())
    try:
        res = author.draft_sync(
            args.business_type, backend=backend, out_root=args.out, rounds=rounds,
            progress=lambda m: print(f"  {m}"),
        )
    except author.OutputRefused as e:
        print(f"REFUSED: {e}")
        return 2
    finally:
        close = getattr(backend, "close", None)
        if close is not None:
            import asyncio

            asyncio.run(close())
    print(f"\nDraft status: {res.status}")
    if res.live:
        u = res.usage
        print(f"Model calls {u.calls}, tokens in {u.input_tokens} out {u.output_tokens}, "
              f"estimated cost about Rs {u.cost_inr:.0f}")
    for label, path in res.files.items():
        print(f"  {label:<9} {path}")
    if res.report is not None:
        print(f"Dry run: {res.report.total:.0%} over {len(res.report.runs)} simulated businesses; "
              f"{len(res.safety_violations)} safety violation(s)")
    if res.status == "blocked_safety" or res.status == "failed":
        print("This draft cannot be promoted. Read report.md.")
        return 2
    if res.status == "needs_work":
        print("Needs work: read report.md, edit playbook.yaml, or run the draft again.")
        return 1
    print(f"Next: read {res.files['report']}, then `uv run friday playbook promote "
          f"{args.business_type}` when you are happy.")
    return 0


def _promote(args: argparse.Namespace) -> int:
    try:
        res = promote.promote(args.business_type, drafts_root=args.drafts)
    except author.OutputRefused as e:
        print(f"REFUSED: {e}")
        return 2
    if not res.ok:
        print("NOT PROMOTED:")
        for r in res.refusals:
            print(f"  {r}")
        return 2
    for p in res.written:
        print(f"copied {p}")
    print(f"\nPromoted. Next: `uv run friday playbook dry-run {args.business_type} "
          "--update-baseline`, read the result, and commit the new files.")
    return 0
