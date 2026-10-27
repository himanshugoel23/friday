"""Adapters that turn what the system ALREADY has into evidence items: a finished call result, a
browser-run recorder, a confirmation text the user forwarded. Nothing new is recorded about the
call; these only read.

Rules that make the levels honest:
* ``observed`` only for facts our own code saw (the call was answered and ended in success, a
  screenshot the recorder took).
* A reference (order id, booking number) counts as ``vendor_stated`` only when its characters
  really occur in what the CALLEE said in the transcript. A reference the model wrote that nobody
  said is dropped, never promoted. Code decides, the model proposes.
* No raw document or image bytes are stored here: a receipt is a fingerprint plus extracted fields;
  a screenshot is kept (object store) only when the caller says it was painted over, else dropped.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from friday.calls.privacy import scrub
from friday.core.models import CallOutcome, CallResult, DialStatus, Speaker, Task, TaskResult
from friday.evidence.models import (
    EvidenceItem,
    EvidenceKind,
    EvidenceLevel,
    Redaction,
)

REF_KEYS = ("reference", "ref", "booking_ref", "order_id", "confirmation", "ticket", "token")
_ORDER_KEYS = {"order_id"}
_NON_ALNUM = re.compile(r"[^a-z0-9]")
MIN_REF_LEN = 4
MAX_SUMMARY = 200


def _norm(s: str) -> str:
    return _NON_ALNUM.sub("", s.lower())


def mask_ref(ref: str) -> str:
    """A long numeric reference shows only its last four digits; others are kept (they are the
    handle the user needs, e.g. ``BK-4821``)."""
    digits = re.sub(r"\D", "", ref)
    if len(digits) >= 8 and len(digits) >= len(_NON_ALNUM.sub("", ref.lower())) - 1:
        return "*" * (len(digits) - 4) + digits[-4:]
    return ref


def expiry(now: datetime, days: int) -> datetime:
    return now + timedelta(days=days)


def _callee_text(result: CallResult) -> str:
    return " ".join(t.text for t in result.transcript.turns if t.speaker == Speaker.CALLEE)


def _item(
    task: Task, kind: EvidenceKind, level: EvidenceLevel, now: datetime, days: int, **kw: Any
) -> EvidenceItem:
    return EvidenceItem(
        user_id=task.requester_user_id,
        task_id=task.id,
        kind=kind,
        level=level,
        captured_at=now,
        expires_at=expiry(now, days),
        **kw,
    )


def from_call(
    task: Task,
    result: CallResult,
    summary: TaskResult | None,
    *,
    now: datetime,
    retention_days: int = 90,
) -> list[EvidenceItem]:
    """Evidence from one finished call. Empty when the call was not answered or did not succeed."""
    if result.dial_status != DialStatus.ANSWERED or result.outcome != CallOutcome.SUCCESS:
        return []
    who = task.target.name if task.target else ""
    callee = _callee_text(result)
    out: list[EvidenceItem] = [
        _item(
            task,
            EvidenceKind.CALL_SUMMARY,
            EvidenceLevel.OBSERVED,
            now,
            retention_days,
            call_id=result.call_id,
            summary=scrub((summary.summary if summary else "")[:MAX_SUMMARY]),
            payload={
                "who": who[:80],
                "outcome": result.outcome.value,
                "seconds": str(int(result.telephony_seconds or 0)),
                "at": now.isoformat(),
            },
            source="call",
        )
    ]
    if result.recording_url:  # a pointer only; the recording itself keeps its own 30-day rule
        out.append(
            _item(
                task,
                EvidenceKind.CALL_RECORDING_REF,
                EvidenceLevel.OBSERVED,
                now,
                retention_days,
                call_id=result.call_id,
                payload={"call_id": result.call_id},
                source="call",
            )
        )
    if callee.strip():
        out.append(
            _item(
                task,
                EvidenceKind.TRANSCRIPT_EXCERPT,
                EvidenceLevel.VENDOR_STATED,
                now,
                retention_days,
                call_id=result.call_id,
                summary=scrub(callee)[:MAX_SUMMARY],
                source="call",
            )
        )
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for src in ((summary.details if summary else {}), result.collected):
        for key in REF_KEYS:
            value = (src.get(key) or "").strip()
            if value:
                candidates.append((key, value))
    heard = _norm(callee)
    for key, value in candidates:
        n = _norm(value)
        if len(n) < MIN_REF_LEN or n in seen or n not in heard:
            continue  # nobody said it on the call: not evidence
        seen.add(n)
        kind = EvidenceKind.ORDER_ID if key in _ORDER_KEYS else EvidenceKind.BOOKING_REF
        out.append(
            _item(
                task,
                kind,
                EvidenceLevel.VENDOR_STATED,
                now,
                retention_days,
                call_id=result.call_id,
                payload={"ref": value[:60], "key": key},
                source="call",
            )
        )
    return out


async def from_recorder(
    task: Task,
    rec: Any,
    *,
    now: datetime,
    masked: bool,
    store: Any = None,
    retention_days: int = 90,
) -> list[EvidenceItem]:
    """Evidence from a browser run (``connectors.recorder.StepRecorder``). The latest screenshot is
    kept only when ``masked`` (the caller verified the paint-over); an unmasked one is DROPPED. The
    order id the page showed (``rec.result``) is ``observed``: our browser read it."""
    out: list[EvidenceItem] = []
    shot = rec.latest_screenshot()
    if shot and masked:
        step = next(s for s in reversed(rec.steps) if s.screenshot)
        key = None
        if store is not None:
            key = await store.put(
                f"evidence/{task.requester_user_id}/{task.id}/{step.n}.png",
                shot,
                content_type="image/png",
            )
        out.append(
            _item(
                task,
                EvidenceKind.SCREENSHOT,
                EvidenceLevel.OBSERVED,
                now,
                retention_days,
                sha256=hashlib.sha256(shot).hexdigest(),
                object_key=key,
                redaction=Redaction.MASKED,
                source="browser",
                payload={"step": str(step.n), "host": urlparse(step.url).hostname or ""},
            )
        )
    result = rec.result or {}
    for key in REF_KEYS:
        value = str(result.get(key) or "").strip()
        if len(_norm(value)) >= MIN_REF_LEN:
            kind = EvidenceKind.ORDER_ID if key in _ORDER_KEYS else EvidenceKind.BOOKING_REF
            out.append(
                _item(
                    task,
                    kind,
                    EvidenceLevel.OBSERVED,
                    now,
                    retention_days,
                    payload={"ref": value[:60], "key": key},
                    source="browser",
                )
            )
            break
    return out


def from_user_text(
    task: Task, text: str, *, now: datetime, ref: str | None = None, retention_days: int = 90
) -> list[EvidenceItem]:
    """A confirmation SMS/email the user forwarded: ``user_supplied``. The text is scrubbed and
    cut; the optional ``ref`` (extracted by code, not by a model) becomes a reference item."""
    out = [
        _item(
            task,
            EvidenceKind.CONFIRMATION_TEXT,
            EvidenceLevel.USER_SUPPLIED,
            now,
            retention_days,
            summary=scrub(text)[:MAX_SUMMARY],
            source="user",
        )
    ]
    if ref and len(_norm(ref)) >= MIN_REF_LEN and _norm(ref) in _norm(text):
        out.append(
            _item(
                task,
                EvidenceKind.BOOKING_REF,
                EvidenceLevel.USER_SUPPLIED,
                now,
                retention_days,
                payload={"ref": ref[:60], "key": "reference"},
                source="user",
            )
        )
    return out


def from_receipt(
    task: Task, data: bytes, fields: dict[str, str], *, now: datetime, retention_days: int = 90
) -> EvidenceItem:
    """A receipt file the user sent: ONLY its sha-256 and the extracted fields are kept. The bytes
    are never stored (family documents live in the family's own Drive, HANDOFF decision)."""
    return _item(
        task,
        EvidenceKind.RECEIPT_FILE,
        EvidenceLevel.USER_SUPPLIED,
        now,
        retention_days,
        sha256=hashlib.sha256(data).hexdigest(),
        payload={k[:30]: v[:80] for k, v in list(fields.items())[:10]},
        source="user",
    )
