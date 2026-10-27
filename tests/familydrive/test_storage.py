"""Migration 0016, encryption at rest, retention, DataPurger, /google/disconnect, doctor."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import create_engine, inspect, text

from friday.core.config import Settings
from friday.db import migrate
from friday.db.objectstore import LocalObjectStore
from friday.db.retention import expire_family_drive, run_retention
from tests.familydrive.conftest import PDF

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"drive_links", "drive_folders", "drive_shares"}


def test_migration_0016_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0016_family_drive"
    assert "0014_documents" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert set(insp.get_table_names()) >= TABLES
    cols = set()
    for t in TABLES:
        cols |= {c["name"] for c in insp.get_columns(t)}
    assert {"user_id", "root_folder_id", "folder_id", "path_key", "email", "permission_id"} <= cols
    assert not {c for c in cols if c in ("data", "content", "blob", "token", "refresh_token")}
    migrate.downgrade(url)
    assert not TABLES & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in TABLES:
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0016_family_drive'" in schema


def test_the_switch_is_off_by_default_and_doctor_reports_it():
    from friday.ops import doctor

    s = Settings(_env_file=None)
    assert s.family_drive_enabled is False and s.family_drive_sharing_enabled is False
    sec = doctor.check_switches(s)
    msgs = [c.message for c in sec.checks]
    assert "FRIDAY_FAMILY_DRIVE_ENABLED=off" in msgs
    on = doctor.check_switches(s.model_copy(update={"family_drive_enabled": True}))
    warn = [c for c in on.checks if c.status == doctor.WARN and "FAMILY_DRIVE" in c.message]
    assert warn and "PENDING" in warn[0].message and "UNVERIFIED" in warn[0].message


async def test_ids_and_emails_are_encrypted_at_rest(svc, repos, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    await svc.file_document(alice.id, doc.id, PDF, trip="Goa")
    req = await svc.request_share(alice.id, "mom.example@gmail.com")
    await svc.approve_share(alice.id, req.id)
    chunks: list[str] = []
    async with repos.db.session() as s:
        for t in ("drive_links", "drive_folders", "drive_shares", "documents"):
            for row in (await s.execute(text(f"select * from {t}"))).all():  # noqa: S608
                chunks += [str(c) for c in row]
    raw = " ".join(chunks)
    assert "mom.example" not in raw and "fk0000" not in raw and "ff0000" not in raw
    assert "perm0" not in raw
    link = await repos.family_drive.get_link(alice.id)
    assert link.root_folder_id.startswith("fk")  # but it decrypts for the owner


async def test_repository_isolation(svc, repos, alice, bob):
    await svc.link(alice.id)
    await svc.link(bob.id)
    r = await svc.request_share(alice.id, "x@example.com")
    assert await repos.family_drive.get_share(bob.id, r.id) is None
    assert await repos.family_drive.update_share(bob.id, r.id, status="shared") is None
    assert (await repos.family_drive.get_link(bob.id)).root_folder_id != (
        await repos.family_drive.get_link(alice.id)
    ).root_folder_id
    assert await repos.family_drive.get_folder(
        bob.id, "root"
    ) != await repos.family_drive.get_folder(alice.id, "root")


async def test_delete_everything_covers_the_drive_tables(svc, repos, alice, bob, mk):
    for u in (alice, bob):
        await svc.link(u.id)
    doc = await mk(alice.id)
    await svc.file_document(alice.id, doc.id, PDF)
    await svc.request_share(alice.id, "x@example.com")
    bdoc = await mk(bob.id)
    await svc.file_document(bob.id, bdoc.id, PDF)
    counts = await repos.purger.purge_user(alice.id)
    assert counts["drive_links"] == 1 and counts["drive_shares"] == 1
    assert counts["drive_folders"] >= 3 and counts["documents"] == 1
    assert (await svc.status(alice.id)).state == "not_linked"
    assert await repos.family_drive.list_shares(alice.id) == []
    assert (await svc.status(bob.id)).state == "active"  # the other user is untouched
    assert (await repos.documents.get(bob.id, bdoc.id)).pointer_kind == "gdrive"


async def test_retention_expires_share_requests_and_drops_stale_links(
    svc, repos, clock, alice, bob, tmp_path
):
    await svc.link(alice.id)
    await svc.link(bob.id)
    pending = await svc.request_share(alice.id, "p@example.com")
    decl = await svc.request_share(alice.id, "d@example.com")
    await svc.decline_share(alice.id, decl.id)
    assert (await expire_family_drive(repos, clock.now() + timedelta(days=1)))[
        "drive_shares_expired"
    ] == 0
    clock.advance(days=8)  # past the 7-day approval window
    out = await run_retention(repos, clock.now(), store=LocalObjectStore(tmp_path / "obj"))
    assert out["drive_shares_expired"] == 1
    assert (await repos.family_drive.get_share(alice.id, pending.id)).status == "expired"
    clock.advance(days=31)
    out = await run_retention(repos, clock.now(), store=LocalObjectStore(tmp_path / "obj"))
    assert out["drive_shares_deleted"] == 2
    assert await repos.family_drive.list_shares(alice.id) == []
    # a link stuck in needs_reconnect for 180 days is dropped (bob's stays: it is active)
    await repos.family_drive.set_link_status(alice.id, "needs_reconnect")
    clock.advance(days=181)
    out = await run_retention(repos, clock.now(), store=LocalObjectStore(tmp_path / "obj"))
    assert out["drive_links_dropped"] == 1
    assert (await svc.status(alice.id)).state == "not_linked"
    assert (await svc.status(bob.id)).state == "active"


async def test_google_disconnect_also_clears_drive_pointers(container, repos, hub, clock):
    """/google/disconnect revokes the one Google token, so our Drive data goes with it."""
    from friday.api.admin import admin_token
    from friday.api.app import create_app
    from friday.core.models import User
    from friday.familydrive.service import FamilyDrive
    from tests.familydrive.conftest import make_doc

    u = await container.repos.users.add(User(phone="+919800000999"))
    svc = FamilyDrive(
        container.settings.model_copy(update={"family_drive_enabled": True}),
        container.repos,
        hub.factory,
        clock=container.clock,
    )
    await svc.link(u.id)
    doc = make_doc(u.id, container.clock)
    await container.repos.documents.save(doc)
    await svc.file_document(u.id, doc.id, PDF)
    app = create_app(container, background=False, fast_pin_hash=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://friday.example"
    ) as c:
        c.headers["authorization"] = f"Bearer {admin_token(container.settings)}"
        r = await c.post("/google/disconnect", json={"user_id": u.id})
        assert r.status_code == 200
    assert (await svc.status(u.id)).state == "not_linked"
    assert await container.repos.documents.get(u.id, doc.id) is None
    assert hub.for_user(u.id).files()  # the file in the user's Drive is still there
