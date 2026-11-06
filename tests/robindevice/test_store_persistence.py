# ruff: noqa: E501
"""T02: the device state survives a restart (a new service + store on the same DB). Tested with fakes on SQLite."""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import create_engine, inspect, select, text

from friday.db import migrate
from friday.robindevice.dbmodel import RobinDeviceStateRow
from friday.robindevice.ports import CONSENT_ITEMS
from friday.robindevice.schemas import LocationIn
from friday.robindevice.store import (
    Device,
    Event,
    Fired,
    InMemoryDeviceStore,
    ParentState,
    Prompt,
    sha256_hex,
    state_from_dict,
    state_to_dict,
)
from tests.robindevice.conftest import ev
from tests.robindevice.dbrig import B, DbRig


def H(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def rig(db):
    r = DbRig(db)
    yield r
    await r.close()


async def _hb(node, token, rig, **extra):
    body = {"app_version": "1.0.1", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}, **extra}
    return await node.client.post(f"{B}/heartbeat", headers=H(token), json=body)


async def test_pairing_token_events_prompts_and_shadow_clock_survive_a_restart(rig):
    a = await rig.node()
    token = await rig.pair(a, shadow_days=None)  # keep the default learning week running
    st = a.store.peek("p1")
    shadow_start = st.shadow_start_ms
    assert shadow_start == rig.clock.ms
    evs = [ev("camera_in_use_start", rig.clock.ms), ev("camera_in_use_stop", rig.clock.ms + 60_000)]
    r = await a.client.post(f"{B}/signals", headers=H(token), json={"events": evs})
    assert r.status_code == 200 and r.json()["accepted"] == 2, r.text
    st.prompts["pr1"] = Prompt("pr1", "S1", "HIGH", "s1_high", "inc1", rig.clock.ms, rig.clock.ms, rig.clock.ms + 3_600_000, True, {"x": 1})
    st.fine_counts["pat"] = 2
    st.trusted.add("h" * 64)
    a.service.note_external("p1", "checkin_unanswered")
    await a.service.pause(st, 5)

    b = await rig.node()  # restart: empty cache, same database
    st2 = await b.service.authenticate(token)
    assert st2 is not None and st2.parent_id == "p1" and st2 is not st
    assert st2.device.token_hash == sha256_hex(token) and st2.device.app_version == "1.0.0"
    assert [e.type for e in st2.events] == ["camera_in_use_start", "camera_in_use_stop"]
    assert st2.shadow_start_ms == shadow_start  # the learning-week clock is not reset
    assert st2.prompts["pr1"].full_screen is True and st2.prompts["pr1"].fmt == {"x": 1}
    assert st2.counters == st.counters and st2.fine_counts == {"pat": 2} and st2.trusted == {"h" * 64}
    assert st2.external.get("checkin_unanswered") and st2.paused_until_ms == st.paused_until_ms
    assert list(st2.seen_ids) == list(st.seen_ids) and len(st2.seen_ids) == 2
    assert (await _hb(b, token, rig)).status_code == 200  # HTTP layer on the new process accepts the old token
    assert (await _hb(b, token + "x", rig)).status_code == 404


async def test_replayed_event_ids_stay_duplicates_after_a_restart(rig):
    a = await rig.node()
    token = await rig.pair(a)
    e = ev("camera_in_use_start", rig.clock.ms)
    assert (await a.client.post(f"{B}/signals", headers=H(token), json={"events": [e]})).json()["accepted"] == 1
    b = await rig.node()
    r = await b.client.post(f"{B}/signals", headers=H(token), json={"events": [e]})
    assert r.json()["duplicates"] == 1 and r.json()["accepted"] == 0


async def test_heartbeat_state_is_written_through(rig):
    a = await rig.node()
    token = await rig.pair(a)
    rig.clock.advance(minutes=10)
    assert (await _hb(a, token, rig, battery_low=True)).status_code == 200
    b = await rig.node()
    dev = (await b.service.authenticate(token)).device
    assert dev.last_seen_ms == rig.clock.ms and dev.battery_low is True and dev.app_version == "1.0.1"


