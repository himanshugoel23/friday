# ruff: noqa: E501
"""`friday qa report`: verdicts per scenario, notes, runs, and the pending line ids that were heard."""

from __future__ import annotations

from typing import Any

from friday.qa import scenarios as sc
from friday.qa.store import VERDICT_LABEL, QaStore


def build(store: QaStore) -> dict[str, Any]:
    verdicts, runs = store.verdicts(), store.runs()
    heard, decisions = store.pending_heard(), store.line_decisions()
    rows = []
    for s in sc.SCENARIOS:
        v = verdicts.get(s.id, {})
        last = next((r for r in reversed(runs) if r.get("scenario") == s.id), None)
        rows.append(
            {
                "id": s.id,
                "title": s.title,
                "kind": s.kind,
                "verdict": v.get("verdict", ""),
                "notes": v.get("notes", []),
                "runs": sum(1 for r in runs if r.get("scenario") == s.id),
                "last_status": (last or {}).get("status", ""),
                "real": list(s.real),
                "simulated": list(s.simulated),
            }
        )
    lines = [
        {
            "line_id": lid,
            "heard": info["count"],
            "source": info["source"],
            "scenarios": info["scenarios"],
            "decision": decisions.get(lid, {}).get("decision", "undecided"),
            "note": decisions.get(lid, {}).get("note", ""),
        }
        for lid, info in heard.items()
    ]
    calls, spend = store.today()
    return {
        "scenarios": rows,
        "pending_lines": lines,
        "calls_today": calls,
        "spend_today_inr": spend,
    }


def render(store: QaStore) -> str:
    rep = build(store)
    out = ["FRIDAY QA REPORT", "================", ""]
    done = [r for r in rep["scenarios"] if r["verdict"]]
    out.append(
        f"Verdicts recorded: {len(done)} of {len(rep['scenarios'])} scenarios. "
        f"QA calls today: {rep['calls_today']}, estimated spend today: Rs {rep['spend_today_inr']}."
    )
    out += ["", "SCENARIOS", "---------"]
    for r in rep["scenarios"]:
        verdict = VERDICT_LABEL.get(r["verdict"], "not yet judged")
        run_note = f"{r['runs']} run(s), last: {r['last_status']}" if r["runs"] else "not run"
        out.append(f"[{verdict:>14}] {r['id']:<24} {run_note}")
        for n in r["notes"]:
            out.append(f"                 note: {n}")
    out += ["", "PENDING LINE IDS HEARD ON QA CALLS", "----------------------------------"]
    if not rep["pending_lines"]:
        out.append("(none yet)")
    for ln in rep["pending_lines"]:
        extra = f"  note: {ln['note']}" if ln["note"] else ""
        out.append(
            f"{ln['decision']:<10} {ln['line_id']}  (heard {ln['heard']}x in {', '.join(ln['scenarios'])}){extra}"
        )
    out += [
        "",
        'To approve or reject a line by id:  friday qa line <line_id> approve|reject [--note "..."]',
        "A rejected or 'wording change' line needs a new audio sample before it can be approved (hear-before-change).",
    ]
    return "\n".join(out)
