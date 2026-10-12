"""The PENDING area: new spoken lines that production does not load until the founder approves.

    friday/playbooks/pending/<id>.yaml            the playbook (validated, dry-run, previewed)
    friday/playbooks/pending/<id>.personas.yaml   its simulated vendors
    friday/playbooks/pending/<id>.approved        the founder's approval marker (NEVER created by
                                                  a builder or a script; the founder creates it
                                                  after hearing the audio)

``friday playbook promote <id>`` copies the pair into ``friday/playbooks/data`` only if the marker
exists (and, when it carries a ``sha256:`` line, the playbook has not changed since), the file
validates, and the dry run is clean (zero safety violations, every check passes). Nothing here
touches the network.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from friday.playbooks import dryrun
from friday.playbooks.authoring.promote import PromoteResult
from friday.playbooks.model import DATA_DIR, PENDING_DIR, PlaybookError, load_playbook

_ID = re.compile(r"[a-z][a-z0-9_]{2,40}")
MARKER_SUFFIX = ".approved"


def pending_paths(pb_id: str, directory: Path | None = None) -> tuple[Path, Path, Path]:
    d = Path(directory) if directory else PENDING_DIR
    return d / f"{pb_id}.yaml", d / f"{pb_id}.personas.yaml", d / f"{pb_id}{MARKER_SUFFIX}"


def pending_ids(directory: Path | None = None) -> list[str]:
    d = Path(directory) if directory else PENDING_DIR
    if not d.is_dir():
        return []
    return sorted(p.name[: -len(".yaml")] for p in d.glob("*.yaml") if ".personas." not in p.name)


def content_hash(pb_id: str, directory: Path | None = None) -> str:
    """sha256 over the playbook AND its personas file (what the founder approved)."""
    pfile, qfile, _m = pending_paths(pb_id, directory)
    h = hashlib.sha256()
    for f in (pfile, qfile):
        h.update(f.read_bytes() if f.exists() else b"")
    return h.hexdigest()


def approval_state(pb_id: str, directory: Path | None = None) -> tuple[str, str]:
    """('approved'|'missing'|'stale', detail). 'stale' = the marker carries a sha256 and the
    playbook changed after it was approved."""
    _p, _q, marker = pending_paths(pb_id, directory)
    if not marker.is_file():
        return "missing", f"no approval marker {marker.name}"
    for line in marker.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.lower().startswith("sha256:"):
            want = line.split(":", 1)[1].strip().lower()
            if want != content_hash(pb_id, directory):
                return "stale", "the playbook changed after it was approved (sha256 differs)"
            return "approved", "approved (hash matches)"
    return "approved", "approved (marker without a hash)"


def marker_line(pb_id: str, directory: Path | None = None) -> str:
    """What the founder puts in the marker to bind approval to the current text."""
    return f"sha256:{content_hash(pb_id, directory)}"


def _strip_pending_notice(text: str) -> str:
    """Drop the leading PENDING paragraph (up to the first bare '#' line) of the file."""
    lines = text.split("\n")
    if not lines or not lines[0].startswith("# PENDING"):
        return text
    for i, line in enumerate(lines):
        if line.strip() == "#":
            return "\n".join(lines[i + 1 :])
        if not line.startswith("#"):
            break
    return text


def check_pending(pb_id: str, directory: Path | None = None) -> PromoteResult:
    """Everything that must hold before promotion. Writes nothing."""
    res = PromoteResult(ok=False)
    pfile, qfile, _marker = pending_paths(pb_id, directory)
    if not _ID.fullmatch(pb_id):
        res.refusals.append(f"'{pb_id}' is not a valid playbook id")
        return res
    if not pfile.exists() or not qfile.exists():
        res.refusals.append(f"no pending playbook {pb_id} (need {pfile.name} and {qfile.name})")
        return res
    state, detail = approval_state(pb_id, directory)
    if state != "approved":
        res.refusals.append(
            f"NOT APPROVED by the founder: {detail}. A pending playbook is promoted only after "
            "the founder has heard its audio and created the marker file "
            f"{pb_id}{MARKER_SUFFIX} next to it."
        )
        return res
    try:
        pb = load_playbook(pfile)
    except PlaybookError as e:
        res.refusals.append("the playbook does not validate:")
        res.refusals += [f"  - {p}" for p in e.problems[:30]]
        return res
    if pb.id != pb_id:
        res.refusals.append(f"the file says id '{pb.id}', expected '{pb_id}'")
        return res
    try:
        report = asyncio.run(dryrun.run_dryrun(pb_id, directory=pfile.parent))
    except Exception as e:  # noqa: BLE001
        res.refusals.append(f"the dry run could not run: {type(e).__name__}: {str(e)[:120]}")
        return res
    res.report = report
    if report.safety_violations:
        res.refusals.append("SAFETY VIOLATIONS (never waived):")
        res.refusals += [f"  - {p}: {s}" for p, s in report.safety_violations]
    fails = [r for r in report.runs if r.failed]
    if fails:
        res.refusals.append("the dry run is not clean:")
        res.refusals += [f"  - {r.persona}: {', '.join(r.failed)}" for r in fails]
    if not report.runs:
        res.refusals.append("no personas to run")
    res.ok = not res.refusals
    return res


def promote_pending(
    pb_id: str,
    *,
    pending_dir: Path | None = None,
    data_dir: Path | None = None,
    confirm: Callable[[str], str] | None = None,
) -> PromoteResult:
    """Promote an approved pending playbook into ``data_dir`` (default friday/playbooks/data).
    Typed confirmation, never overwrites a live playbook, removes the pending files afterwards."""
    from datetime import date

    res = check_pending(pb_id, pending_dir)
    dest = Path(data_dir) if data_dir else DATA_DIR
    targets = [dest / f"{pb_id}.yaml", dest / f"{pb_id}.personas.yaml"]
    if res.ok:
        clash = [t for t in targets if t.exists()]
        if clash:
            res.ok = False
            res.refusals.append(
                f"{clash[0].name} already exists in {dest}; promotion never overwrites a playbook."
            )
    if not res.ok:
        return res
    ask = confirm or input
    try:
        typed = ask(
            f"Approved, valid, dry run clean. To copy {pb_id} into {dest} (LIVE for calls once "
            f"selected) type its id ({pb_id}) and press Enter: "
        )
    except EOFError:
        typed = ""
    if typed.strip() != pb_id:
        res.ok = False
        res.refusals.append("not confirmed (the playbook id was not typed): nothing copied")
        return res
    pfile, qfile, marker = pending_paths(pb_id, pending_dir)
    head = (f"# Playbook {pb_id}: promoted from friday/playbooks/pending on {date.today()} after "
            "the founder's approval.\n# Rules: docs/PLAYBOOKS.md, docs/VENDOR_CALLING.md. After "
            "any edit run `uv run friday playbook validate|dry-run <name>`.\n#\n")
    dest.mkdir(parents=True, exist_ok=True)
    for src, dst in ((pfile, targets[0]), (qfile, targets[1])):
        dst.write_text(head + _strip_pending_notice(src.read_text(encoding="utf-8")),
                       encoding="utf-8")
    for old in (pfile, qfile, marker):
        old.unlink(missing_ok=True)
    res.written = targets
    return res


__all__ = [
    "MARKER_SUFFIX", "approval_state", "check_pending", "content_hash", "marker_line",
    "pending_ids", "pending_paths", "promote_pending",
]
