# ruff: noqa: E501
"""Testers, invite links, feedback and the call ledger of the web channel (files under ``var/web/``).

* ``testers.json``  name, phone, SHA-256 of the personal link token (the token itself is shown once,
  never stored), expiry, revoked, consent time. Written atomically, mode 0600.
* ``feedback.jsonl`` thumbs / "mark wrong" with the message text the tester judged (scrubbed).
* ``ledger.jsonl``   one row per call placed (tester id, seconds, estimated INR): the per-tester and
  global daily caps read this.

The server and ``friday web ...`` are different processes; the file is re-read when it changes.
No database table: migrations end at 0018_refunds.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from friday.core.models import normalize_phone

IST = timezone(timedelta(hours=5, minutes=30))
FEEDBACK_KINDS = ("up", "down", "wrong")
MAX_NOTE = 1000


class InviteRefused(ValueError):
    """The invite cannot be made (bad name/number, number not allow-listed)."""


def allowed_numbers(settings: Any) -> set[str]:
    """Who may be a tester: the pilot allow-list plus the chatbot testers."""
    return set(getattr(settings, "pilot_allowed_numbers", []) or []) | set(
        getattr(settings, "chatbot_testers", []) or []
    )


def mask(phone: str | None) -> str:
    if not phone:
        return "<none>"
    return phone[:3] + "*" * max(0, len(phone) - 5) + phone[-2:] if len(phone) > 6 else "***"


def ist_day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(IST).date().isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Tester:
    id: str
    name: str
    phone: str
    token_hash: str
    created_at: str
    expires_at: str
    revoked_at: str | None = None
    consented_at: str | None = None

    def active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return self.revoked_at is None and now < datetime.fromisoformat(self.expires_at)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("token_hash")
        d["phone"] = mask(self.phone)
        d["active"] = self.active()
        return d


class Registry:
    def __init__(self, directory: Path | str = "var/web", now: Callable[[], datetime] | None = None) -> None:
        self.dir = Path(directory)
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._cache: list[Tester] = []
        self._mtime: float | None = None

    # ------------------------------------------------------------------ files
    @property
    def testers_path(self) -> Path:
        return self.dir / "testers.json"

    @property
    def feedback_path(self) -> Path:
        return self.dir / "feedback.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.dir / "ledger.jsonl"

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
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _load(self) -> list[Tester]:
        path = self.testers_path
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            self._cache, self._mtime = [], None
            return self._cache
        if mtime != self._mtime:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._cache = [Tester(**t) for t in data.get("testers", [])]
            except (ValueError, TypeError, OSError):
                self._cache = []
            self._mtime = mtime
        return self._cache

    def _save(self, testers: list[Tester]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.testers_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"testers": [asdict(t) for t in testers]}, f, indent=1)
        os.replace(tmp, self.testers_path)
        self._cache, self._mtime = testers, self.testers_path.stat().st_mtime_ns

    # ------------------------------------------------------------------ testers
    def all(self) -> list[Tester]:
        with self._lock:
            return list(self._load())

    def active(self, now: datetime | None = None) -> list[Tester]:
        now = now or self._now()
        return [t for t in self.all() if t.active(now)]

    def invite(
        self,
        name: str,
        phone: str,
        *,
        allowed: set[str],
        days: float = 30.0,
        default_cc: str = "+91",
        now: datetime | None = None,
    ) -> tuple[Tester, str]:
        """Create (or re-issue) a tester's personal link. Returns the tester and the TOKEN (shown once)."""
        name = " ".join((name or "").split())[:60]
        if not name:
            raise InviteRefused("a name is needed")
        try:
            number = normalize_phone(phone, default_cc)
        except ValueError:
            raise InviteRefused("that is not a valid phone number") from None
        if number not in allowed:
            raise InviteRefused(
                f"{mask(number)} is not in FRIDAY_PILOT_ALLOWED_NUMBERS or FRIDAY_CHATBOT_TESTERS: "
                "add the number there first (calls may only go to an allow-listed number)"
            )
        now = now or self._now()
        token = secrets.token_urlsafe(24)
        with self._lock:
            testers = list(self._load())
            for t in testers:  # one live link per number: a new invite replaces the old one
                if t.phone == number and t.revoked_at is None:
                    t.revoked_at = now.isoformat(timespec="seconds")
            tester = Tester(
                id=secrets.token_hex(4),
                name=name,
                phone=number,
                token_hash=hash_token(token),
                created_at=now.isoformat(timespec="seconds"),
                expires_at=(now + timedelta(days=days)).isoformat(timespec="seconds"),
            )
            testers.append(tester)
            self._save(testers)
        return tester, token

    def by_token(self, token: str, now: datetime | None = None) -> Tester | None:
        h = hash_token(token or "")
        now = now or self._now()
        for t in self.all():
            if secrets.compare_digest(t.token_hash, h) and t.active(now):
                return t
        return None

    def by_phone(self, phone: str, now: datetime | None = None) -> Tester | None:
        now = now or self._now()
        for t in self.all():
            if t.phone == phone and t.active(now):
                return t
        return None

    def find(self, ref: str) -> Tester | None:
        """By id or (case-insensitive) name; the newest match."""
        ref = (ref or "").strip().lower()
        hits = [t for t in self.all() if t.id == ref or t.name.lower() == ref]
        return hits[-1] if hits else None

    def revoke(self, ref: str, now: datetime | None = None) -> Tester | None:
        with self._lock:
            testers = list(self._load())
            hit = next((t for t in reversed(testers) if t.id == ref.strip().lower() or t.name.lower() == ref.strip().lower()), None)
            if hit is None:
                return None
            hit.revoked_at = (now or self._now()).isoformat(timespec="seconds")
            self._save(testers)
            return hit

    def set_consent(self, tester_id: str, now: datetime | None = None) -> None:
        with self._lock:
            testers = list(self._load())
            for t in testers:
                if t.id == tester_id and not t.consented_at:
                    t.consented_at = (now or self._now()).isoformat(timespec="seconds")
            self._save(testers)

    # ------------------------------------------------------------------ feedback
    def add_feedback(
        self, tester: Tester, kind: str, message_id: str, text: str, note: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if kind not in FEEDBACK_KINDS:
            raise ValueError("kind must be up, down or wrong")
        row = {
            "ts": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
            "tester_id": tester.id,
            "tester": tester.name,
            "kind": kind,
            "message_id": message_id,
            "text": (text or "")[:600],
            "note": (note or "").strip()[:MAX_NOTE],
        }
        self._append(self.feedback_path, row)
        return row

    def feedback(self, tester_ref: str | None = None) -> list[dict[str, Any]]:
        rows = self._read(self.feedback_path)
        if tester_ref:
            t = self.find(tester_ref)
            rows = [r for r in rows if r.get("tester_id") == (t.id if t else tester_ref)]
        return rows

    # ------------------------------------------------------------------ ledger
    def add_call(self, tester_id: str, seconds: float, cost_inr: float, now: datetime | None = None) -> None:
        self._append(
            self.ledger_path,
            {
                "ts": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                "day": ist_day(now),
                "tester_id": tester_id,
                "seconds": round(seconds, 1),
                "cost_inr": round(cost_inr, 2),
            },
        )

    def usage(self, tester_id: str | None = None, now: datetime | None = None) -> tuple[int, float]:
        """(calls, estimated INR) today (IST); one tester, or all when ``tester_id`` is None."""
        day = ist_day(now)
        calls, spend = 0, 0.0
        for r in self._read(self.ledger_path):
            if r.get("day") == day and (tester_id is None or r.get("tester_id") == tester_id):
                calls += 1
                spend += float(r.get("cost_inr") or 0)
        return calls, spend


def silent(fn: Any, *a: Any, **k: Any) -> Any:
    with contextlib.suppress(Exception):
        return fn(*a, **k)
    return None
