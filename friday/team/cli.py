# ruff: noqa: E501
"""``friday team``: look at site knowledge, the review queue and drift history. Offline: reads local files only.

    friday team knowledge [--site zomato]        current version, status, versions, last changes
    friday team review                           proposals waiting for the founder (with the diff)
    friday team approve <id> | reject <id>       decide one
    friday team rollback <site> <version>        move the CURRENT pointer back (nothing is deleted)
    friday team drift-run                        run the probes now (REAL network; public pages; respects robots.txt)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any


def register(sub: Any) -> None:
    sp = sub.add_parser("team", help="agent team: site knowledge versions, review queue, drift")
    t = sp.add_subparsers(dest="team_cmd")
    k = t.add_parser("knowledge")
    k.add_argument("--site")
    t.add_parser("review")
    for name in ("approve", "reject"):
        t.add_parser(name).add_argument("id")
    r = t.add_parser("rollback")
    r.add_argument("site")
    r.add_argument("version", type=int)
    t.add_parser("drift-run")


def _store() -> Any:
    from friday.core.config import Settings
    from friday.team.knowledge import KnowledgeStore

    s = Settings()
    return KnowledgeStore(Path(s.team_knowledge_dir)), s


def run_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "team_cmd", None)
    if cmd is None:
        print(__doc__)
        return 0
    store, s = _store()
    if cmd == "knowledge":
        for site in [args.site] if args.site else store.sites():
            kb = store.get(site)
            print(f"{site}: current v{kb['version']} ({kb['status']}); versions {store.versions(site)}")
            for e in store.changelog(site)[-5:]:
                print("   ", {k: v for k, v in e.items() if k != "changes"})
        return 0
    if cmd == "review":
        q = store.review_queue()
        for item in q:
            print(f"{item['id']}  [{item['site']}] {item['reason']}")
            for line in item["diff"]:
                print("    ", line)
        print(f"{len(q)} waiting")
        return 0
    if cmd == "approve":
        print(f"applied as v{store.approve(args.id)}")
        return 0
    if cmd == "reject":
        store.reject(args.id)
        print("rejected")
        return 0
    if cmd == "rollback":
        store.rollback(args.site, args.version, "cli")
        print(f"{args.site} is now v{args.version}")
        return 0
    if cmd == "drift-run":
        from friday.team.drift import DriftJob, HttpxFetcher

        job = DriftJob(store, HttpxFetcher(), min_interval_s=s.team_probe_min_interval_s, interval_h=s.team_drift_interval_h)
        for rep in asyncio.run(job.run_all()):
            print(rep.line(), "|", rep.note or "; ".join(rep.diff))
        return 0
    return 0
