"""TranscriptStore: what is kept from a finished front-door call, and for how long.

Rules (DPDP; docs/SECURITY.md 5.4):
* kept ONLY when the caller has a user record with granted TERMS_PRIVACY consent; no
  consent (or a deleted user, or a rejected call) -> nothing is written;
* every turn is redacted first (secrets, phone numbers, long numbers, names), then the
  transcript is encrypted per field (AES-GCM via ``EncryptedJSON``);
* rows expire after ``Settings.quality_transcript_retention_days`` (30) - ``purge_expired``;
* "delete everything" removes the user's rows (``erase_user``; also called from the
  DataPurger so the existing erasure path covers it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger
from friday.core.models import ConsentKind, UserStatus
from friday.quality.labels import normalise_rating, validate_labels
from friday.quality.models import QualityCallRow
from friday.quality.redact import redact_text, spoken_names

log = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 30
MAX_NOTE_CHARS = 1000


@dataclass(frozen=True)
class CaptureResult:
    stored: bool
    reason: str  # "stored" or why not (no PII)


@dataclass
class StoredCall:
    call_id: str
    user_id: str
    stored_at: datetime
    expires_at: datetime
    meta: dict[str, Any]
    transcript: list[dict[str, Any]]
    labels: list[str]
    note: str | None
    rating: int | None


def _to_stored(row: QualityCallRow) -> StoredCall:
    return StoredCall(
        call_id=row.call_id,
        user_id=row.user_id,
        stored_at=row.stored_at,
        expires_at=row.expires_at,
        meta=dict(row.meta or {}),
        transcript=list(row.transcript or []),
        labels=list(row.labels or []),
        note=row.note,
        rating=row.rating,
    )


class TranscriptStore:
    def __init__(
        self, db: Any, repos: Any, *, clock: Clock | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.db = db
        self.repos = repos
        self.clock = clock or SystemClock()
        self.retention_days = max(1, int(retention_days))

    @classmethod
    def from_container(cls, c: Any) -> TranscriptStore:
        days = getattr(c.settings, "quality_transcript_retention_days", DEFAULT_RETENTION_DAYS)
        return cls(c.db, c.repos, clock=c.clock, retention_days=days)

    # ------------------------------------------------------------------ capture
    async def capture(self, summary: Any, result: Any) -> CaptureResult:
        """Called once per finished call. Writes only for a consenting, existing user."""
        if result is None or getattr(summary, "route", "serve") != "serve":
            return CaptureResult(False, "not a served call")
        collected = getattr(result, "collected", {}) or {}
        if str(collected.get("consented", "")).lower() == "false":
            return CaptureResult(False, "caller did not consent")
        phone = getattr(result, "to_phone", None)
        user = await self.repos.users.get_by_phone(phone) if phone else None
        if user is None or user.status == UserStatus.DELETED:
            return CaptureResult(False, "no user record (no consent)")
        if not await self.repos.consents.has(user.id, ConsentKind.TERMS_PRIVACY):
            return CaptureResult(False, "no storage consent")
        if not result.transcript.turns:
            return CaptureResult(False, "empty transcript")
        call_id = str(getattr(summary, "call_id", None) or result.call_id)
        profile = await self.repos.profiles.get(user.id)
        turns = [
            (t.speaker.value if hasattr(t.speaker, "value") else str(t.speaker), t.text)
            for t in result.transcript.turns
        ]
        names = spoken_names(
            [("friday" if s.lower() == "friday" else "callee", x) for s, x in turns],
            known=[getattr(profile, "name", None)],
        )
        stored_turns = [
            {
                "speaker": s,
                "text": redact_text(t.text, names=names),
                "language": t.language.value if t.language else None,
                "at": t.at.isoformat(),
            }
            for (s, _), t in zip(turns, result.transcript.turns, strict=True)
        ]
        now = self.clock.now()
        meta = {
            "kind": getattr(getattr(summary, "kind", None), "value", None),
            "outcome": getattr(summary, "outcome", None),
            "end_reason": getattr(summary, "end_reason", ""),
            "duration_s": getattr(summary, "duration_s", 0.0),
            "languages": list(getattr(summary, "languages", []) or []),
            "turns": len(stored_turns),
            "llm_turns": getattr(summary, "llm_turns", 0),
            "p95_ms": getattr(summary, "p95_ms", 0.0),
            "cost_inr_est": getattr(summary, "cost_inr_est", 0.0),
            "onboarded": bool(getattr(summary, "onboarded", False)),
        }
        async with self.db.session() as s:
            if (
                await s.execute(select(QualityCallRow.id).where(QualityCallRow.call_id == call_id))
            ).first():
                return CaptureResult(False, "already stored")
            s.add(
                QualityCallRow(
                    call_id=call_id,
                    user_id=user.id,
                    stored_at=now,
                    expires_at=now + timedelta(days=self.retention_days),
                    meta=meta,
                    transcript=stored_turns,
                    labels=[],
                )
            )
        return CaptureResult(True, "stored")

    # ------------------------------------------------------------------ read
    async def recent(self, limit: int = 20, *, labelled: bool | None = None) -> list[StoredCall]:
        async with self.db.session() as s:
            q = select(QualityCallRow).order_by(QualityCallRow.stored_at.desc())
            cap = 500 if labelled is not None else limit
            rows = list((await s.execute(q.limit(cap))).scalars())
        out = [_to_stored(r) for r in rows]
        if labelled is not None:
            out = [c for c in out if bool(c.labels) == labelled]
        return out[:limit]

    async def get(self, call_id: str) -> StoredCall | None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(QualityCallRow).where(QualityCallRow.call_id == call_id))
            ).scalar_one_or_none()
        return _to_stored(row) if row else None

    async def count(self) -> int:
        async with self.db.session() as s:
            return len(list((await s.execute(select(QualityCallRow.id))).scalars()))

    # ------------------------------------------------------------------ labels / rating
    async def _update(self, call_id: str, **values: Any) -> bool:
        async with self.db.session() as s:
            row = (
                await s.execute(select(QualityCallRow).where(QualityCallRow.call_id == call_id))
            ).scalar_one_or_none()
            if row is None:
                return False
            for k, v in values.items():
                setattr(row, k, v)
        return True

    async def add_labels(
        self, call_id: str, labels: list[str], *, note: str | None = None, remove: bool = False
    ) -> bool:
        """Attach (or with ``remove`` take off) labels from the fixed set; ``note`` replaces
        the free-text note. Unknown labels raise ValueError."""
        wanted = validate_labels(labels)
        call = await self.get(call_id)
        if call is None:
            return False
        current = [x for x in call.labels if x not in wanted] if remove else [
            *call.labels, *[x for x in wanted if x not in call.labels]
        ]
        values: dict[str, Any] = {"labels": current, "labelled_at": self.clock.now()}
        if note is not None:
            values["note"] = note[:MAX_NOTE_CHARS]
        return await self._update(call_id, **values)

    async def record_rating(self, call_id: str, rating: int | str) -> bool:
        """1-5 (or 'up'/'down' thumbs = 5/1). False when the call is not stored (the caller
        had not consented, or it expired) - a rating is never kept without its call row."""
        value = normalise_rating(rating)
        return await self._update(call_id, rating=value, rated_at=self.clock.now())

    # ------------------------------------------------------------------ retention / erasure
    async def purge_expired(self, now: datetime | None = None) -> int:
        cutoff = now or self.clock.now()
        async with self.db.session() as s:
            res = await s.execute(delete(QualityCallRow).where(QualityCallRow.expires_at <= cutoff))
            return int(res.rowcount or 0)  # type: ignore[attr-defined]

    async def erase_user(self, user_id: str) -> int:
        async with self.db.session() as s:
            res = await s.execute(delete(QualityCallRow).where(QualityCallRow.user_id == user_id))
            return int(res.rowcount or 0)  # type: ignore[attr-defined]


async def record_rating(c: Any, call_id: str, rating: int | str) -> bool:
    """Convenience: ``await record_rating(container, call_id, 4)``."""
    return await TranscriptStore.from_container(c).record_rating(call_id, rating)
