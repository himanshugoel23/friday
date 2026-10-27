# ruff: noqa: E501
"""The escalation store on memory AND on the real SQL tables (same suite), migration 0015, the SQL
files, encryption at rest, "delete everything" and the restart-safe compare-and-set operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from friday.core.clock import FakeClock
from friday.core.models import User, UserStatus
from friday.db import migrate
from friday.urgent.models import EscalationState, EscStatus, UserEscalationConfig
from friday.urgent.store import MemoryEscalationStore, SqlEscalationStore
from tests.urgent.conftest import USER_PHONE, at

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SW:
    store: object
    u1: str
    u2: str
    kind: str
    clock: FakeClock
    container: object = None


@pytest.fixture(params=["memory", "sql"])
async def sw(request, settings):
    clock = FakeClock(at(11))
    if request.param == "memory":
        yield SW(MemoryEscalationStore(clock), "u-one", "u-two", "memory", clock)
        return
    from friday.core.container import Container
    from friday.db import Database

    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    a = await c.repos.users.add(User(phone="+919800000401", status=UserStatus.ACTIVE))
    b = await c.repos.users.add(User(phone="+919800000402", status=UserStatus.ACTIVE))
    yield SW(SqlEscalationStore(db, clock), a.id, b.id, "sql", clock, c)
    await db.dispose()


def st(user: str, mid: str = "m1", **kw) -> EscalationState:
    base = dict(wait_s=300, max_calls=2, spacing_s=300, next_action_at=at(11, 5))
    base.update(kw)
    return EscalationState(user_id=user, message_id=mid, **base)


async def test_config_round_trip_and_isolation(sw):
    s = sw.store
    assert await s.get_config(sw.u1) is None
    await s.save_config(sw.u1, UserEscalationConfig(opted_in=True, number=USER_PHONE, minutes=3))
    await s.save_config(sw.u1, UserEscalationConfig(opted_in=True, number=USER_PHONE, minutes=4))  # update
    assert (await s.get_config(sw.u1)).minutes == 4
    assert await s.get_config(sw.u2) is None


async def test_create_is_idempotent_per_user_and_message(sw):
    s = sw.store
    a, made = await s.create(st(sw.u1))
    b, made2 = await s.create(st(sw.u1))
    c, made3 = await s.create(st(sw.u1, "m2"))
    d, made4 = await s.create(st(sw.u2))  # same message id, other user: separate
    assert made and not made2 and a.id == b.id
    assert made3 and c.id != a.id and made4 and d.id != a.id


async def test_get_is_scoped_to_the_user(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    assert await s.get(sw.u1, a.id) is not None
    assert await s.get(sw.u2, a.id) is None
    assert (await s.by_message(sw.u1, "m1")).id == a.id and await s.by_message(sw.u2, "m1") is None


async def test_due_lists_only_open_and_due(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    await s.create(st(sw.u1, "m2", next_action_at=at(12)))
    assert [x.id for x in await s.due(at(11, 5))] == [a.id]
    assert len(await s.due(at(12))) == 2
    await s.close(sw.u1, a.id, EscStatus.ACKED, "ack_button", at(11, 6))
    assert [x.message_id for x in await s.due(at(12))] == ["m2"]


async def test_claim_is_a_compare_and_set(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    assert not await s.claim(a.id, 1, at(11, 5))  # wrong expected count
    assert await s.claim(a.id, 0, at(11, 5))
    assert not await s.claim(a.id, 0, at(11, 5))  # second replica loses
    assert not await s.claim(a.id, 1, at(11, 5))  # still in flight
    got = await s.get(sw.u1, a.id)
    assert got.in_flight and got.calls_made == 1 and got.last_call_at == at(11, 5)
    assert await s.finish_attempt(a.id, result="no_answer", next_action_at=at(11, 10))
    assert not await s.finish_attempt(a.id, result="again", next_action_at=at(11, 15))  # nothing in flight
    got = await s.get(sw.u1, a.id)
    assert not got.in_flight and got.last_call_result == "no_answer" and got.next_action_at == at(11, 10)
    assert await s.claim(a.id, 1, at(11, 10))


async def test_close_only_closes_a_pending_row_and_never_reopens(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    assert await s.close(sw.u1, a.id, EscStatus.ACKED, "ack_button", at(11, 1))
    assert not await s.close(sw.u1, a.id, EscStatus.STOPPED, "late", at(11, 2))
    assert not await s.claim(a.id, 0, at(11, 5))  # a closed row cannot be claimed
    assert not await s.set_alert(a.id, ok=True, sent_at=at(11), next_action_at=at(11, 9))
    got = await s.get(sw.u1, a.id)
    assert got.status == EscStatus.ACKED and got.ack_at == at(11, 1) and got.next_action_at is None
    assert not await s.close(sw.u2, a.id, EscStatus.ACKED, "other user", at(11, 3))


async def test_close_for_message_and_for_user(sw):
    s = sw.store
    await s.create(st(sw.u1, "m1"))
    await s.create(st(sw.u1, "m2"))
    await s.create(st(sw.u2, "m1"))
    assert await s.close_for_message(sw.u1, "m1", EscStatus.ACKED, "x", at(11, 1)) == 1
    assert await s.close_open_for_user(sw.u1, EscStatus.STOPPED, "user_called", at(11, 2)) == 1
    assert len(await s.open_for_user(sw.u2)) == 1 and await s.open_for_user(sw.u1) == []


async def test_daily_count_ignores_refused_dials(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    b, _ = await s.create(st(sw.u1, "m2"))
    await s.claim(a.id, 0, at(11, 5))
    await s.finish_attempt(a.id, result="no_answer", next_action_at=at(11, 10))
    await s.claim(b.id, 0, at(11, 6))
    await s.finish_attempt(b.id, result="refused", next_action_at=None)
    assert await s.escalations_with_calls_since(sw.u1, at(0)) == 1
    assert await s.escalations_with_calls_since(sw.u1, at(12)) == 0


async def test_purge_finished_keeps_open_rows(sw):
    s = sw.store
    a, _ = await s.create(st(sw.u1))
    await s.create(st(sw.u1, "m2"))
    await s.close(sw.u1, a.id, EscStatus.ACKED, "x", at(11, 1))
    sw.clock.advance(days=31)
    assert await s.purge_finished(sw.clock.now() - timedelta(days=30)) == 1
    assert [x.message_id for x in await s.open_for_user(sw.u1)] == ["m2"]


async def test_delete_user_removes_only_that_user(sw):
    s = sw.store
    await s.save_config(sw.u1, UserEscalationConfig(opted_in=True, number=USER_PHONE))
    await s.create(st(sw.u1))
    await s.create(st(sw.u2))
    assert await s.delete_user(sw.u1) == 1
    assert await s.get_config(sw.u1) is None and await s.by_message(sw.u1, "m1") is None
    assert await s.by_message(sw.u2, "m1") is not None


async def test_the_users_number_is_encrypted_at_rest_and_rows_hold_no_personal_text(sw):
    if sw.kind != "sql":
        return
    await sw.store.save_config(sw.u1, UserEscalationConfig(opted_in=True, number="+919812345678"))
    await sw.store.create(st(sw.u1))
    async with sw.store.db.session() as sess:
        cfg_row = (await sess.execute(text("select config from urgent_escalation_configs"))).scalar_one()
        cols = [r[1] for r in (await sess.execute(text("pragma table_info(urgent_escalations)"))).all()]
    assert "9812345678" not in str(cfg_row)
    assert not {"number", "phone", "text", "reason", "caller_number"} & set(cols)


async def test_data_purger_covers_the_escalation_tables(sw):
    if sw.kind != "sql":
        return
    c = sw.container
    await sw.store.save_config(sw.u1, UserEscalationConfig(opted_in=True, number=USER_PHONE))
    await sw.store.create(st(sw.u1))
    await sw.store.create(st(sw.u2))
    counts = await c.repos.purger.purge_user(sw.u1)
    assert counts["urgent_escalations"] == 1 and counts["urgent_escalation_configs"] == 1
    assert await sw.store.by_message(sw.u1, "m1") is None and await sw.store.by_message(sw.u2, "m1")


def test_migration_0015_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0015_urgent_escalation"
    assert "0014_documents" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert {"urgent_escalations", "urgent_escalation_configs"} <= set(insp.get_table_names())
    uniques = {tuple(u["column_names"]) for u in insp.get_unique_constraints("urgent_escalations")}
    assert ("user_id", "message_id") in uniques
    migrate.downgrade(url, "0014_documents")
    assert not {"urgent_escalations", "urgent_escalation_configs"} & set(inspect(eng).get_table_names())
    assert "documents" in inspect(eng).get_table_names()
    migrate.upgrade(url)
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in ("urgent_escalations", "urgent_escalation_configs"):
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0015_urgent_escalation'" in schema
