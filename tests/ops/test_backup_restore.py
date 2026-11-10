# ruff: noqa: E501
"""T19: backups cover the Robin, device and concierge tables, and a restore (checked on SQLite) brings every row back unchanged. Fakes only."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from friday.core.clock import utcnow
from friday.db.session import Database
from friday.ops import backupcheck

ROOT = Path(__file__).resolve().parents[2]


def test_expected_tables_include_all_three_packages():
    names = set(backupcheck.expected_robin_tables())
    assert {"robin_families", "robin_members", "robin_consents", "robin_records"} <= names  # family core
    assert {"robin_device_states", "robin_device_codes"} <= names  # device package
    assert {"robin_concierge_requests", "robin_concierge_audit", "robin_concierge_docs"} <= names  # concierge desk


def test_backup_script_dumps_the_whole_database_with_no_table_filter():
    text = (ROOT / "deploy" / "backup.sh").read_text()
    (cmd,) = [ln for ln in text.splitlines() if "pg_dump" in ln and "exec" in ln]
    assert "--format=custom" in cmd
    assert not re.search(r"(\s-t\s|--table|--exclude|--schema|-n\s)", cmd), "a table filter would silently drop Robin tables from the backup"
    assert "pg_restore --list" in text  # the dump is verified readable before upload


def test_restore_drill_doc_lists_the_robin_tables_check():
    doc = (ROOT / "deploy" / "restore.md").read_text()
    for t in backupcheck.expected_robin_tables():
        assert t in doc, f"deploy/restore.md section C must name {t}"


async def test_sqlite_restore_brings_back_every_robin_table(tmp_path):
    path = tmp_path / "live.db"
    db = Database(f"sqlite+aiosqlite:///{path}")
    await db.create_all()
    try:
        from friday.concierge.audit import AuditLog
        from friday.concierge.dbmodel import DbConciergeStore
        from friday.core.clock import FakeClock
        from friday.db.tables import UserRow
        from friday.robin.dbmodel import RobinFamilyRow, RobinMemberRow, RobinRecordRow
        from friday.robindevice.dbmodel import RobinDeviceCodeRow, RobinDeviceStateRow

        now = utcnow()
        async with db.session() as s:
            s.add(UserRow(id="u1", phone="+910000000001", phone_hmac="p" * 64))  # invented
            await s.flush()
            s.add(RobinFamilyRow(id="fam1", user_id="u1", status="active", data={"parent_label": "Papa"}))
            s.add(RobinMemberRow(id="mem1", user_id="u1", family_id="fam1", role="parent", phone_hash="h" * 64, data={"language": "hi"}))
            s.add(RobinRecordRow(id="rec1", user_id="u1", family_id="fam1", kind="incident", key="k1", status="open", at=now, data={"tier": "high"}))
            s.add(RobinDeviceStateRow(id="dev1", parent_id="mem1", token_hash="t" * 64, version=1, data={"x": 1}))
            s.add(RobinDeviceCodeRow(id="code1", code_hash="c" * 64, parent_id="mem1", expires_ms=1))
            await s.commit()
        store = DbConciergeStore(db)
        audit = AuditLog(store, FakeClock(now))
        await audit.record("c1", "queue_view", "", rows=0)
        await store.doc_save("handoff", "inc1", {"card": {"incident_id": "inc1"}}, parent_id="mem1", status="paged")
    finally:
        await db.dispose()

    rep = backupcheck.restore_check(path, tmp_path)
    assert rep.ok, rep.lines()
    for t in ("robin_families", "robin_members", "robin_records", "robin_device_states", "robin_device_codes", "robin_concierge_audit", "robin_concierge_docs"):
        assert rep.counts[t] >= 1, (t, rep.counts)
    out = "\n".join(rep.lines())
    assert "Papa" not in out and "RESTORE CHECK OK" in out


async def test_restore_check_detects_a_missing_table_and_a_change(tmp_path):
    path = tmp_path / "live.db"
    db = Database(f"sqlite+aiosqlite:///{path}")
    await db.create_all()
    await db.dispose()
    con = sqlite3.connect(path)
    con.execute("DROP TABLE robin_concierge_docs")
    con.commit()
    con.close()
    rep = backupcheck.restore_check(path, tmp_path)
    assert not rep.ok and rep.missing_in_source == ["robin_concierge_docs"]
    assert backupcheck.main([str(path)]) == 1
    assert backupcheck.main([]) == 2
