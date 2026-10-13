"""Append-only log of vendor utterances for the review queue.

The playbook engine calls ``record_turn`` once per vendor utterance::

    record_turn(*, call_id, playbook_id, step, text, intent, confident,
                source="heuristic", unhandled=False, repeat_count=0, path=None) -> bool

* ``call_id``: the real call id; only a salted hash (``call_ref``) is written.
* ``text``: the vendor's words; phone numbers become ``<phone>``, other 6+ digit runs ``<num>``
  and e-mail addresses ``<email>`` BEFORE anything touches disk.
* ``source``: ``heuristic`` or ``llm`` (who chose ``intent``); ``unhandled``: the script had no
  branch for the intent; ``repeat_count``: how often the vendor repeated themselves.
* Returns True when written. NEVER raises: a logging failure must never break a call.

One JSON line per utterance in ``var/learning/utterances.jsonl`` (``var/`` is git-ignored; set
``FRIDAY_LEARNING_LOG`` to move it). The salt lives in ``salt`` next to the log (or
``FRIDAY_LEARNING_SALT``). Real call data is never committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = _ROOT / "var" / "learning" / "utterances.jsonl"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# a run of digits with optional +91 / spaces / dashes holding 10+ digits (a phone number, even
# when the speech-to-text spaced it out: "98 76 54 32 10")
_PHONE = re.compile(r"(?<![\w])\+?\d(?:[\s\-.]?\d){9,}(?![\w])")
_LONG_NUM = re.compile(r"\d{6,}")


def log_path() -> Path:
    env = os.environ.get("FRIDAY_LEARNING_LOG")
    return Path(env) if env else DEFAULT_LOG


def mask_text(text: str) -> str:
    """Mask e-mails, phone numbers and any other 6+ digit sequence."""
    t = _EMAIL.sub("<email>", text or "")
    t = _PHONE.sub("<phone>", t)
    return _LONG_NUM.sub("<num>", t)


def _salt(path: Path) -> str:
    env = os.environ.get("FRIDAY_LEARNING_SALT")
    if env:
        return env
    sf = path.parent / "salt"
    try:
        return sf.read_text(encoding="utf-8").strip()
    except OSError:
        s = secrets.token_hex(16)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(s, encoding="utf-8")
        return s


def call_ref(call_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{call_id}".encode()).hexdigest()[:16]


def record_turn(
    *,
    call_id: str,
    playbook_id: str,
    step: str,
    text: str,
    intent: str,
    confident: bool,
    source: str = "heuristic",
    unhandled: bool = False,
    repeat_count: int = 0,
    path: Path | str | None = None,
) -> bool:
    """Append one masked utterance. Thread-safe. Never raises."""
    try:
        p = Path(path) if path else log_path()
        row: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "call_ref": call_ref(str(call_id), _salt(p)),
            "playbook_id": str(playbook_id),
            "step": str(step),
            "text": mask_text(str(text))[:500],
            "intent": str(intent),
            "confident": bool(confident),
            "source": "llm" if source == "llm" else "heuristic",
            "unhandled": bool(unhandled),
            "repeat_count": int(repeat_count),
        }
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception:  # noqa: BLE001 - logging must never break a call
        return False
