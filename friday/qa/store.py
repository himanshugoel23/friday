# ruff: noqa: E501
"""Files under ``var/qa/`` (gitignored). JSON lines, append-only, no phone number in full.

notes.jsonl           verdicts and notes the founder gives per scenario (and per pending line id)
runs.jsonl            one row per run (status, real vs simulated parts, cost estimate, transcript)
ledger.jsonl          one row per call placed: the daily call count and spend cap read this
pending_heard.jsonl   every PENDING line id spoken on a QA call (written by ``override``)
"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from friday.integration.telephony import scrub_text

IST = timezone(timedelta(hours=5, minutes=30))
VERDICTS = ("ok", "wording", "bug")
VERDICT_LABEL = {"ok": "OK", "wording": "wording change", "bug": "bug"}
LINE_VERDICTS = ("approve", "reject")
MAX_NOTE_CHARS = 1000


def ist_day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(IST).date().isoformat()


class QaStore:
    def __init__(self, directory: Path | str = "var/qa") -> None:
        self.dir = Path(directory)

    # ------------------------------------------------------------------ files
    @property
    def notes_path(self) -> Path:
        return self.dir / "notes.jsonl"

    @property
    def runs_path(self) -> Path:
        return self.dir / "runs.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.dir / "ledger.jsonl"

    @property
    def pending_path(self) -> Path:
        return self.dir / "pending_heard.jsonl"

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn line never breaks the report
            if isinstance(row, dict):
                rows.append(row)
        return rows

    # ------------------------------------------------------------------ notes and verdicts
    def add_note(
        self, scenario: str, verdict: str = "", note: str = "", *, now: datetime | None = None
    ) -> dict[str, Any]:
        if verdict and verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
        if not verdict and not note.strip():
            raise ValueError("give a verdict or a note")
        row = {
            "ts": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
            "kind": "scenario",
            "scenario": scenario,
            "verdict": verdict,
            "note": scrub_text(note.strip())[:MAX_NOTE_CHARS],
        }
        self._append(self.notes_path, row)
        return row

    def add_line_decision(
        self, line_id: str, decision: str, note: str = "", *, now: datetime | None = None
    ) -> dict[str, Any]:
        if decision not in LINE_VERDICTS:
            raise ValueError("decision must be approve or reject")
        row = {
            "ts": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
            "kind": "line",
            "line_id": line_id.strip(),
            "decision": decision,
            "note": scrub_text(note.strip())[:MAX_NOTE_CHARS],
        }
        self._append(self.notes_path, row)
        return row

    def notes(self) -> list[dict[str, Any]]:
        return self._read(self.notes_path)

    def verdicts(self) -> dict[str, dict[str, Any]]:
        """Latest verdict per scenario, with every note of that scenario."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.notes():
            if r.get("kind") != "scenario":
                continue
            cur = out.setdefault(r["scenario"], {"verdict": "", "ts": "", "notes": []})
            if r.get("verdict"):
                cur["verdict"], cur["ts"] = r["verdict"], r["ts"]
            if r.get("note"):
                cur["notes"].append(r["note"])
        return out

    def line_decisions(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in self.notes():
            if r.get("kind") == "line":
                out[r["line_id"]] = {"decision": r["decision"], "note": r.get("note", "")}
        return out

    # ------------------------------------------------------------------ runs
    def add_run(self, row: dict[str, Any]) -> None:
        self._append(self.runs_path, row)

    def runs(self) -> list[dict[str, Any]]:
        return self._read(self.runs_path)

    def last_run(self, scenario: str) -> dict[str, Any] | None:
        for r in reversed(self.runs()):
            if r.get("scenario") == scenario:
                return r
        return None

    # ------------------------------------------------------------------ ledger (caps)
    def add_ledger(
        self, scenario: str, seconds: float, cost_inr: float, *, now: datetime | None = None
    ) -> None:
        self._append(
            self.ledger_path,
            {
                "ts": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                "day": ist_day(now),
                "scenario": scenario,
                "seconds": round(seconds, 1),
                "cost_inr": round(cost_inr, 2),
            },
        )

    def today(self, now: datetime | None = None) -> tuple[int, float]:
        """(calls placed, estimated spend in INR) for the current IST day."""
        day = ist_day(now)
        rows = [r for r in self._read(self.ledger_path) if r.get("day") == day]
        return len(rows), round(sum(float(r.get("cost_inr", 0)) for r in rows), 2)

    # ------------------------------------------------------------------ pending lines heard
    def pending_heard(self) -> OrderedDict[str, dict[str, Any]]:
        """line id -> {count, scenarios, source, last_run}, in first-heard order."""
        out: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for r in self._read(self.pending_path):
            cur = out.setdefault(
                r["line_id"],
                {"source": r.get("source", ""), "count": 0, "scenarios": [], "last_run": ""},
            )
            cur["count"] += 1
            if r.get("scenario") not in cur["scenarios"]:
                cur["scenarios"].append(r.get("scenario"))
            cur["last_run"] = r.get("run_id", "")
        return out
