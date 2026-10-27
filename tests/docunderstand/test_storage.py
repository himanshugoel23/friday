# ruff: noqa: E501
"""Migration 0014, SQL repository, encryption at rest, retention and "delete everything"."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from friday.core.models import User
from friday.db import migrate
from friday.db.objectstore import LocalObjectStore
from friday.db.repositories import make_repositories
from friday.db.retention import expire_documents, run_retention
from friday.docunderstand.models import DocField, DocStatus, DocType, Document
from friday.docunderstand.store import MemoryDocStore

ROOT = Path(__file__).resolve().parents[2]


def test_migration_0014_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0018_refunds"
    assert "0013_evidence" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert {"documents", "document_fields"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("documents")} | {
        c["name"] for c in insp.get_columns("document_fields")
    }
    assert {
        "user_id",
        "doc_type",
        "status",
        "expires_at",
        "pointer_kind",
        "pointer_ref",
        "value",
    } <= cols
    assert not {
        c
        for c in cols
        if "bytes" in c.replace("size_bytes", "") or c in ("data", "content", "blob", "text")
    }
    migrate.downgrade(url)
    assert not {"documents", "document_fields"} & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in ("documents", "document_fields"):
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0014_documents'" in schema


@pytest.fixture
def repos(db, clock):
    return make_repositories(db, clock, "test-secret")


def make_doc(user_id: str, clock, *, days: int = 7, status=DocStatus.PENDING) -> Document:
    return Document(
        user_id=user_id,
        doc_type=DocType.PASSPORT,
        status=status,
        mime="image/jpeg",
        size_bytes=1234,
        sha256="a" * 64,
        fields={
            "given_name": DocField(value="ASHA", confidence=0.9),
            "number_masked": DocField(value="******567", confidence=0.9, masked=True),
            "dob": DocField(value="1990-04-12", confidence=0.6, needs_confirm=True),
        },
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(days=days),
    )


async def seed(repos, phone: str, clock, **kw):  # noqa: ANN003, ANN201
    user = await repos.users.add(User(phone=phone))
    doc = make_doc(user.id, clock, **kw)
    await repos.documents.save(doc)
    return user, doc


async def test_round_trip_and_two_user_isolation(repos, clock):
    u1, d1 = await seed(repos, "+919800000001", clock)
    u2, _ = await seed(repos, "+919800000002", clock)
    got = await repos.documents.get(u1.id, d1.id)
    assert got.values() == d1.values() and got.fields["number_masked"].masked
    assert got.fields["dob"].needs_confirm and got.status == DocStatus.PENDING
    assert await repos.documents.get(u2.id, d1.id) is None
    assert (await repos.documents.latest_open(u1.id)).id == d1.id
    # saving replaces the fields (a fix) and keeps one row
    got.fields["given_name"] = DocField(value="MEERA", confidence=1.0, source="user")
    got.status = DocStatus.CONFIRMED
    await repos.documents.save(got)
    again = await repos.documents.get(u1.id, d1.id)
    assert (
        again.fields["given_name"].value == "MEERA" and again.fields["given_name"].source == "user"
    )
    assert [d.id for d in await repos.documents.list_confirmed(u1.id)] == [d1.id]
    assert await repos.documents.list_confirmed(u1.id, DocType.BILL) == []
    assert await repos.documents.latest_open(u1.id) is None
    async with repos.db.session() as s:
        assert (await s.execute(text("select count(*) from document_fields"))).scalar_one() == 6
    with pytest.raises(PermissionError):
        await repos.documents.save(again.model_copy(update={"user_id": u2.id}))


async def test_values_and_pointer_are_encrypted_at_rest(repos, clock):
    u, d = await seed(repos, "+919800000001", clock)
    d.pointer_kind, d.pointer_ref = "gdrive", "drive-file-id-777"
    await repos.documents.save(d)
    async with repos.db.session() as s:
        rows = (await s.execute(text("select value from document_fields"))).all()
        ptr = (await s.execute(text("select pointer_ref from documents"))).all()
    raw = " ".join(str(c) for r in rows + ptr for c in r)
    assert "ASHA" not in raw and "******567" not in raw and "drive-file-id-777" not in raw
    assert (await repos.documents.get(u.id, d.id)).pointer_ref == "drive-file-id-777"


async def test_delete_only_your_own(repos, clock):
    u1, d1 = await seed(repos, "+919800000001", clock)
    u2, _ = await seed(repos, "+919800000002", clock)
    assert not await repos.documents.delete(u2.id, d1.id)
    assert await repos.documents.delete(u1.id, d1.id)
    async with repos.db.session() as s:
        assert (
            await s.execute(
                text("select count(*) from document_fields where user_id=:u"), {"u": u1.id}
            )
        ).scalar_one() == 0


async def test_retention_expires_unconfirmed_after_7_days_and_confirmed_later(
    repos, clock, tmp_path
):
    u1, pending = await seed(repos, "+919800000001", clock, days=7)
    _, kept = await seed(repos, "+919800000002", clock, days=180, status=DocStatus.CONFIRMED)
    assert await expire_documents(repos, clock.now() + timedelta(days=6)) == {"documents": 0}
    clock.advance(days=8)
    out = await run_retention(repos, clock.now(), store=LocalObjectStore(tmp_path / "obj"))
    assert out["documents"] == 1
    assert await repos.documents.get(u1.id, pending.id) is None
    assert await repos.documents.get(kept.user_id, kept.id) is not None
    clock.advance(days=200)
    assert (await expire_documents(repos, clock.now())) == {"documents": 1}
    async with repos.db.session() as s:
        assert (await s.execute(text("select count(*) from document_fields"))).scalar_one() == 0


async def test_delete_everything_covers_the_document_tables(repos, clock):
    u1, d1 = await seed(repos, "+919800000001", clock)
    u2, d2 = await seed(repos, "+919800000002", clock)
    counts = await repos.purger.purge_user(u1.id)
    assert counts["documents"] == 1 and counts["document_fields"] == 3
    assert await repos.documents.get(u1.id, d1.id) is None
    assert await repos.documents.get(u2.id, d2.id) is not None  # the other user is untouched


async def test_memory_store_matches_the_sql_surface(clock):
    m = MemoryDocStore()
    d = make_doc("u1", clock)
    await m.save(d)
    assert await m.get("u2", d.id) is None
    assert (await m.latest_open("u1")).id == d.id
    assert await m.expire(clock.now() + timedelta(days=8)) == 1
    assert await m.delete("u1", d.id) is False
