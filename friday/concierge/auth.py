# ruff: noqa: E501
"""C5: staff roles and sessions. Deny by default; password + TOTP (a port); 10-minute idle timeout; nothing can be exported.

* ``can(account, permission)`` is true only if the role grants it, the account is active and (for desk permissions) the account is on
  the emergency lane. An unknown permission, an unknown role, or any ``export*`` permission is False for every role (there is no export).
* ``Sessions.login`` needs the password AND a valid one-time code; bad tries are counted per staff id and lock that id for a while.
  The same fixed message is returned for an unknown id, a bad password and a bad code.
* A session token is 256 random bits; only its SHA-256 is kept. Every ``get`` checks the idle timeout and refreshes it; after the
  timeout the session is gone and a new login (password + code) is needed.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from friday.concierge.ports import StaffAccount, StaffDirectory, TotpVerifier

CONCIERGE_PERMS = frozenset({
    "queue.view", "request.view", "request.claim", "request.release", "request.note", "request.proof", "request.done", "request.escalate",
    "request.waiting_user", "contact.parent", "contact.child",
})
DESK_PERMS = frozenset({"desk.view", "desk.join", "desk.handback", "desk.close"})
LEAD_ONLY = frozenset({"request.assign", "roster.edit", "audit.view", "desk.review"})
GRANTS: dict[str, frozenset[str]] = {
    "concierge": CONCIERGE_PERMS,
    "emergency": CONCIERGE_PERMS | DESK_PERMS,
    "lead": CONCIERGE_PERMS | DESK_PERMS | LEAD_ONLY,
    "reviewer": frozenset({"queue.view", "request.view", "desk.view", "audit.view", "desk.review"}),
}
LANE_ONLY_EMERGENCY = DESK_PERMS | {"desk.review"}
LOGIN_FAIL_LIMIT = 5
LOGIN_LOCK_S = 15 * 60
BAD_LOGIN = "That did not work."  # one message for every failure: no hint which part was wrong


def can(account: StaffAccount | None, permission: str) -> bool:
    if account is None or not account.active or permission.startswith("export"):
        return False
    perms = GRANTS.get(account.role)
    if perms is None or permission not in perms:
        return False
    # concierge-only staff cannot take lane 2
    return not (permission in LANE_ONLY_EMERGENCY and "emergency" not in account.lanes and account.role != "reviewer")


@dataclass
class Session:
    staff_id: str
    csrf: str
    started: datetime
    last_seen: datetime


class Sessions:
    def __init__(self, directory: StaffDirectory, totp: TotpVerifier, clock, *, idle_timeout_s: int = 600) -> None:  # noqa: ANN001
        self.directory, self.totp, self.clock, self.idle = directory, totp, clock, timedelta(seconds=idle_timeout_s)
        self._by_hash: dict[str, Session] = {}
        self._fails: dict[str, list[datetime]] = {}

    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _locked(self, staff_id: str) -> bool:
        now = self.clock.now()
        recent = [t for t in self._fails.get(staff_id, []) if now - t < timedelta(seconds=LOGIN_LOCK_S)]
        self._fails[staff_id] = recent
        return len(recent) >= LOGIN_FAIL_LIMIT

    async def login(self, staff_id: str, password: str, code: str) -> tuple[str, Session] | None:
        """Returns (token, session) or None. Never says which factor failed."""
        sid = (staff_id or "")[:48]
        if self._locked(sid):
            return None
        acct = await self.directory.get(sid)
        pw_ok = await self.directory.verify_password(sid, password or "") if acct else False
        totp_ok = self.totp.verify(sid, (code or "").strip()) if pw_ok else False  # the code is only consumed after the password passed
        if acct is None or not acct.active or not pw_ok or not totp_ok:
            self._fails.setdefault(sid, []).append(self.clock.now())
            return None
        self._fails.pop(sid, None)
        token = secrets.token_urlsafe(32)
        now = self.clock.now()
        s = Session(sid, secrets.token_urlsafe(16), now, now)
        self._by_hash[self._h(token)] = s
        return token, s

    def peek_fail_count(self, staff_id: str) -> int:
        return len(self._fails.get(staff_id, []))

    async def get(self, token: str | None) -> tuple[Session, StaffAccount] | None:
        """The live session and its account, or None. Refreshes the idle clock; drops an idle or deactivated session."""
        if not token:
            return None
        h = self._h(token)
        s = self._by_hash.get(h)
        if s is None:
            return None
        now = self.clock.now()
        if now - s.last_seen > self.idle:
            del self._by_hash[h]
            return None
        acct = await self.directory.get(s.staff_id)
        if acct is None or not acct.active:
            del self._by_hash[h]
            return None
        s.last_seen = now
        return s, acct

    def was_expired(self, token: str | None) -> bool:
        s = self._by_hash.get(self._h(token)) if token else None
        return bool(s and self.clock.now() - s.last_seen > self.idle)

    def logout(self, token: str | None) -> bool:
        return bool(token and self._by_hash.pop(self._h(token), None))

    def revoke_staff(self, staff_id: str) -> int:
        gone = [h for h, s in self._by_hash.items() if s.staff_id == staff_id]
        for h in gone:
            del self._by_hash[h]
        return len(gone)
