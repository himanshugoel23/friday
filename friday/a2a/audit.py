# ruff: noqa: E501
"""Audit log of every A2A message: who, to whom, method, task, state, a MASKED short text.

No secrets: ``redact_secrets`` first (OTP/PIN wording), then e-mails and phone numbers are masked,
then the text is clipped. Kept in a ring buffer, logged, and optionally appended to a JSONL file.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.voice.text import redact_secrets

log = get_logger(__name__)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s\-]{7,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _mask_phone(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group())
    return "*" * (len(digits) - 2) + digits[-2:]


def mask_text(text: str, limit: int = 160) -> str:
    t = redact_secrets(" ".join((text or "").split()))
    t = _EMAIL.sub("[email]", t)
    t = _PHONE.sub(_mask_phone, t)
    return t if len(t) <= limit else t[: limit - 1] + "…"


class A2AAudit:
    def __init__(self, *, path: str | Path | None = None, keep: int = 500, now: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else None
        self.records: deque[dict[str, Any]] = deque(maxlen=keep)
        self._now = now

    def record(self, *, direction: str, sender: str, receiver: str, method: str, task_id: str | None = None,
               root_task_id: str | None = None, parent_task_id: str | None = None, state: str | None = None,
               depth: int | None = None, text: str = "", error: str | None = None) -> dict[str, Any]:
        rec = {"ts": round(self._now(), 3), "dir": direction, "from": sender, "to": receiver, "method": method,
               "task": task_id, "root": root_task_id, "parent": parent_task_id, "state": state, "depth": depth,
               "text": mask_text(text), "error": mask_text(error or "", 100) or None}
        self.records.append(rec)
        log.info("a2a %s %s->%s %s task=%s state=%s", direction, sender, receiver, method, task_id, state)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError:
                log.info("a2a audit file not writable")
        return rec

    def for_root(self, root_task_id: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("root") == root_task_id]
