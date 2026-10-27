# ruff: noqa: E501
"""Migration 0013, SQL repository, encryption at rest, retention and "delete everything"."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from friday.core.models import Task, TaskSpec, TaskType, User
from friday.db import migrate
from friday.db.objectstore import LocalObjectStore
from friday.db.repositories import make_repositories
from friday.db.retention import expire_evidence, run_retention
from friday.evidence.models import (
    ClaimType,
    DoneClaim,
    EvidenceItem,
    EvidenceKind,
    EvidenceLevel,
    ProofStatus,
)
from friday.evidence.store import MemoryEvidenceStore

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ migration + sql files
def test_migration_0013_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0015_urgent_escalation"
    assert "0013_evidence" in doctor.known_revisions()
    assert "0012_receptionist_spam" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert {"evidence_items", "done_claims"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("evidence_items")}
    assert {
        "user_id",
        "task_id",
        "kind",
        "level",
        "summary",
        "payload",
        "object_key",
        "sha256",
        "expires_at",
        "shareable",
        "redaction",
    } <= cols
    assert not {c for c in cols if "bytes" in c or c in ("data", "content", "blob")}
    migrate.downgrade(url)
    assert not {"evidence_items", "done_claims"} & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in ("evidence_items", "done_claims"):
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0013_evidence'" in schema


# ------------------------------------------------------------------ repository
@pytest.fixture
def repos(db, clock):
    return make_repositories(db, clock, "test-secret")


async def seed(repos, phone: str, clock, ref="BK4821", key=None):
    user = await repos.users.add(User(phone=phone))
    task = Task(
        requester_user_id=user.id,
        type=TaskType.BOOKING,
        spec=TaskSpec(type=TaskType.BOOKING, goal="table"),
    )
    await repos.tasks.add(task)
    now = clock.now()
    items = [
        EvidenceItem(
            user_id=user.id,
            task_id=task.id,
            kind=EvidenceKind.CALL_SUMMARY,
            level=EvidenceLevel.OBSERVED,
            summary="secret words from the call",
            payload={"who": "Spice Hub"},
            captured_at=now,
            expires_at=now + timedelta(days=90),
        ),
        EvidenceItem(
            user_id=user.id,
            task_id=task.id,
            kind=EvidenceKind.BOOKING_REF,
            level=EvidenceLevel.VENDOR_STATED,
            payload={"ref": ref},
            captured_at=now,
            expires_at=now + timedelta(days=90),
            object_key=key,
        ),
    ]
    await repos.evidence.add_items(items)
    claim = DoneClaim(
        user_id=user.id,
        task_id=task.id,
        claim_type=ClaimType.BOOKED,
        required_level=EvidenceLevel.OBSERVED,
        status=ProofStatus.PROVEN,
        evidence_ids=[i.id for i in items],
    )
    await repos.evidence.save_claim(claim)
    return user, task, items


async def test_round_trip_and_two_user_isolation(repos, clock):
    u1, t1, items = await seed(repos, "+919800000001", clock)
    u2, t2, _ = await seed(repos, "+919800000002", clock, ref="XX0000")
    got = await repos.evidence.list_for_task(u1.id, t1.id)
    assert [i.id for i in got] == [i.id for i in items] or {i.id for i in got} == {
        i.id for i in items
    }
    assert {i.payload.get("ref") for i in got} >= {"BK4821"}
    assert await repos.evidence.list_for_task(u2.id, t1.id) == []  # wrong user sees nothing
    assert await repos.evidence.get_claim(u2.id, t1.id) is None
    claim = await repos.evidence.get_claim(u1.id, t1.id)
    assert claim.status == ProofStatus.PROVEN and claim.claim_type == ClaimType.BOOKED
    # re-judging replaces the one claim per task
    await repos.evidence.save_claim(claim.model_copy(update={"status": ProofStatus.PARTIAL}))
    assert (await repos.evidence.get_claim(u1.id, t1.id)).status == ProofStatus.PARTIAL


async def test_text_is_encrypted_at_rest(repos, clock):
    await seed(repos, "+919800000001", clock)
    async with repos.db.session() as s:
        row = (await s.execute(text("select summary, payload from evidence_items"))).all()
    raw = " ".join(str(c) for r in row for c in r)
    assert "secret words" not in raw and "BK4821" not in raw and "Spice Hub" not in raw


async def test_retention_expires_items_and_erases_object_keys(repos, clock, tmp_path):
    store = LocalObjectStore(tmp_path / "obj")
    url = await store.put("evidence/u/t/1.png", b"png", content_type="image/png")
    u, t, _ = await seed(repos, "+919800000001", clock, key=url)
    assert await expire_evidence(repos, clock.now() + timedelta(days=89), store=store) == {
        "evidence_items": 0
    }
    assert len(await repos.evidence.list_for_task(u.id, t.id)) == 2
    clock.advance(days=91)
    out = await run_retention(repos, clock.now(), store=store)
    assert out["evidence_items"] == 2
    assert await repos.evidence.list_for_task(u.id, t.id) == []
    assert not (tmp_path / "obj" / "evidence" / "u" / "t" / "1.png").exists()


async def test_delete_everything_covers_the_evidence_tables(repos, clock, tmp_path):
    store = LocalObjectStore(tmp_path / "obj")
    url = await store.put("evidence/u/t/1.png", b"png", content_type="image/png")
    u1, t1, _ = await seed(repos, "+919800000001", clock, key=url)
    u2, t2, _ = await seed(repos, "+919800000002", clock, ref="XX0000")
    keys = await repos.purger.recording_urls(u1.id)  # collected BEFORE the purge, then erased
    assert url in keys
    counts = await repos.purger.purge_user(u1.id)
    assert counts["evidence_items"] == 2 and counts["done_claims"] == 1
    assert await repos.evidence.list_for_task(u1.id, t1.id) == []
    assert await repos.evidence.get_claim(u1.id, t1.id) is None
    assert len(await repos.evidence.list_for_task(u2.id, t2.id)) == 2  # other user untouched
    async with repos.db.session() as s:
        assert (await s.execute(text("select count(*) from evidence_items"))).scalar_one() == 2


async def test_memory_store_matches_the_sql_surface(clock):
    m = MemoryEvidenceStore()
    now = clock.now()
    i = EvidenceItem(
        user_id="u1",
        task_id="t1",
        kind=EvidenceKind.SCREENSHOT,
        level=EvidenceLevel.OBSERVED,
        object_key="file:///a",
        captured_at=now,
        expires_at=now + timedelta(days=90),
    )
    await m.add_items([i])
    assert await m.list_for_task("u2", "t1") == []
    assert await m.object_keys("u1") == ["file:///a"]
    assert await m.expire(now + timedelta(days=91)) == (1, ["file:///a"])
