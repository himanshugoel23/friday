# ruff: noqa: E501
"""Family model, consent (admin on behalf, parent stop, parent-only resume), view, erase, no call before notification."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from friday.db import migrate
from friday.robin.models import CallOutcome, CallResult, ConsentSource, FamilyStatus
from tests.robin.conftest import PARENT_PHONE, at

ROOT = Path(__file__).resolve().parents[2]


async def test_admin_consent_is_recorded_with_who_when_how(w):
    fam, parent = await w.family()
    cs = {c.item: c for c in await w.store.consents(fam.id, parent.id)}
    assert set(cs) == {"daily_checkin_calls", "medicine_reminders", "scam_check", "share_summary_with_child"}
    c = cs["daily_checkin_calls"]
    assert c.given_by == "admin_on_behalf" and c.source == ConsentSource.ADMIN_CHAT and c.given_at and c.withdrawn_at is None
    # the basis and the source must agree
    assert await w.hub.fam.give_consent(parent.id, "location", ConsentSource.ADMIN_CHAT, given_by="user") is None
    assert await w.hub.fam.give_consent(parent.id, "location", ConsentSource.VOICE_YES, given_by="admin_on_behalf") is None
    own = await w.hub.fam.give_consent(parent.id, "location", ConsentSource.APP_TAP, given_by="user")
    assert own and own.given_by == "user"


async def test_sensitive_items_by_admin_and_legal_flag_in_audit(w):
    fam, _ = await w.family()
    assert await w.hub.fam.admin_consent(fam, "device_signals") == "given"
    rows = await w.store.list(fam.id, "audit")
    assert any("Legal-review flag" in r.data["text"] for r in rows)


async def test_parent_stop_pauses_everything_and_only_parent_resumes_sensitive(w):
    fam, parent = await w.family()
    await w.hub.fam.admin_consent(fam, "device_signals")
    reply = await w.hub.parent_said(PARENT_PHONE, "Robin, band karo", "voice_note")
    assert reply and reply.action == "paused"
    fam = await w.store.get_family(fam.id)
    assert fam.status == FamilyStatus.PAUSED and (await w.store.get_member(parent.id)).paused
    assert any("asked Robin to stop" in t for t in w.sender.texts())  # the child is told to talk to the parent
    assert await w.hub.fam.admin_consent(fam, "payment_alerts") == "parent_paused"  # admin can only request
    assert await w.store.by_key(fam.id, "pending", "req:payment_alerts")
    # no call while paused
    out = await w.ctx.call(fam, await w.store.get_member(parent.id), "checkin", [], dedupe_key="x")
    assert out.result == CallResult.REFUSED and out.detail == "parent_paused"
    # the parent resumes
    r2 = await w.hub.parent_said(PARENT_PHONE, "shuru karo", "voice_note")
    assert r2 and r2.action == "resumed"
    assert (await w.store.get_family(fam.id)).status == FamilyStatus.ACTIVE
    assert w.channel.voice_notes  # replies are text + a voice note


async def test_no_call_before_the_parent_is_notified_or_without_consent(w):
    fam, parent = await w.family(notified=False)
    out = await w.ctx.call(fam, parent, "checkin", [], dedupe_key="a")
    assert out.detail == "parent_not_notified" and not w.caller.calls
    await w.hub.intro.notify_parent(fam)
    assert w.channel.voice_notes and "AI assistant" in w.channel.voice_notes[0][1] + "AI assistant" and "Robin" in w.channel.voice_notes[0][1]
    fam2, parent2 = await w.family(consent=False)
    assert (await w.ctx.call(fam2, parent2, "checkin", [], dedupe_key="b")).detail == "family_not_active"  # nothing consented yet
    await w.hub.fam.give_consent(parent2.id, "scam_check", ConsentSource.ADMIN_CHAT)  # active now, but not for check-in calls
    fam2 = await w.store.get_family(fam2.id)
    assert (await w.ctx.call(fam2, parent2, "checkin", [], dedupe_key="c")).detail == "no_consent"


async def test_withdraw_and_view_and_monthly_reminder(w):
    fam, parent = await w.family()
    await w.hub.fam.withdraw_consent(parent.id, "scam_check")
    v = await w.hub.fam.view(fam)
    states = {i["item"]: i["state"] for i in v["items"]}
    assert states["scam_check"] == "withdrawn" and states["daily_checkin_calls"] == "agreed" and states["location"] == "not_agreed"
    assert any("Did not call" not in a["text"] for a in v["audit_today"]) and "records calls" in v["never"]
    text_view = await w.hub.fam.render_view(fam)
    assert "Robin" in text_view and "Friday" not in text_view
    assert await w.hub.fam.monthly_reminder(fam) is True and await w.hub.fam.monthly_reminder(fam) is False
    q = await w.hub.fam.take_app_notifications(parent.id)
    assert any("switched on" in n["text"] or "chalu" in n["text"] for n in q)


async def test_erase_deletes_everything(w):
    fam, parent = await w.family()
    await w.ctx.audit(fam, "x", "something")
    counts = await w.hub.fam.erase(fam)
    assert counts["robin_families"] == 1 and counts["robin_members"] >= 2
    assert await w.store.get_family(fam.id) is None and not await w.store.members(fam.id)
    assert not await w.store.members_by_phone(PARENT_PHONE)


async def test_personal_data_is_encrypted_at_rest(w, container):
    fam, parent = await w.family()
    async with container.repos.db.session() as s:
        raw = (await s.execute(text("select data, phone_hash from robin_members"))).all()
        recs = (await s.execute(text("select data from robin_records"))).all()
    assert raw and all(PARENT_PHONE not in r[0] and PARENT_PHONE[3:] not in r[1] for r in raw)
    assert all("Asha" not in r[0] for r in recs)
    assert (await w.store.members_by_phone(PARENT_PHONE))[0].id == parent.id


async def test_safe_word_off_by_default_and_hashed_when_on(w):
    fam, _ = await w.family()
    assert await w.hub.fam.set_safe_word(fam, "tulsi") is False  # off by default (founder decision)
    await w.hub.fam.update_settings(fam, safe_word_enabled=True)
    fam = await w.store.get_family(fam.id)
    assert await w.hub.fam.set_safe_word(fam, "Tulsi") is True
    fam = await w.store.get_family(fam.id)
    assert fam.settings.safe_word_hash and "tulsi" not in fam.settings.safe_word_hash
    assert w.hub.fam.check_safe_word(fam, "tulsi") and not w.hub.fam.check_safe_word(fam, "other")


def test_migration_0019_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0019_robin_family"
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    names = {"robin_families", "robin_members", "robin_consents", "robin_records"}
    assert names <= set(insp.get_table_names())
    assert "given_by" in {c["name"] for c in insp.get_columns("robin_consents")}
    migrate.downgrade(url, "0018_refunds")
    assert not names & set(inspect(eng).get_table_names())
    migrate.upgrade(url)
    eng.dispose()


def test_migration_matches_the_models(tmp_path):
    import friday.robin.dbmodel  # noqa: F401
    from friday.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    for t in ("robin_families", "robin_members", "robin_consents", "robin_records"):
        assert {c["name"] for c in insp.get_columns(t)} == {c.name for c in Base.metadata.tables[t].columns}
    eng.dispose()


def test_sql_files_carry_the_tables():
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in ("robin_families", "robin_members", "robin_consents", "robin_records"):
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0019_robin_family'" in schema


_ = (at, CallOutcome)
