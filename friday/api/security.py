"""Friday PIN: validation, salted+peppered argon2id hashing, verification with lockout.

The raw PIN is never stored, logged, echoed or sent to the LLM. It is peppered
with ``Settings.secret_key`` (HMAC-SHA256) before argon2id hashing, so a DB
leak alone is not enough to brute-force 10^4 PINs offline.

Owner: Backend Engineer A.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from friday.core.clock import Clock
from friday.core.models import User
from friday.db.repositories import PinLock, PinLockRepo, UserRepo

WEAK_PINS = frozenset({"1234", "4321", "1212", "2580", "0852"} | {str(d) * 4 for d in range(10)})
PIN_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
LOCKOUT = timedelta(minutes=30)
LOCK_STEPS = (LOCKOUT, timedelta(hours=24))  # then support-only (SECURITY-23)


def extract_pin(text: str | None) -> str | None:
    """The single 4-digit group in ``text`` (spaces between digits tolerated)."""
    if not text:
        return None
    compact = re.sub(r"(?<=\d)[ \-](?=\d)", "", text.strip())
    found = PIN_RE.findall(compact)
    return found[0] if len(found) == 1 else None


def pin_problem(pin: str) -> str | None:
    if not re.fullmatch(r"\d{4}", pin):
        return "format"
    if pin in WEAK_PINS:
        return "weak"
    return None


class PinCheck(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"
    NOT_SET = "not_set"


@dataclass
class PinResult:
    status: PinCheck
    attempts_left: int = 0


class PinHasher:
    """argon2id over HMAC(pepper, PIN). SECURITY-30: the pepper is its own key
    (``Settings.key_material("pin_pepper")``); ``legacy`` peppers (wave-1 used the app
    secret) still verify so existing users aren't locked out, and are re-hashed on the
    next successful entry."""

    def __init__(
        self, pepper: str | bytes, *, fast: bool = False, legacy: tuple[str | bytes, ...] = ()
    ) -> None:
        def _b(p: str | bytes) -> bytes:
            return p.encode() if isinstance(p, str) else p

        self._pepper = _b(pepper)
        self._legacy = tuple(_b(p) for p in legacy if p)
        # ``fast`` lowers argon2 cost for tests only.
        self._ph = (
            PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
            if fast
            else PasswordHasher()
        )

    @staticmethod
    def _peppered(pepper: bytes, pin: str) -> str:
        return hmac.new(pepper, pin.encode(), hashlib.sha256).hexdigest()

    def hash(self, pin: str) -> str:
        return self._ph.hash(self._peppered(self._pepper, pin))

    def check(self, pin_hash: str | None, pin: str) -> str | None:
        """"current" / "legacy" (matched an old pepper) / None."""
        if not pin_hash:
            return None
        for label, pepper in (("current", self._pepper), *(("legacy", p) for p in self._legacy)):
            try:
                if self._ph.verify(pin_hash, self._peppered(pepper, pin)):
                    return label
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                continue
        return None

    def verify(self, pin_hash: str | None, pin: str) -> bool:
        return self.check(pin_hash, pin) is not None


class PinService:
    """Set/verify a user's PIN. SECURITY-23 progressive lockout: ``max_attempts`` wrong
    PINs -> 30 min, the next round -> 24 h, the third -> locked until support verifies.
    Lock state is persisted (``pin_locks``), so it survives restarts and replicas."""

    def __init__(
        self,
        hasher: PinHasher,
        users: UserRepo,
        clock: Clock,
        max_attempts: int,
        locks: PinLockRepo | Any | None = None,
    ) -> None:
        if locks is not None and not isinstance(locks, PinLockRepo):
            # Wave-1 call shape passed the AuditRepo: same database, dedicated table now.
            locks = PinLockRepo(locks.db, clock)
        self.hasher = hasher
        self.users = users
        self.clock = clock
        self.max_attempts = max_attempts
        self.locks = locks
        self._mem_locks: dict[str, PinLock] = {}  # only when no repo (unit tests)

    async def _lock(self, user_id: str) -> PinLock:
        if self.locks is not None:
            return await self.locks.get(user_id)
        return self._mem_locks.get(user_id) or PinLock(user_id=user_id)

    async def _save_lock(self, lock: PinLock) -> None:
        if self.locks is not None:
            await self.locks.save(lock)
        else:
            self._mem_locks[lock.user_id] = lock

    async def is_locked(self, user: User) -> bool:
        return (await self._lock(user.id)).active(self.clock.now())

    async def freeze(self, user: User, *, reason: str, hours: int = 24) -> PinLock:
        """Re-registration / SIM-swap freeze of every PIN-gated action."""
        lock = await self._lock(user.id)
        until = self.clock.now() + timedelta(hours=hours)
        lock.locked_until = max(lock.locked_until or until, until)
        lock.reason = reason
        await self._save_lock(lock)
        return lock

    async def set_pin(self, user: User, pin: str) -> User:
        if pin_problem(pin):
            raise ValueError("invalid PIN")
        user.pin_hash = self.hasher.hash(pin)
        user.pin_failed_attempts = 0
        return await self.users.save(user)

    async def verify(self, user: User, pin: str) -> PinResult:
        if not user.pin_hash:
            return PinResult(PinCheck.NOT_SET)
        if await self.is_locked(user):
            return PinResult(PinCheck.LOCKED)
        if user.pin_failed_attempts >= self.max_attempts:  # lock expired: new round
            user.pin_failed_attempts = 0
        which = self.hasher.check(user.pin_hash, pin)
        if which is not None:
            dirty = bool(user.pin_failed_attempts)
            user.pin_failed_attempts = 0
            if which == "legacy":  # migrate to the dedicated pepper
                user.pin_hash = self.hasher.hash(pin)
                dirty = True
            if dirty:
                await self.users.save(user)
            lock = await self._lock(user.id)
            if lock.strikes and not lock.support_required:
                lock.strikes, lock.locked_until = 0, None
                await self._save_lock(lock)
            return PinResult(PinCheck.OK)
        user.pin_failed_attempts += 1
        await self.users.save(user)
        left = max(0, self.max_attempts - user.pin_failed_attempts)
        if left == 0:
            lock = await self._lock(user.id)
            lock.strikes += 1
            if lock.strikes <= len(LOCK_STEPS):
                lock.locked_until = self.clock.now() + LOCK_STEPS[lock.strikes - 1]
            else:
                lock.support_required = True
            lock.reason = "lockout"
            await self._save_lock(lock)
        return PinResult(PinCheck.LOCKED if left == 0 else PinCheck.WRONG, left)

    def matches(self, user: User, pin: str) -> bool:
        """Side-effect-free check (E18: unprompted PIN-looking message)."""
        return self.hasher.verify(user.pin_hash, pin)
