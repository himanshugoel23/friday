# ruff: noqa: E501
"""Ports of the desk and their fakes. Real adapters are unbuilt [U]: the masked-contact bridge (Robin lines), the TOTP
verifier, the staff directory and the pager. Nothing in this package imports a provider."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

# --------------------------------------------------------------------------- staff
STAFF_ROLES = ("concierge", "emergency", "lead", "reviewer")


@dataclass(frozen=True)
class StaffAccount:
    id: str  # opaque staff id, shown in the watermark and the audit log (no name)
    role: str  # one of STAFF_ROLES
    lanes: frozenset[str] = frozenset({"concierge"})
    active: bool = True


@runtime_checkable
class StaffDirectory(Protocol):
    async def get(self, staff_id: str) -> StaffAccount | None: ...
    async def verify_password(self, staff_id: str, password: str) -> bool: ...


@runtime_checkable
class TotpVerifier(Protocol):
    def verify(self, staff_id: str, code: str) -> bool: ...  # [U] real RFC 6238 verifier with replay protection


class FakeStaffDirectory:
    """Test directory. Passwords are kept as scrypt-free fake hashes: only for tests."""

    def __init__(self) -> None:
        self._accounts: dict[str, StaffAccount] = {}
        self._pw: dict[str, str] = {}

    def add(self, account: StaffAccount, password: str) -> None:
        self._accounts[account.id] = account
        self._pw[account.id] = hashlib.sha256(("fake:" + password).encode()).hexdigest()

    def deactivate(self, staff_id: str) -> None:
        a = self._accounts[staff_id]
        self._accounts[staff_id] = StaffAccount(a.id, a.role, a.lanes, False)

    async def get(self, staff_id: str) -> StaffAccount | None:
        return self._accounts.get(staff_id)

    async def verify_password(self, staff_id: str, password: str) -> bool:
        want = self._pw.get(staff_id)
        got = hashlib.sha256(("fake:" + password).encode()).hexdigest()
        return want is not None and hmac.compare_digest(want, got)


class FakeTotp:
    """``codes[staff_id]`` is the currently valid code; a code works once (replay protection)."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self._used: set[tuple[str, str]] = set()

    def verify(self, staff_id: str, code: str) -> bool:
        if self.codes.get(staff_id) != code or (staff_id, code) in self._used:
            return False
        self._used.add((staff_id, code))
        return True


# --------------------------------------------------------------------------- family side
@dataclass(frozen=True)
class MemberInfo:
    member_id: str
    family_id: str
    role: str  # parent | child_admin | second_contact
    parent_id: str  # the parent this member is, or looks after
    label: str = ""  # "Parent", never a name unless the family set a short label
    language: str = "hinglish"


@dataclass(frozen=True)
class PartyView:
    label: str
    masked_phone: str  # already masked, e.g. "+91 ••••• ••210"; the port never returns a raw number to the desk
    language: str


@runtime_checkable
class FamilyLookup(Protocol):
    async def member(self, member_id: str) -> MemberInfo | None: ...
    async def party(self, parent_id: str, who: str) -> PartyView | None: ...  # who: parent | child


class FakeFamily:
    def __init__(self) -> None:
        self.members: dict[str, MemberInfo] = {}
        self.parties: dict[tuple[str, str], PartyView] = {}

    def add(self, info: MemberInfo) -> None:
        self.members[info.member_id] = info

    async def member(self, member_id: str) -> MemberInfo | None:
        return self.members.get(member_id)

    async def party(self, parent_id: str, who: str) -> PartyView | None:
        return self.parties.get((parent_id, who))


# --------------------------------------------------------------------------- AI emergency path (friday/robin)
@runtime_checkable
class EmergencyReroute(Protocol):
    async def reroute(self, *, member_id: str, parent_id: str, reason: str) -> str | None: ...  # -> incident id


class FakeEmergency:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def reroute(self, *, member_id: str, parent_id: str, reason: str) -> str | None:
        self.calls.append((member_id, parent_id, reason))
        return f"inc{len(self.calls)}"


# --------------------------------------------------------------------------- masked contact (C7)
@dataclass(frozen=True)
class MaskedLink:
    link_id: str
    party: str  # parent | child
    masked_label: str  # what staff see: "Parent via Robin line 2", never a number
    request_id: str
    expires_at: datetime


@runtime_checkable
class MaskedBridge(Protocol):
    """Connects a staff member to a party THROUGH a Robin line. The bridge resolves the real number itself; the desk passes ids only
    and never receives a raw number back. [U] the real bridge (telephony + number pool) is unbuilt."""

    async def connect(self, *, staff_id: str, request_id: str, parent_id: str, party: str) -> MaskedLink | None: ...
    async def end(self, link_id: str) -> bool: ...


class FakeBridge:
    def __init__(self, now=lambda: datetime(2026, 1, 1)) -> None:  # noqa: ANN001
        self._now = now
        self.links: dict[str, MaskedLink] = {}
        self.ended: list[str] = []
        self.refuse = False
        # the raw numbers live only inside the bridge; tests assert they never appear in anything the desk shows
        self.raw: dict[tuple[str, str], str] = {}

    async def connect(self, *, staff_id: str, request_id: str, parent_id: str, party: str) -> MaskedLink | None:
        if self.refuse or party not in ("parent", "child"):
            return None
        link = MaskedLink(f"ml{len(self.links) + 1}", party, f"{party.capitalize()} via Robin line {len(self.links) % 3 + 1}", request_id, self._now() + timedelta(minutes=15))
        self.links[link.link_id] = link
        return link

    async def end(self, link_id: str) -> bool:
        if link_id in self.links and link_id not in self.ended:
            self.ended.append(link_id)
            return True
        return False


# --------------------------------------------------------------------------- pager (lane 2)
@runtime_checkable
class Pager(Protocol):
    async def page(self, staff_id: str, handoff_id: str) -> bool: ...  # [U] real pager (push/phone) unbuilt


class FakePager:
    def __init__(self) -> None:
        self.paged: list[tuple[str, str]] = []
        self.deaf: set[str] = set()

    async def page(self, staff_id: str, handoff_id: str) -> bool:
        self.paged.append((staff_id, handoff_id))
        return staff_id not in self.deaf


def mask_phone(number: str | None) -> str:
    """'+919876543210' -> '+91 ••••• ••210'. Anything that is not a number gives a plain placeholder."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if len(digits) < 8:
        return "••••••"
    return f"+{digits[:2]} ••••• ••{digits[-3:]}"