async def test_pair_code_is_single_use_and_survives_restart(rig):
    a = await rig.node()
    rig.parents.add("p1", "en")
    code = await a.service.create_pairing_code("p1")
    b = await rig.node()  # restart between issuing and using the code
    body = {"code": code, "app_version": "1", "os_sdk": 34}
    assert (await b.client.post(f"{B}/pair", json=body)).status_code == 200
    c = await rig.node()
    assert (await c.client.post(f"{B}/pair", json=body)).status_code == 404  # used, seen by any process
    assert (await a.client.post(f"{B}/pair", json=body)).status_code == 404


async def test_pair_code_expiry_and_one_live_code_per_parent(rig):
    a = await rig.node()
    rig.parents.add("p1", "en")
    old = await a.service.create_pairing_code("p1")
    new = await a.service.create_pairing_code("p1")  # replaces the old one
    b = await rig.node()
    assert (await b.client.post(f"{B}/pair", json={"code": old, "app_version": "1", "os_sdk": 34})).status_code == 404
    rig.clock.advance(minutes=16)
    c = await rig.node()
    assert (await c.client.post(f"{B}/pair", json={"code": new, "app_version": "1", "os_sdk": 34})).status_code == 404  # expired


async def test_a_pairing_made_on_another_process_is_found_by_token(rig):
    a = await rig.node()
    b = await rig.node()  # b loaded before the pairing exists
    token = await rig.pair(a)
    st = await b.service.authenticate(token)
    assert st is not None and st.parent_id == "p1"


async def test_re_pair_replaces_the_old_token_and_revoke_persists(rig):
    a = await rig.node()
    t1 = await rig.pair(a)
    code = await a.service.create_pairing_code("p1")
    t2 = (await a.client.post(f"{B}/pair", json={"code": code, "app_version": "2", "os_sdk": 34})).json()["device_token"]
    b = await rig.node()
    assert await b.service.authenticate(t1) is None and await b.service.authenticate(t2) is not None
    assert await b.service.revoke("p1")
    c = await rig.node()
    assert await c.service.authenticate(t2) is None


async def test_erase_removes_the_rows(rig, db):
    a = await rig.node()
    token = await rig.pair(a)
    assert (await a.client.delete(f"{B}/erase", headers=H(token))).status_code == 200
    c = await rig.node()
    assert await c.service.authenticate(token) is None and c.store.peek("p1") is None
    _, rows = await _raw(db, "robin_device_states")
    assert rows == []


async def _raw(db, table):
    async with db.session() as s:
        res = await s.execute(text(f"SELECT * FROM {table}"))  # noqa: S608 - fixed table names
        return list(res.keys()), [tuple(r) for r in res.all()]


async def test_raw_columns_hold_no_plaintext_token_code_phone_or_text(rig, db):
    a = await rig.node()
    token = await rig.pair(a)
    rig.parents.add("p2", "en")
    code2 = await a.service.create_pairing_code("p2")
    phone, said = "+919800000555", "OTP bhej do 482913 abhi"
    await a.service.feed_call_turn("p1", "call-1", "caller", f"{said} {phone}", 1.0)  # scored, dropped
    await a.client.post(f"{B}/signals", headers=H(token), json={"events": [ev("camera_in_use_start", rig.clock.ms)]})
    await a.service.sos(a.store.peek("p1"), LocationIn(lat=28.61234, lon=77.20987))
    cols, rows = await _raw(db, "robin_device_states")
    cols2, rows2 = await _raw(db, "robin_device_codes")
    assert rows and rows2
    blob = "".join(repr(v) for r in (*rows, *rows2) for v in r)
    for needle in (token, token[4:], code2, phone, "482913", "OTP", "bhej", "camera_in_use", "heartbeats", "SOS button"):
        assert needle not in blob, needle
    row = dict(zip(cols, rows[0], strict=True))
    assert row["token_hash"] == sha256_hex(token) and len(row["token_hash"]) == 64
    assert str(row["data"]).startswith("v1:")  # AES-GCM envelope, not JSON
    assert sha256_hex(code2) not in blob  # the code hash is keyed, not a bare sha256
    code_row = dict(zip(cols2, rows2[0], strict=True))
    assert len(code_row["code_hash"]) == 64 and code_row["code_hash"] != code2
    # what IS stored (read back through the ORM) holds no text, name, number or coordinates
    async with db.session() as s:
        data = (await s.execute(select(RobinDeviceStateRow.data))).scalars().all()
    dump = json.dumps(data)
    assert len(dump) > 200
    for needle in ("OTP", "bhej", phone, "482913", "28.61234", "77.20987"):
        assert needle not in dump, needle
    assert not re.search(r"\d{10,}", re.sub(r"\d{13}", "", re.sub(r"[0-9a-f]{64}", "", dump)))  # only 13-digit ms timestamps (and 64-hex hashes, which can hold a digit run by chance) are long numbers


