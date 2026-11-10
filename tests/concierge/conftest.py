# ruff: noqa: E501
"""Fixtures for the human desk: fake clock, in-memory store, fake directory/TOTP/family/bridge/pager. Nothing real is touched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from friday.concierge.audit import AuditLog
from friday.concierge.auth import Sessions
from friday.concierge.desk import DeskService
from friday.concierge.ports import (
    FakeBridge,
    FakeEmergency,
    FakeFamily,
    FakePager,
    FakeStaffDirectory,
    FakeTotp,
    MemberInfo,
    PartyView,
    StaffAccount,
)
from friday.concierge.service import ConciergeService, DeskSettings
from friday.concierge.store import InMemoryConciergeStore
from friday.core.clock import FakeClock

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
PARENT_NUMBER = "+919800000555"  # invented; lives only inside the fake bridge
PW = "correct-horse-fake"  # a test-only password for the fake directory; not a credential


@dataclass
class Rig:
    clock: FakeClock
    store: InMemoryConciergeStore
    audit: AuditLog
    directory: FakeStaffDirectory
    totp: FakeTotp
    family: FakeFamily
    emergency: FakeEmergency
    bridge: FakeBridge
    pager: FakePager
    service: ConciergeService
    desk: DeskService
    sessions: Sessions
    cfg: DeskSettings

    def staff(self, sid: str) -> StaffAccount:
        return self.directory._accounts[sid]

    def code(self, sid: str, code: str = "123456") -> str:
        self.totp.codes[sid] = code
        return code


def make_rig(cfg: DeskSettings | None = None) -> Rig:
    clock = FakeClock(T0)
    store = InMemoryConciergeStore()
    audit = AuditLog(store, clock)
    directory, totp, family, emergency, pager = FakeStaffDirectory(), FakeTotp(), FakeFamily(), FakeEmergency(), FakePager()
    bridge = FakeBridge(now=clock.now)
    bridge.raw[("par1", "parent")] = PARENT_NUMBER
    cfg = cfg or DeskSettings()
    for sid, role, lanes in (
        ("c1", "concierge", {"concierge"}), ("c2", "concierge", {"concierge"}), ("e1", "emergency", {"emergency", "concierge"}),
        ("e2", "emergency", {"emergency", "concierge"}), ("lead1", "lead", {"emergency", "concierge"}), ("rev1", "reviewer", {"concierge"}),
    ):
        directory.add(StaffAccount(sid, role, frozenset(lanes)), PW)
    family.add(MemberInfo("par1", "fam1", "parent", "par1", "Parent", "hinglish"))
    family.add(MemberInfo("kid1", "fam1", "child_admin", "par1", "Child", "en"))
    family.add(MemberInfo("sec1", "fam1", "second_contact", "par1", "Neighbour", "en"))
    family.add(MemberInfo("oth1", "fam2", "child_admin", "par2", "Other child", "en"))
    family.parties[("par1", "parent")] = PartyView("Parent", "+91 ••••• ••555", "hinglish")
    service = ConciergeService(store=store, audit=audit, clock=clock, family=family, directory=directory, emergency=emergency, bridge=bridge, settings=cfg)
    desk = DeskService(store=store, audit=audit, clock=clock, directory=directory, pager=pager, settings=cfg)
    sessions = Sessions(directory, totp, clock, idle_timeout_s=cfg.idle_timeout_s)
    return Rig(clock, store, audit, directory, totp, family, emergency, bridge, pager, service, desk, sessions, cfg)


@pytest.fixture
def rig() -> Rig:
    return make_rig()
