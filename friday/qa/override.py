# ruff: noqa: E501
"""The QA-only override, scoped to ONE number and to the time a QA call is being run.

While a QA session is active (``QaGuard.session`` activates it, nothing else does):

* lines marked PENDING_FOUNDER_APPROVAL may be spoken on that call to the founder's own number,
  and each pending line id that is spoken is logged (``note_pending_line``) so he can approve or
  reject it by id afterwards;
* the per-number daily/weekly caps, the per-user daily caps and the calling window of the W1
  ``CallGate`` are lifted for that one number only.

Outside a session every function here answers "no" and logs nothing: no pending line ever plays
outside QA. The override is re-checked against the live settings each time it is asked (live mode,
pilot profile, the number on the allow-list), so a wrong environment cannot widen it.

This module imports nothing heavy so that the gate, the playbook engine and the dial adapters can
all ask it without import cycles.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_ACTIVE: QaSession | None = None


@dataclass(frozen=True)
class QaSession:
    run_id: str
    scenario: str
    target: str = ""
    pending_log: Path | None = None


def activate(session: QaSession) -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = session


def deactivate() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None


def active() -> QaSession | None:
    return _ACTIVE


def _env_ok(settings: Any, number: str | None) -> bool:
    s = _ACTIVE
    if s is None or settings is None:
        return False
    if not (getattr(settings, "is_live", False) and getattr(settings, "is_pilot", False)):
        return False
    allow = list(getattr(settings, "pilot_allowed_numbers", []) or [])
    if allow != [s.target]:  # exactly the one allow-listed number
        return False
    return number is None or number == s.target


def override_allows(number: str | None, settings: Any) -> bool:
    """True when ``number`` is the QA target and a QA session is active: lifts caps and window."""
    return bool(number) and _env_ok(settings, number)


def pending_lines_allowed(settings: Any) -> bool:
    """True when a spoken pending line may be played right now (QA session active, env checked)."""
    return _env_ok(settings, None)


def note_pending_line(source: str, line_id: str) -> None:
    """Log a pending line that was spoken on a QA call. No-op outside a QA session."""
    s = _ACTIVE
    if s is None or s.pending_log is None:
        return
    row = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": s.run_id,
        "scenario": s.scenario,
        "source": source,
        "line_id": line_id,
    }
    try:
        s.pending_log.parent.mkdir(parents=True, exist_ok=True)
        with s.pending_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
