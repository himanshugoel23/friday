# ruff: noqa: E501
"""C5 (roles, TOTP port, idle timeout, deny by default, no export) and C6 (append-only hash chain). Tested with fakes."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from friday.concierge.audit import ACTIONS, AuditRefused
from friday.concierge.auth import BAD_LOGIN, GRANTS, LOGIN_FAIL_LIMIT, can
from friday.concierge.ports import StaffAccount
from friday.concierge.service import Denied
from tests.concierge.conftest import PW


# ---------------------------------------------------------------- C5
def test_deny_by_default_unknown_permission_role_and_inactive():
    c = StaffAccount("x", "concierge", frozenset({"concierge"}))
    assert can(c, "request.claim")
    assert not can(c, "request.assign") and not can(c, "roster.edit") and not can(c, "audit.view")
    assert not can(c, "nonsense.permission") and not can(None, "request.claim")
    assert not can(StaffAccount("y", "janitor", frozenset({"concierge"})), "queue.view")
    assert not can(StaffAccount("z", "concierge", frozenset({"concierge"}), active=False), "queue.view")


def test_nobody_can_export_not_even_a_lead():
    every = {p for perms in GRANTS.values() for p in perms}
    assert not [p for p in every if p.startswith("export")]
    for role in GRANTS:
        for perm in ("export", "export.requests", "export.audit", "exportall"):
            assert not can(StaffAccount("a", role, frozenset({"emergency", "concierge"})), perm)


def test_concierge_only_staff_cannot_take_lane_2():
    assert not can(StaffAccount("c", "concierge", frozenset({"concierge"})), "desk.join")
    assert not can(StaffAccount("e", "emergency", frozenset({"concierge"})), "desk.join")  # right role, not trained for lane 2
    assert can(StaffAccount("e", "emergency", frozenset({"emergency"})), "desk.join")


async def test_login_needs_password_and_a_one_time_code_and_the_code_works_once(rig):
    s = rig.sessions
    assert await s.login("c1", PW, "000000") is None  # no code issued
    rig.code("c1")
    assert await s.login("c1", "wrong", "123456") is None
    assert await s.login("c1", PW, "999999") is None
    ok = await s.login("c1", PW, "123456")
    assert ok is not None
    assert await s.login("c1", PW, "123456") is None  # replay
    assert await s.login("ghost", PW, "123456") is None


async def test_failures_are_indistinguishable_and_lock_the_id(rig):
    rig.code("c1")
    for _ in range(LOGIN_FAIL_LIMIT):
        assert await rig.sessions.login("c1", "bad", "123456") is None
    assert await rig.sessions.login("c1", PW, "123456") is None  # locked even with the right factors
    rig.clock.advance(minutes=16)
    assert await rig.sessions.login("c1", PW, "123456") is not None
    assert BAD_LOGIN == "That did not work."


async def test_idle_timeout_is_ten_minutes_and_activity_extends_it(rig):
    rig.code("c1")
    token, _ = await rig.sessions.login("c1", PW, "123456")
    rig.clock.advance(minutes=9)
    assert await rig.sessions.get(token) is not None  # refreshes
    rig.clock.advance(minutes=9)
    assert await rig.sessions.get(token) is not None
    rig.clock.advance(minutes=10, seconds=1)
    assert await rig.sessions.get(token) is None
    rig.clock.advance(seconds=1)
    assert await rig.sessions.get(token) is None  # gone for good: a new login (password + code) is needed


async def test_a_deactivated_staff_session_dies_at_once(rig):
    rig.code("c1")
    token, _ = await rig.sessions.login("c1", PW, "123456")
    rig.directory.deactivate("c1")
    assert await rig.sessions.get(token) is None


async def test_tokens_are_not_kept_in_the_clear(rig):
    rig.code("c1")
    token, _ = await rig.sessions.login("c1", PW, "123456")
    assert token not in rig.sessions._by_hash and len(token) >= 40


# ---------------------------------------------------------------- C6
async def test_chain_verifies_and_every_staff_action_is_logged_without_text(rig):
    r = (await rig.service.intake("par1", {"summary": "Order atta and rice from the corner shop", "category": "grocery"})).request_id
    s = rig.staff("c1")
    await rig.service.queue(s)
    await rig.service.claim(s, r)
    await rig.service.view(s, r)
    await rig.service.note(s, r, "Shop confirmed stock, will pack by noon")
    await rig.service.proof(s, r, "call_note", "Spoke to shop owner at 10:05")
    await rig.service.contact(s, r, "parent")
    await rig.service.done(s, r)
    with pytest.raises(Denied):
        await rig.service.assign(s, r, "c2")
    es = await rig.audit.entries()
    assert [e.action for e in es] == ["intake", "queue_view", "claim", "request_view", "note", "proof", "contact_parent", "done", "denied"]
    assert await rig.audit.verify() is None
    blob = repr([(e.staff_id, e.action, e.target_id, e.counts) for e in es])
    for secret in ("atta", "rice", "corner shop", "Shop confirmed", "owner", "9800000555", "10:05"):
        assert secret not in blob
    assert all(isinstance(v, int) for e in es for v in e.counts.values())


async def test_tampering_deleting_or_reordering_is_detected(rig):
    for _ in range(5):
        await rig.service.queue(rig.staff("c1"))
    assert await rig.audit.verify() is None
    log = rig.store._audit
    saved = list(log)
    log[2] = replace(log[2], staff_id="someone_else")  # edit
    assert await rig.audit.verify() == 3
    rig.store._audit = saved[:2] + saved[3:]  # delete one in the middle
    assert await rig.audit.verify() == 4
    rig.store._audit = [saved[1], saved[0], *saved[2:]]  # reorder
    assert await rig.audit.verify() == 2
    rig.store._audit = saved
    assert await rig.audit.verify() is None


async def test_the_writer_refuses_text_and_unknown_actions(rig):
    with pytest.raises(AuditRefused):
        await rig.audit.record("c1", "note", "r1", text_len="five")  # counts must be integers
    with pytest.raises(AuditRefused):
        await rig.audit.record("c1", "note", "r1", Text=3)  # keys are plain words
    with pytest.raises(AuditRefused):
        await rig.audit.record("c1", "note", "please call mom on 98xxxx")  # target must be an id
    with pytest.raises(AuditRefused):
        await rig.audit.record("c1", "free_text_action", "r1")
    with pytest.raises(AuditRefused):
        await rig.audit.record("c1", "note", "r1", flag=True)
    assert len(await rig.audit.entries()) == 0


def test_the_store_interface_has_no_audit_update_or_delete():
    from friday.concierge import dbmodel, store

    for cls in (store.InMemoryConciergeStore, dbmodel.DbConciergeStore):
        names = [n for n in dir(cls) if n.startswith("audit")]
        assert sorted(names) == ["audit_all", "audit_append", "audit_last"]
    assert not re.search(r"update\(ConciergeAuditRow|delete\(ConciergeAuditRow", Path(dbmodel.__file__).read_text())


def test_audit_action_list_has_no_export_action_except_the_denial():
    assert [a for a in ACTIONS if "export" in a] == ["export_denied"]


async def test_db_store_roundtrip_and_chain_survive_a_restart(db, rig):
    from friday.concierge.audit import AuditLog
    from friday.concierge.dbmodel import DbConciergeStore
    from friday.concierge.service import ConciergeService

    store = DbConciergeStore(db)
    audit = AuditLog(store, rig.clock)
    svc = ConciergeService(store=store, audit=audit, clock=rig.clock, family=rig.family, directory=rig.directory, emergency=rig.emergency, bridge=rig.bridge)
    r = (await svc.intake("par1", {"summary": "Book a cab to the clinic", "category": "cab"})).request_id
    await svc.claim(rig.staff("c1"), r)
    await svc.proof(rig.staff("c1"), r, "call_note", "cab booked")
    await svc.done(rig.staff("c1"), r)
    store2 = DbConciergeStore(db)  # "restart"
    audit2 = AuditLog(store2, rig.clock)
    assert await audit2.verify() is None and len(await audit2.entries()) == 4
    req = await store2.request_get(r)
    assert req.status.value == "done" and req.summary == "Book a cab to the clinic"
    await audit2.record("c1", "queue_view", "", rows=0)
    assert await audit2.verify() is None
    assert await store2.erase_parent("par1") == {"requests": 1, "docs": 0}
    assert await store2.request_get(r) is None and await audit2.verify() is None  # the audit keeps ids and counts only
