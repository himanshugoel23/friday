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

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from friday.core.clock import Clock
from friday.core.models import User
from friday.db.repositories import UserRepo

WEAK_PINS = frozenset({"1234", "4321", "1212", "2580", "0852"} | {str(d) * 4 for d in range(10)})
PIN_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
LOCKOUT = timedelta(minutes=30)


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
    def __init__(self, pepper: str, *, fast: bool = False) -> None:
        self._pepper = pepper.encode()
        # ``fast`` lowers argon2 cost for tests only.
        self._ph = (
            PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
            if fast
            else PasswordHasher()
        )

    def _peppered(self, pin: str) -> str:
        return hmac.new(self._pepper, pin.encode(), hashlib.sha256).hexdigest()

    def hash(self, pin: str) -> str:
        return self._ph.hash(self._peppered(pin))

    def verify(self, pin_hash: str | None, pin: str) -> bool:
        if not pin_hash:
            return False
        try:
            return self._ph.verify(pin_hash, self._peppered(pin))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


class PinService:
    """Set/verify a user's PIN with attempt counting and a 30 min lockout."""

    def __init__(self, hasher: PinHasher, users: UserRepo, clock: Clock, max_attempts: int) -> None:
        self.hasher = hasher
        self.users = users
        self.clock = clock
        self.max_attempts = max_attempts

    def is_locked(self, user: User) -> bool:
        return (
            user.pin_failed_attempts >= self.max_attempts
            and self.clock.now() - user.updated_at < LOCKOUT
        )

    async def set_pin(self, user: User, pin: str) -> User:
        if pin_problem(pin):
            raise ValueError("invalid PIN")
        user.pin_hash = self.hasher.hash(pin)
        user.pin_failed_attempts = 0
        return await self.users.save(user)

    async def verify(self, user: User, pin: str) -> PinResult:
        if not user.pin_hash:
            return PinResult(PinCheck.NOT_SET)
        if self.is_locked(user):
            return PinResult(PinCheck.LOCKED)
        if user.pin_failed_attempts >= self.max_attempts:  # lock expired
            user.pin_failed_attempts = 0
        if self.hasher.verify(user.pin_hash, pin):
            if user.pin_failed_attempts:
                user.pin_failed_attempts = 0
                await self.users.save(user)
            return PinResult(PinCheck.OK)
        user.pin_failed_attempts += 1
        await self.users.save(user)
        left = max(0, self.max_attempts - user.pin_failed_attempts)
        return PinResult(PinCheck.LOCKED if left == 0 else PinCheck.WRONG, left)

    def matches(self, user: User, pin: str) -> bool:
        """Side-effect-free check (E18: unprompted PIN-looking message)."""
        return self.hasher.verify(user.pin_hash, pin)