def test_serialisation_round_trips_every_field():
    st = ParentState("px")
    st.device = Device("t" * 64, 1, 2, "1.0", 34, {"a": True}, True)
    st.events.append(Event("e1", "camera_in_use_start", 5, {"k": 1}))
    st.remember_id("e1")
    st.bump("a", 3)
    st.prompts["p"] = Prompt("p", "S1", "HIGH", "k", "i", 1, 2, 3, False, {"q": "r"}, "pat", "h", "acked")
    st.fired["f"] = Fired(2, 9, True, 11)
    st.trusted |= {"x"}
    st.nudge_times, st.shadow_nudge_times = [1, 2], [3]
    st.audit.append({"ts_ms": 1, "tier": "INFO", "details": {}})
    st.findings.append({"ts_ms": 2})
    st.shadow_days, st.shadow_start_ms, st.payment_threshold_paise, st.s7_open, st.stopped = 3, 7, 500, True, True
    st.sensitivity, st.paused_until_ms, st.support_window_until_ms = "high", 8, 9  # type: ignore[assignment]
    again = state_from_dict("px", json.loads(json.dumps(state_to_dict(st))))
    assert state_to_dict(again) == state_to_dict(st)
    assert again.device == st.device and again.prompts == st.prompts and again.fired == st.fired and again.events == st.events


async def test_in_memory_store_is_still_the_default(rig):
    from friday.robindevice.ports import FakeAlertPort
    from friday.robindevice.schemas import PairIn
    from friday.robindevice.service import DeviceService

    svc = DeviceService(alerts=FakeAlertPort(), consent=rig.consent, parents=rig.parents, now_ms=rig.clock)
    assert isinstance(svc.store, InMemoryDeviceStore)
    rig.parents.add("p1", "en")
    code = await svc.create_pairing_code("p1")
    res = await svc.pair(PairIn(code=code, app_version="1", os_sdk=34))
    assert res and await svc.authenticate(res["device_token"]) is not None and CONSENT_ITEMS


def test_migration_0020_up_down_and_chain(tmp_path):
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0020_robin_device"
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    names = {"robin_device_states", "robin_device_codes"}
    assert names <= set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0020_robin_device"
    migrate.downgrade(url, "0019_robin_family")
    assert not names & set(inspect(eng).get_table_names())
    assert "robin_families" in inspect(eng).get_table_names()  # 0019 is untouched
    migrate.upgrade(url)
    assert names <= set(inspect(eng).get_table_names())
    eng.dispose()


def test_migration_matches_the_models_and_sql_files(tmp_path):
    from pathlib import Path

    from friday.db.base import Base

    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    insp = inspect(eng)
    for t in ("robin_device_states", "robin_device_codes"):
        assert {c["name"] for c in insp.get_columns(t)} == {c.name for c in Base.metadata.tables[t].columns}
    eng.dispose()
    root = Path(__file__).resolve().parents[2] / "deploy" / "supabase"
    schema, rls = (root / "schema.sql").read_text(), (root / "rls.sql").read_text()
    for t in ("robin_device_states", "robin_device_codes"):
        assert f"CREATE TABLE {t}" in schema and f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0020_robin_device'" in schema
