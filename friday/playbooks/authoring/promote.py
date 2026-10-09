"""``friday playbook promote <business_type>``: copy a reviewed draft into friday/playbooks/data.

Only if the draft (as it is NOW on disk, including any edits) validates, passes the dry run with
zero safety violations and every check, and a human types the business type name to confirm.
There is no flag that skips the confirmation. An existing playbook is never overwritten.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from friday.playbooks import dryrun
from friday.playbooks.authoring.author import (
    check_draft,
    collect_failures,
    resolve_draft_dir,
    run_dryrun_on_texts,
)
from friday.playbooks.model import DATA_DIR

_ID = re.compile(r"[a-z][a-z0-9_]{2,40}")


@dataclass
class PromoteResult:
    ok: bool
    refusals: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    report: dryrun.DryRunReport | None = None


def _promoted_header(text: str, business_type: str, what: str = "Playbook") -> str:
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    head = (f"# {what} {business_type}: promoted from a reviewed draft on {date.today()}.\n"
            "# Rules: docs/PLAYBOOKS.md. After any edit run "
            "`uv run friday playbook validate|dry-run <name>`.\n\n")
    return head + "\n".join(lines[i:])


def check_promotable(business_type: str, draft_dir: Path) -> PromoteResult:
    """Everything that must hold before promotion (no files are written)."""
    res = PromoteResult(ok=False)
    pfile, qfile = draft_dir / "playbook.yaml", draft_dir / "personas.yaml"
    if not pfile.exists() or not qfile.exists():
        res.refusals.append(f"no draft found in {draft_dir} (need playbook.yaml and personas.yaml)")
        return res
    ptext = pfile.read_text(encoding="utf-8")
    qtext = qfile.read_text(encoding="utf-8")
    problems, _pb, _pf = check_draft(business_type, ptext, qtext)
    if problems:
        res.refusals.append("the draft does not validate:")
        res.refusals += [f"  - {p}" for p in problems[:30]]
        return res
    with tempfile.TemporaryDirectory(prefix=".promote-", dir=draft_dir) as stage:
        report = asyncio.run(run_dryrun_on_texts(business_type, ptext, qtext, Path(stage)))
    res.report = report
    if report.safety_violations:
        res.refusals.append("SAFETY VIOLATIONS (never waived):")
        res.refusals += [f"  - {p}: {s}" for p, s in report.safety_violations]
    fails = collect_failures(report)
    if fails:
        res.refusals.append("the dry run is not clean:")
        res.refusals += [f"  - {f.persona}: {', '.join(f.failed)}" for f in fails]
    if not res.refusals:
        res.ok = True
    return res


def promote(
    business_type: str,
    *,
    drafts_root: Path | str | None = None,
    data_dir: Path | None = None,
    confirm: Callable[[str], str] | None = None,
) -> PromoteResult:
    """Promote a draft. ``confirm(prompt)`` returns what the human typed (default: input())."""
    if not _ID.fullmatch(business_type):
        return PromoteResult(False, [f"'{business_type}' is not a valid business type name"])
    draft_dir = resolve_draft_dir(drafts_root, business_type)
    res = check_promotable(business_type, draft_dir)
    dest = Path(data_dir) if data_dir else DATA_DIR
    targets = [dest / f"{business_type}.yaml", dest / f"{business_type}.personas.yaml"]
    if res.ok:
        clash = [t for t in targets if t.exists()]
        if clash:
            res.ok = False
            res.refusals.append(
                f"{clash[0].name} already exists in {dest}; promotion never overwrites a playbook. "
                "Move or delete the old file yourself if you really mean to replace it."
            )
    if not res.ok:
        return res
    ask = confirm or input
    try:
        typed = ask(
            f"Everything checks out. To copy this draft into {dest} type the business type "
            f"name ({business_type}) and press Enter: "
        )
    except EOFError:
        typed = ""
    if typed.strip() != business_type:
        res.ok = False
        res.refusals.append("not confirmed (the business type name was not typed): nothing copied")
        return res
    ptext = _promoted_header(
        (draft_dir / "playbook.yaml").read_text(encoding="utf-8"), business_type
    )
    qtext = _promoted_header(
        (draft_dir / "personas.yaml").read_text(encoding="utf-8"), business_type,
        "Simulated businesses for")
    dest.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(ptext, encoding="utf-8")
    targets[1].write_text(qtext, encoding="utf-8")
    res.written = targets
    return res
