"""Google connector storage (tables in friday/google/dbmodel.py).

Every method takes the ``user_id`` and filters by it: a user's connection is never reachable
through another user's id. Tokens are encrypted by the column type (AES-GCM, AAD
``table.column``); the dataclass below hides them from ``repr`` so a log line or traceback
cannot print them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select, update

from friday.db.repositories._base import Repo
from friday.google.dbmodel import GoogleConnectionRow, GoogleOAuthStateRow

CONNECTED = "connected"
NEEDS_RECONNECT = "needs_reconnect"


def state_id(nonce: str) -> str:
    """Database key of a state nonce (the nonce itself is never stored)."""
    return hashlib.sha256(nonce.encode()).hexdigest()


@dataclass
class GoogleConnection:
    user_id: str
    google_sub_hmac: str
    email: str | None
    scopes: list[str]
    status: str
    refresh_token: str = field(repr=False)
    access_token: str | None = field(default=None, repr=False)
    access_expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class PendingState:
    user_id: str
    code_verifier: str = field(repr=False)
    scopes: list[str]
    expires_at: datetime


def _conn(r: GoogleConnectionRow) -> GoogleConnection:
    return GoogleConnection(
        user_id=r.user_id,
        google_sub_hmac=r.google_sub_hmac,
        email=r.email,
        scopes=list(r.scopes or []),
        status=r.status,
        refresh_token=r.refresh_token,
        access_token=r.access_token,
        access_expires_at=r.access_expires_at,
        last_used_at=r.last_used_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


class GoogleRepo(Repo):
    # ------------------------------------------------------------------ connection
    async def get(self, user_id: str) -> GoogleConnection | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(GoogleConnectionRow).where(GoogleConnectionRow.user_id == user_id)
                )
            ).scalar_one_or_none()
            return _conn(row) if row else None

    async def upsert(self, conn: GoogleConnection) -> None:
        now = self.now()
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(GoogleConnectionRow).where(GoogleConnectionRow.user_id == conn.user_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = GoogleConnectionRow(user_id=conn.user_id, created_at=now)
                s.add(row)
            row.google_sub_hmac = conn.google_sub_hmac
            row.email = conn.email
            row.scopes = list(conn.scopes)
            row.refresh_token = conn.refresh_token
            row.access_token = conn.access_token
            row.access_expires_at = conn.access_expires_at
            row.status = conn.status
            row.updated_at = now

    async def set_access_token(
        self, user_id: str, token: str, expires_at: datetime, *, refresh_token: str | None = None
    ) -> None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(GoogleConnectionRow).where(GoogleConnectionRow.user_id == user_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.access_token = token
            row.access_expires_at = expires_at
            row.status = CONNECTED
            if refresh_token:  # Google rarely rotates it; keep the old one otherwise
                row.refresh_token = refresh_token
            row.updated_at = self.now()

    async def set_status(self, user_id: str, status: str) -> None:
        async with self.db.session() as s:
            values: dict = {"status": status, "updated_at": self.now()}
            if status == NEEDS_RECONNECT:
                values |= {"access_token": None, "access_expires_at": None}
            await s.execute(
                update(GoogleConnectionRow)
                .where(GoogleConnectionRow.user_id == user_id)
                .values(**values)
            )

    async def touch(self, user_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(
                update(GoogleConnectionRow)
                .where(GoogleConnectionRow.user_id == user_id)
                .values(last_used_at=self.now())
            )

    async def delete(self, user_id: str) -> bool:
        """Delete the connection AND any pending consent attempts. True if a row existed."""
        async with self.db.session() as s:
            await s.execute(
                delete(GoogleOAuthStateRow).where(GoogleOAuthStateRow.user_id == user_id)
            )
            res = await s.execute(
                delete(GoogleConnectionRow).where(GoogleConnectionRow.user_id == user_id)
            )
            return bool(res.rowcount)

    # ------------------------------------------------------------------ OAuth state
    async def create_state(
        self,
        user_id: str,
        nonce: str,
        *,
        code_verifier: str,
        scopes: list[str],
        expires_at: datetime,
    ) -> None:
        async with self.db.session() as s:
            s.add(
                GoogleOAuthStateRow(
                    id=state_id(nonce),
                    user_id=user_id,
                    code_verifier=code_verifier,
                    scopes=list(scopes),
                    expires_at=expires_at,
                    created_at=self.now(),
                )
            )

    async def peek_state(self, user_id: str, nonce: str) -> PendingState | None:
        """The pending (unused, unexpired) attempt, without consuming it."""
        async with self.db.session() as s:
            row = await s.get(GoogleOAuthStateRow, state_id(nonce))
            if (
                row is None
                or row.user_id != user_id
                or row.used_at is not None
                or row.expires_at <= self.now()
                or not row.code_verifier
            ):
                return None
            return PendingState(row.user_id, row.code_verifier, list(row.scopes), row.expires_at)

    async def consume_state(self, user_id: str, nonce: str) -> PendingState | None:
        """Atomically mark the attempt used (single use) and return it; None if unknown,
        expired, already used or bound to another user. The PKCE verifier is wiped."""
        now = self.now()
        async with self.db.session() as s:
            row = await s.get(GoogleOAuthStateRow, state_id(nonce))
            if row is None or row.user_id != user_id or not row.code_verifier:
                return None
            res = await s.execute(
                update(GoogleOAuthStateRow)
                .where(
                    GoogleOAuthStateRow.id == row.id,
                    GoogleOAuthStateRow.used_at.is_(None),
                    GoogleOAuthStateRow.expires_at > now,
                )
                .values(used_at=now)
            )
            if res.rowcount != 1:
                return None
            pending = PendingState(row.user_id, row.code_verifier, list(row.scopes), row.expires_at)
            await s.execute(
                update(GoogleOAuthStateRow)
                .where(GoogleOAuthStateRow.id == row.id)
                .values(code_verifier=None)
            )
            return pending

    async def purge_states(self, before: datetime) -> int:
        async with self.db.session() as s:
            res = await s.execute(
                delete(GoogleOAuthStateRow).where(GoogleOAuthStateRow.expires_at < before)
            )
            return int(res.rowcount or 0)
