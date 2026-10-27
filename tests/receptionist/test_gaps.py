# ruff: noqa: E501
"""Receptionist gaps closed 2026-10-27: call_fields, doctor check, shared spam table, test ring,
receptionist-only number. Fakes only; no call, no message."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from friday.core.config import Settings
from friday.core.events import InboundCallReceived
from friday.receptionist import copy, lines, sim
from friday.receptionist import probe as P
from friday.receptionist.identify import RedirectResolver, Resolution, Route, UserRef
from friday.receptionist.models import CallOutcomeKind, ReceptionistConfig
from friday.receptionist.store import spam_key
from tests.frontdoor.conftest import FRIDAY_NUMBER, OWN, start_friday

ROOT = Path(__file__).resolve().parents[2]
USER, USER_PHONE, POOL = sim.USER_ID, sim.USER_PHONE, "+918000000055"
CALLER = "+919100000015"


@pytest.fixture(autouse=True)
def _reset_hook():
    P.configure((), None)
    yield
    P.configure((), None)


def caller(cid: str):
    return next(x for x in sim.callers() if x.id == cid)


# ------------------------------------------------------------------ (1) call_fields
def test_observe_fields_is_inert_until_configured():
    assert P.observe_fields({"Diversion": USER_PHONE, "X-Foo": "1"}) == {}


def test_observe_fields_captures_diversion_history_and_x_headers_but_not_from_to():
    P.configure(["Diversion"], None)
    got = P.observe_fields({
        "From": CALLER, "To": FRIDAY_NUMBER, "CallUUID": "abc",
        "Diversion": f"<sip:{USER_PHONE}@h>;reason=no-answer", "History-Info": "<sip:x@h>",
        "X-Orig-Called": USER_PHONE, "x_other": "v", "Direction": "inbound",
    })
    assert set(got) == {"Diversion", "History-Info", "X-Orig-Called", "x_other"}
    assert len(P.observe_fields({"X-Big": "9" * 900})["X-Big"]) == 300


def test_inbound_event_carries_call_fields_default_empty():
    assert InboundCallReceived(from_phone=CALLER).call_fields == {}
    assert InboundCallReceived(from_phone=CALLER, call_fields={"X-A": "1"}).call_fields == {"X-A": "1"}


def test_vobiz_adapter_helper_returns_the_fields():
    from friday.voice.telephony.sarvam import _observe_fields

    P.configure(["Diversion"], None)
    assert _observe_fields({"From": CALLER, "To": FRIDAY_NUMBER, "X-Diverted-By": USER_PHONE}) == {
        "X-Diverted-By": USER_PHONE
    }


class _Dir:
    async def user_for_phone(self, phone):
        return UserRef(USER, True) if phone == USER_PHONE else None


async def test_resolver_finds_the_user_in_an_x_header():
    r = RedirectResolver(_Dir(), fields=["Diversion"], friday_numbers=lambda: [FRIDAY_NUMBER])
    res = await r.resolve(None, CALLER, {"X-Orig-Called": USER_PHONE, "Other": "hello"})
    assert res.route == Route.MATCHED and res.user_id == USER


async def test_resolver_skips_friday_caller_and_dialled_numbers_then_falls_through():
    r = RedirectResolver(_Dir(), fields=["Diversion"], friday_numbers=lambda: [FRIDAY_NUMBER])
    fields = {
        "Diversion": f"<sip:{FRIDAY_NUMBER}@h>", "History-Info": f"<sip:{CALLER}@h>",
        "X-A": f"<sip:{USER_PHONE}@h>;reason=user-busy",
    }
    res = await r.resolve(None, CALLER, fields, FRIDAY_NUMBER)
    assert res.route == Route.MATCHED and res.reason == "user-busy"
    none = await r.resolve(None, CALLER, {"Diversion": FRIDAY_NUMBER, "X-To": CALLER}, FRIDAY_NUMBER)
    assert none.route == Route.NOT_FORWARDED


async def test_raw_value_still_wins_over_call_fields():
    r = RedirectResolver(_Dir(), fields=[], friday_numbers=lambda: [])
    res = await r.resolve(f"<sip:{USER_PHONE}@h>", CALLER, {"X-A": "+919800000777"})
    assert res.route == Route.MATCHED


# ------------------------------------------------------------------ (2) doctor, chain, sql files
def test_doctor_chain_and_sql_files_contain_the_receptionist_tables():
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0017_trips"
    assert doctor.EXPECTED_HEAD_CHAIN in doctor.known_revisions()
    assert "0011_receptionist" in doctor.known_revisions()
    schema = (ROOT / "deploy" / "supabase" / "schema.sql").read_text()
    rls = (ROOT / "deploy" / "supabase" / "rls.sql").read_text()
    for t in ("receptionist_configs", "receptionist_messages", "receptionist_blocks", "receptionist_spam"):
        assert f"CREATE TABLE {t}" in schema
        assert f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0012_receptionist_spam'" in schema
    spam = schema[schema.index("CREATE TABLE receptionist_spam"):].split(");", 1)[0]
    assert "user_id" not in spam  # anonymised: hash + count only


def _doc_settings(tmp_path, **kw) -> Settings:
    return Settings(
        _env_file=None, env="test", database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
        receptionist_store_dir=str(tmp_path / "rcp"), **kw,
    )


async def test_doctor_receptionist_section_off_by_default(tmp_path):
    from friday.ops import doctor

    sec = await doctor.check_receptionist(_doc_settings(tmp_path))
    text = "\n".join(c.message for c in sec.checks)
    assert "off (default)" in text and "probe has not been run" in text
    assert all(c.status != doctor.FAIL for c in sec.checks)
    assert "receptionist" in doctor.SECTIONS and doctor.TITLES["receptionist"]


async def test_doctor_receptionist_counts_opted_in_and_reads_probe_verdict(tmp_path):
    from friday.core.container import Container
    from friday.core.models import User, UserStatus
    from friday.db import Database
    from friday.ops import doctor
    from friday.receptionist.store import SqlReceptionistStore

    st = _doc_settings(tmp_path, receptionist_enabled=True, receptionist_inbound_number=FRIDAY_NUMBER)
    db = Database(st.database_url)
    await db.create_all()
    c = Container(st)
    c.override_db(db)
    u = await c.repos.users.add(User(phone="+919800000311", status=UserStatus.ACTIVE))
    await SqlReceptionistStore(db).save_config(u.id, ReceptionistConfig(enabled=True))
    await db.dispose()
    pr = P.InboundProbe(["Diversion"], tmp_path / "rcp" / P.PROBE_FILE)
    pr.record({"From": CALLER, "To": FRIDAY_NUMBER, "Diversion": f"<sip:{USER_PHONE}@h>"})
    sec = await doctor.check_receptionist(st)
    msgs = [x.message for x in sec.checks]
    assert "opted-in users: 1" in msgs
    assert any("IS delivered, in key(s): Diversion" in m for m in msgs)
    assert USER_PHONE not in "\n".join(msgs)


async def test_doctor_warns_when_on_and_probe_shows_nothing(tmp_path):
    from friday.ops import doctor

    pr = P.InboundProbe([], tmp_path / "rcp" / P.PROBE_FILE)
    pr.record({"From": CALLER, "To": FRIDAY_NUMBER})
    sec = await doctor.check_receptionist(_doc_settings(tmp_path, receptionist_enabled=True))
    assert any(c.status == doctor.WARN and "NOT delivered" in c.message for c in sec.checks)


# ------------------------------------------------------------------ (3) shared spam table
async def test_spam_table_is_anonymised_and_counts_on_both_stores(world):
    s = world.store
    assert await s.spam_reports("+919100000099") == 0
    assert await s.record_spam("+919100000099") == 1
    assert await s.record_spam("09100000099") == 2  # same last 10 digits
    assert await s.spam_reports("+91 91000 00099") == 2
    assert await s.spam_reports("+919100000098") == 0
    assert await s.record_spam(None) == 0
    assert await s.record_spam("123") == 0
    if world.kind == "sql":
        from sqlalchemy import select

        from friday.receptionist.dbmodel import ReceptionistSpamRow

        async with world.store.db.session() as ses:
            rows = (await ses.execute(select(ReceptionistSpamRow))).scalars().all()
        assert len(rows) == 1 and rows[0].reports == 2
        assert rows[0].number_hash == spam_key("+919100000099")
        assert "9100000099" not in rows[0].number_hash
        assert not hasattr(rows[0], "user_id")


async def test_a_spam_verdict_is_recorded_and_shared_reports_raise_an_unknown_caller():
    w = await sim.make_world()
    spam = caller("spam-loan-hinglish")
    await sim.run_caller(w, spam)
    assert await w.store.spam_reports(spam.number) == 1
    plain = caller("english-recruiter")
    w2 = await sim.make_world()
    assert (await sim.run_caller(w2, plain)).urgency == "normal"
    w3 = await sim.make_world()
    for _ in range(5):
        await w3.store.record_spam(plain.number)
    assert (await sim.run_caller(w3, plain)).urgency == "spam"


async def test_user_purge_leaves_the_shared_table_alone(world):
    await world.store.record_spam("+919100000099")
    await world.store.delete_user(world.u1)
    assert await world.store.spam_reports("+919100000099") == 1


# ------------------------------------------------------------------ (4) the declined test ring
async def _world_with_pool():
    w = await sim.make_world()
    w.service.resolver.pool_numbers = lambda: [POOL]
    return w


async def test_declined_test_ring_from_the_pool_number_means_forwarding_works():
    w = await _world_with_pool()
    port = sim.ScriptedPort(caller("doctor-clinic"), w.mono)
    rep = await w.service.handle_call(port, POOL, f"<sip:{USER_PHONE}@vobiz.example>;reason=user-busy")
    assert rep is not None and rep.route == Route.TEST_RING
    assert port.spoken == []  # nothing spoken
    assert await w.store.list_messages(USER) == []  # nothing stored
    assert (await w.store.get_config(USER)).forwarding_verified is True
    assert len(w.sent) == 1 and w.sent[0][1] == copy.t("test.confirmed", "hinglish") and w.sent[0][2] == []


async def test_test_ring_is_silent_while_paused_and_an_ordinary_caller_is_not_a_test_ring():
    w = await _world_with_pool()
    w.paused[0] = True
    port = sim.ScriptedPort(caller("doctor-clinic"), w.mono)
    rep = await w.service.handle_call(port, POOL, f"<sip:{USER_PHONE}@h>")
    assert rep.route == Route.TEST_RING and w.sent == []
    assert (await w.store.get_config(USER)).forwarding_verified is False
    w.paused[0] = False
    assert (await w.service.claims(f"<sip:{USER_PHONE}@h>", CALLER)).route == Route.MATCHED
    unknown = await w.service.claims("<sip:+919800000777@h>", POOL)
    assert unknown.route == Route.UNKNOWN_NUMBER  # a pool caller for a non-user is not a test ring


# ------------------------------------------------------------------ (5) receptionist-only number
async def test_refused_route_speaks_only_the_fixed_line_and_stores_nothing():
    w = await sim.make_world()
    port = sim.ScriptedPort(caller("doctor-clinic"), w.mono)
    rep = await w.service.handle_call(port, CALLER, None, resolution=Resolution(Route.REFUSED))
    assert rep is not None and rep.route == Route.REFUSED
    assert port.spoken == [lines.say("blocked.end", "hinglish")]
    assert list(w.store.messages.values()) == [] and w.sent == []
    assert rep.capture.outcome == CallOutcomeKind.BLOCKED


async def test_only_number_setting_is_off_by_default_and_front_door_callers_are_untouched():
    assert Settings(_env_file=None).receptionist_only_number is False
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_redirect_fields=["Diversion"],
        receptionist_only_number=True, receptionist_inbound_number="+918000000077",
    )
    try:
        rcp = f.rt.callbacks.receptionist()
        direct = InboundCallReceived(from_phone=CALLER, to_number=FRIDAY_NUMBER, provider_call_id="p1")
        assert await rcp.claims(direct) is None  # another Friday number: front door as before
        only = InboundCallReceived(from_phone=CALLER, to_number="+918000000077", provider_call_id="p2")
        assert (await rcp.claims(only)).route == Route.REFUSED
        unknown = InboundCallReceived(
            from_phone=CALLER, to_number="+91 80000 00077", provider_call_id="p3",
            call_fields={"Diversion": "<sip:+919800000777@h>"},
        )
        assert (await rcp.claims(unknown)).route == Route.REFUSED
    finally:
        await f.close()


async def test_only_number_off_keeps_the_generic_taker_path():
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_inbound_number="+918000000077",
    )
    try:
        rcp = f.rt.callbacks.receptionist()
        ev = InboundCallReceived(from_phone=CALLER, to_number="+918000000077", provider_call_id="p4")
        assert await rcp.claims(ev) is None
    finally:
        await f.close()


async def test_call_fields_flow_through_the_real_claim_path():
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_redirect_fields=["Diversion"]
    )
    try:
        await f.user("+919811100001", "Rahul")
        rcp = f.rt.callbacks.receptionist()
        uid = (await f.c.repos.users.get_by_phone("+919811100001")).id
        await rcp.service.store.save_config(uid, ReceptionistConfig(enabled=True, user_name="Rahul"))
        ev = InboundCallReceived(
            from_phone=CALLER, to_number=FRIDAY_NUMBER, provider_call_id="p5",
            call_fields={"X-Original-Called": "<sip:+919811100001@h>;reason=no-answer"},
        )
        res = await rcp.claims(ev)
        assert res is not None and res.route == Route.MATCHED and res.user_id == uid
    finally:
        await f.close()


# ------------------------------------------------------------------ docs stay in sync
def test_doc_mentions_the_new_pieces():
    text = (ROOT / "docs" / "RECEPTIONIST.md").read_text(encoding="utf-8")
    for needle in ("call_fields", "FRIDAY_RECEPTIONIST_ONLY_NUMBER", "0012_receptionist_spam", "forwarding_verified"):
        assert needle in text, needle
    for pl in lines.all_lines():
        assert f"`{pl.id}`" in text
    assert re.search(r"rcpw\.test\.confirmed", text)
