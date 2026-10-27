# ruff: noqa: E501
"""Migration 0018, schema/RLS files, encryption at rest, retention, DataPurger, doctor, wording."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from friday.core.config import Settings
from friday.db import migrate
from friday.db.retention import expire_refunds
from friday.refunds import copy
from friday.refunds.models import RefundState
from friday.refunds.service import RefundService
from tests.refunds.conftest import EXAMPLE_NUMBER, at, known, open_case

ROOT = Path(__file__).resolve().parents[2]
TABLES = {"refund_cases", "refund_events", "refund_evidence", "refund_nudges"}


def test_migration_0018_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0018_refunds"
    assert "0017_trips" in doctor.known_revisions()
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    assert set(insp.get_table_names()) >= TABLES
    cols = set()
    for t in TABLES:
        cols |= {c["name"] for c in insp.get_columns(t)}
    assert {"user_id", "vendor_name", "amount_expected_paise", "proof_item_id", "key"} <= cols
    assert not {c for c in cols if c in ("blob", "file", "bytes", "token", "commission", "revenue", "referral")}
    migrate.downgrade(url)
    assert not TABLES & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_migration_matches_the_models(tmp_path):
    import friday.db.tables  # noqa: F401
    from friday.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    for t in TABLES:
        model_cols = {c.name for c in Base.metadata.tables[t].columns}
        assert {c["name"] for c in insp.get_columns(t)} == model_cols, t
        idx = {i["name"] for i in insp.get_indexes(t)}
        assert {i.name for i in Base.metadata.tables[t].indexes} <= idx, t
    eng.dispose()


def test_schema_and_rls_sql_files_carry_the_new_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in TABLES:
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0018_refunds'" in schema and "-> 0018_refunds" in schema
    assert "CREATE POLICY" not in rls.split("refund_cases")[1].split("\n")[0]


def test_switch_is_off_and_doctor_reports_it():
    from friday.ops import doctor

    s = Settings(_env_file=None)
    assert s.refunds_enabled is False and s.refund_chase_calls is False
    msgs = [c.message for c in doctor.check_switches(s).checks]
    assert "FRIDAY_REFUNDS_ENABLED=off" in msgs
    on = doctor.check_switches(s.model_copy(update={"refunds_enabled": True, "refund_chase_calls": True}))
    warn = [c.message for c in on.checks if c.status == doctor.WARN and "REFUND" in c.message]
    assert any("PENDING" in m for m in warn) and any("CHASE_CALLS" in m for m in warn)


# ------------------------------------------------------------------ wording
def test_all_wording_is_pending_and_has_no_spoken_line_outside_the_registry():
    assert copy.PENDING_FOUNDER_APPROVAL and copy.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert copy.CALL_LINE_STATUS == "PENDING_FOUNDER_APPROVAL"
    assert all(set(v) == {"hinglish", "en"} and all(v.values()) for v in copy.TEXTS.values())
    assert set(copy.VENDOR_CALL_QUESTIONS) == {"hinglish", "en"}
    assert len(copy.copy_ids()) == len(set(copy.copy_ids()))
    emoji = [k for k, v in copy.TEXTS.items() for s in v.values() if any(ord(c) > 0x2000 and c != "₹" for c in s)]
    assert emoji == [], emoji
    for k, v in copy.TEXTS.items():  # no line states a law, a refund window, or that Friday moves money
        for s in v.values():
            low = s.lower()
            assert "right to" not in low and "by law" not in low and "within 7" not in low, k
            assert "i will pay" not in low and "main pay" not in low, k


def test_every_copy_key_the_code_uses_exists():
    used: set[str] = set()
    for f in ("service.py", "commands.py"):
        tree = ast.parse((ROOT / "friday" / "refunds" / f).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value
                if v in copy.TEXTS:
                    used.add(v)
    # keys built as f"state.{...}" / "level.{...}" / "source.{...}" / "what.{...}" exist for every value
    for s in RefundState:
        assert f"state.{s.value}" in copy.TEXTS
    from friday.evidence.models import EvidenceLevel
    from friday.refunds.models import Origin
    from friday.refunds.ports import SOURCES

    for lv in EvidenceLevel:
        assert f"level.{lv.value}" in copy.TEXTS
    for o in Origin:
        assert f"what.{o.value}" in copy.TEXTS
    for src in SOURCES:
        assert f"source.{src}" in copy.TEXTS
    # and every key the code mentions as a literal that looks like a copy id is real
    for f in ("service.py", "commands.py"):
        tree = ast.parse((ROOT / "friday" / "refunds" / f).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "t" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant):
                    assert a.value in copy.TEXTS, a.value
    assert used


def test_copy_ids_are_listed_in_the_pilot_doc():
    doc = (ROOT / "docs" / "CHATBOT_PILOT.md").read_text()
    assert "friday/refunds/copy.py" in doc
    refunds = (ROOT / "docs" / "REFUNDS.md").read_text()
    for key in copy.copy_ids():
        assert f"`{key}`" in doc or f"`{key}`" in refunds, key


def test_formatting_helpers():
    assert copy.money(450000) == "Rs 4,500" and copy.money(120050) == "Rs 1,200.50" and copy.money(None) == ""
    assert copy.fmt_date(date(2026, 11, 20)) == "20 Nov"
    assert copy.age_text(0) == "aaj" and copy.age_text(3) == "3 din" and copy.age_text(3, "en") == "3 days"
    assert copy.t("muted", "xx") == copy.t("muted")  # an unknown language falls back


# ------------------------------------------------------------------ storage
async def test_personal_values_are_encrypted_at_rest(rsettings, repos, clock, alice, sender, taskport):
    from friday.refunds.resolver import StaticNumberSource

    src = StaticNumberSource()
    src.add(alice.id, "Secretvendor", known("+919800000888"))
    svc = RefundService(rsettings, repos.refunds, clock, sender=sender, tasks=taskport, sources=[src])
    await svc.open_by_user(alice.id, "Secretvendor", amount_paise=450000, paid_with_bank="Fictional Bank")
    (case,) = await repos.refunds.list_cases(alice.id)
    await svc.set_number(alice.id, case.id, "+919800000999")
    await svc.attach_text(alice.id, case.id, "Refund of Rs 4,500 for booking ZZSECRET initiated", amount_paise=450000)
    await svc.attach_receipt(alice.id, case.id, b"receipt-bytes", amount_paise=450000)
    clock.set(at(11, 10, 1))
    await svc.run_user(alice.id)
    chunks: list[str] = []
    async with repos.db.session() as s:
        for t in TABLES:
            for row in (await s.execute(text(f"select * from {t}"))).all():  # noqa: S608
                chunks += [str(c) for c in row]
    raw = " ".join(chunks)
    for secret in ("Secretvendor", "Fictional Bank", "919800000999", "ZZSECRET", "initiated", "pooch rahi"):
        assert secret not in raw, secret
    again = await repos.refunds.get_case(alice.id, case.id)  # but it decrypts for the owner
    assert (again.vendor_name, again.paid_with_bank, again.user_number) == ("Secretvendor", "Fictional Bank", "+919800000999")
    ev = await repos.refunds.list_evidence(alice.id, case.id)
    assert any("ZZSECRET" in e.summary for e in ev)
    assert all(e.sha256 is None or len(e.sha256) == 64 for e in ev)


async def test_sql_and_memory_agree(rsettings, repos, clock, alice):
    from friday.refunds.store import MemoryRefundStore

    results = []
    for st in (MemoryRefundStore(), repos.refunds):
        svc = RefundService(rsettings, st, clock)
        await svc.open_by_user(alice.id, f"Exampleair{len(results)}", amount_paise=450000)
        c = (await st.list_cases(alice.id))[-1]
        await svc.mark_requested(alice.id, c.id)
        await svc.mark_promised(alice.id, c.id, date(2026, 11, 20), 450000)
        await svc.mark_received(alice.id, c.id, 450000)
        c = await st.get_case(alice.id, c.id)
        ev = await st.list_evidence(alice.id, c.id)
        events = await st.list_events(alice.id, c.id)
        results.append((c.state, c.closed_reason, c.closed_basis, c.amount_received_paise, c.state_epoch, sorted((e.kind.value, e.level.value, e.amount_paise) for e in ev), [e.to_state for e in events]))
    assert results[0] == results[1]


async def test_delete_everything_covers_the_refund_tables(rsettings, repos, clock, alice, bob, sender):
    svc = RefundService(rsettings, repos.refunds, clock, sender=sender)
    for u in (alice, bob):
        c = await open_case(svc, u.id)
        await svc.attach_text(u.id, c.id, "Rs 4,500 refund initiated", amount_paise=450000)
        await svc.mark_requested(u.id, c.id)
    clock.set(at(14, 10, 1))  # the first check-in after "requested" is 3 days on
    await svc.run_user(alice.id)
    await svc.run_user(bob.id)
    counts = await repos.purger.purge_user(alice.id)
    assert counts["refund_cases"] == 1 and counts["refund_events"] >= 2
    assert counts["refund_evidence"] == 1 and counts["refund_nudges"] >= 1
    assert await repos.refunds.list_cases(alice.id) == []
    assert len(await repos.refunds.list_cases(bob.id)) == 1  # the other user is untouched
    assert len(await repos.refunds.list_evidence(bob.id, (await repos.refunds.list_cases(bob.id))[0].id)) == 1
    assert await repos.refunds.users_with_open_cases() == [bob.id]


async def test_memory_store_purge(rsettings, clock, alice, bob):
    from friday.refunds.store import MemoryRefundStore

    st = MemoryRefundStore()
    svc = RefundService(rsettings, st, clock)
    await open_case(svc, alice.id)
    await open_case(svc, bob.id)
    assert await st.purge_user(alice.id) == 1
    assert await st.list_cases(alice.id) == [] and len(await st.list_cases(bob.id)) == 1


async def test_retention_deletes_old_closed_cases_only(rsettings, repos, clock, alice):
    svc = RefundService(rsettings, repos.refunds, clock)
    done = await open_case(svc, alice.id, "Exampleair")
    await svc.mark_received(alice.id, done.id, 450000)  # closed today
    open_ = await open_case(svc, alice.id, "Examplemart")  # still open
    assert (await expire_refunds(repos, at(15, 10)))["refund_cases"] == 0
    assert len(await repos.refunds.list_cases(alice.id)) == 2
    far = at(10, 10).replace(year=2027, month=6)  # more than 180 days after the close
    assert (await expire_refunds(repos, far))["refund_cases"] == 1
    left = await repos.refunds.list_cases(alice.id)
    assert [c.id for c in left] == [open_.id]  # an open case is never deleted by retention
    assert await repos.refunds.list_events(alice.id, done.id) == []
    assert await repos.refunds.list_evidence(alice.id, done.id) == []


async def test_memory_store_retention(rsettings, clock, alice):
    from friday.refunds.store import MemoryRefundStore

    st = MemoryRefundStore()
    svc = RefundService(rsettings, st, clock)
    c = await open_case(svc, alice.id)
    await svc.close(alice.id, c.id)
    assert await st.expire(at(20), 180) == 0
    assert await st.expire(at(10).replace(year=2027, month=6), 180) == 1


async def test_nudge_log_dedupes_by_key(repos, alice, rsettings, clock):
    from friday.refunds.models import RefundNudge

    svc = RefundService(rsettings, repos.refunds, clock)
    c = await open_case(svc, alice.id)
    n = RefundNudge(user_id=alice.id, case_id=c.id, key="refund:x:0:0", stage="checkin", sent_at=clock.now())
    assert await repos.refunds.add_nudge(n) is True
    assert await repos.refunds.add_nudge(n.model_copy(update={"id": "other"})) is False
    assert EXAMPLE_NUMBER
