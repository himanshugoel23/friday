# ruff: noqa: E501, F811
"""C3: the staff console over HTTP (fake ports), wiring/switch default OFF, the Robin ladder hook, migration + at-rest. Tested with fakes."""

from __future__ import annotations

import re
from datetime import timedelta

import httpx
from fastapi import FastAPI

from friday.concierge import humanport
from friday.concierge.console import build_console
from friday.concierge.desk import HandoffCard, Shift
from tests.concierge.conftest import PARENT_NUMBER, PW, T0, make_rig
from tests.robin.conftest import w  # noqa: F401 - the Robin fixture, reused


def make_app(rig) -> FastAPI:
    app = FastAPI()
    app.include_router(build_console(rig.service, rig.desk, rig.sessions, rig.audit, secure_cookie=False), prefix="/concierge")
    return app


def client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", follow_redirects=False)


async def login(c, rig, sid="c1", pw=PW, code="123456"):
    rig.code(sid, code)
    return await c.post("/concierge/login", data={"staff_id": sid, "password": pw, "code": code})


def csrf_of(html: str) -> str:
    m = re.search(r"name='csrf' value='([^']+)'", html)
    assert m
    return m.group(1)


async def test_every_page_needs_a_login_and_has_hardened_headers(rig):
    async with client(make_app(rig)) as c:
        for path in ("/concierge/", "/concierge/desk", "/concierge/r/abc"):
            r = await c.get(path)
            assert r.status_code == 303 and r.headers["location"].startswith("/concierge/login")
        r = await c.post("/concierge/r/abc/claim", data={"csrf": "x"})
        assert r.status_code == 303
        page = await c.get("/concierge/login")
        h = page.headers
        assert h["cache-control"] == "no-store" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer" and "default-src 'none'" in h["content-security-policy"]
        assert "<script" not in page.text.lower()


async def test_login_failure_is_one_plain_message(rig):
    async with client(make_app(rig)) as c:
        rig.code("c1")
        a = await c.post("/concierge/login", data={"staff_id": "c1", "password": "bad", "code": "123456"})
        b = await c.post("/concierge/login", data={"staff_id": "ghost", "password": PW, "code": "123456"})
        assert a.status_code == b.status_code == 303 and a.headers["location"] == b.headers["location"]
        assert "set-cookie" not in a.headers
        assert all(e.staff_id == "unknown" for e in await rig.audit.entries() if e.action == "login_failed")  # what was typed is never logged


async def test_one_screen_request_view_with_masked_number_watermark_and_actions(rig):
    r = (await rig.service.intake("par1", {"summary": "Book an appointment with Dr Rao on Friday", "category": "doctor_booking"})).request_id
    async with client(make_app(rig)) as c:
        res = await login(c, rig)
        assert res.status_code == 303 and "httponly" in res.headers["set-cookie"].lower() and "samesite=strict" in res.headers["set-cookie"].lower()
        q = await c.get("/concierge/")
        assert "doctor_booking" in q.text and "health" in q.text and "signed in as c1" in q.text
        page = await c.get(f"/concierge/r/{r}")
        t = page.text
        assert "Book an appointment with Dr Rao" in t and "+91 ••••• ••555" in t and PARENT_NUMBER not in t and "9800000555" not in t
        assert "c1" in t and "data:image/svg+xml" in t and "c1%3C%2Ftext" not in t  # watermark carries the staff id
        assert "Take this request" in t and "Mark done" not in t
        tok = csrf_of(t)
        assert (await c.post(f"/concierge/r/{r}/claim", data={"csrf": "wrong"})).status_code == 403  # CSRF
        assert (await c.post(f"/concierge/r/{r}/claim", data={"csrf": tok}, headers={"origin": "http://evil.example"})).status_code == 403
        assert (await c.post(f"/concierge/r/{r}/claim", data={"csrf": tok})).status_code == 303
        t = (await c.get(f"/concierge/r/{r}")).text
        for needle in ("Add note", "Add proof", "Contact through a Robin line", "Mark done", "Escalate to a lead"):
            assert needle in t
        # done without proof is refused with a plain code
        res = await c.post(f"/concierge/r/{r}/done", data={"csrf": tok})
        assert "proof_required" in res.headers["location"]
        await c.post(f"/concierge/r/{r}/note", data={"csrf": tok, "text": "Clinic opens at 9"})
        await c.post(f"/concierge/r/{r}/note", data={"csrf": tok, "text": "the otp is 123456"})
        await c.post(f"/concierge/r/{r}/proof", data={"csrf": tok, "kind": "call_note", "ref": "Booked 11:30 Friday"})
        res = await c.post(f"/concierge/r/{r}/contact", data={"csrf": tok, "party": "parent"})
        assert "Parent+via+Robin+line" in res.headers["location"] or "Parent%20via%20Robin%20line" in res.headers["location"]
        t = (await c.get(f"/concierge/r/{r}")).text
        assert "Clinic opens at 9" in t and "123456" not in t and "call_note" in t
        assert (await c.post(f"/concierge/r/{r}/done", data={"csrf": tok})).headers["location"].startswith("/concierge/")
    req = await rig.store.request_get(r)
    assert req.status.value == "done"
    actions = [e.action for e in await rig.audit.entries()]
    assert actions.count("claim") == 1 and "done" in actions and "contact_parent" in actions and await rig.audit.verify() is None


async def test_idle_ten_minutes_signs_out_and_the_next_page_asks_again(rig):
    async with client(make_app(rig)) as c:
        await login(c, rig)
        assert (await c.get("/concierge/")).status_code == 200
        rig.clock.advance(minutes=11)
        r = await c.get("/concierge/")
        assert r.status_code == 303 and "login" in r.headers["location"]
        assert (await c.get("/concierge/")).status_code == 303


async def test_there_is_no_export_download_or_csv_route(rig):
    app = make_app(rig)
    paths = set(app.openapi()["paths"])
    assert "/concierge/login" in paths  # the route listing is real, not empty
    assert not [p for p in paths if re.search(r"export|download|csv|bulk|dump", p)]
    async with client(app) as c:
        await login(c, rig, "lead1")
        for p in ("/concierge/export", "/concierge/export/requests.csv", "/concierge/download/all", "/concierge/csv"):
            assert (await c.get(p)).status_code == 404
        assert "export_denied" in [e.action for e in await rig.audit.entries()]
        assert "attachment" not in (await c.get("/concierge/")).headers.get("content-disposition", "")


async def test_a_reviewer_cannot_act_and_a_concierge_does_not_see_lane_2(rig):
    r = (await rig.service.intake("par1", {"summary": "Order milk", "category": "grocery"})).request_id
    async with client(make_app(rig)) as c:
        await login(c, rig, "c1")
        assert "not on the emergency desk" in (await c.get("/concierge/desk")).text
    async with client(make_app(rig)) as c:
        await login(c, rig, "rev1", code="654321")
        t = (await c.get(f"/concierge/r/{r}")).text
        assert "Take this request" not in t and "Add note" not in t


async def test_lane_2_screens_join_and_close(rig):
    await rig.desk.set_shift(rig.staff("lead1"), Shift("s1", T0 - timedelta(hours=1), T0 + timedelta(hours=8), "e1", "e2"))
    await rig.desk.receive(HandoffCard("inc9", "par1", "fam1", "hinglish", "emergency", "SOS pressed", ai_actions=("rang_parent",), consent_items=("desk_may_call_112",)))
    humanport.register_human_joined(rig.desk.is_human_joined)
    try:
        async with client(make_app(rig)) as c:
            await login(c, rig, "e1")
            assert "SOS pressed" in (await c.get("/concierge/desk")).text
            t = (await c.get("/concierge/desk/inc9")).text
            assert "I am on the line" in t and "desk_may_call_112" in t and "not made from here yet" in t
            tok = csrf_of(t)
            await c.post("/concierge/desk/inc9/join", data={"csrf": tok})
            assert await humanport.human_joined("inc9")
            t = (await c.get("/concierge/desk/inc9")).text
            assert "Hand back to Robin" in t
            await c.post("/concierge/desk/inc9/close", data={"csrf": tok, "outcome": "false_alarm", "reason": "test"})
            assert not await humanport.human_joined("inc9")
    finally:
        humanport.register_human_joined(None)
    assert await rig.desk.false_alarms("par1") == {"test": 1}


# ---------------------------------------------------------------- switch, wiring, Robin hook, migration, at rest
def test_switch_defaults_off_and_is_in_env_example_and_doctor(tmp_path):
    from friday.core.config import Settings
    from friday.ops import doctor

    assert Settings(_env_file=None).robin_concierge_enabled is False
    root = __import__("pathlib").Path(doctor.__file__).resolve().parents[2]
    assert "FRIDAY_ROBIN_CONCIERGE_ENABLED=false" in (root / ".env.example").read_text()
    s = doctor.check_robin(Settings(_env_file=None, robin_enabled=False))
    assert any("FRIDAY_ROBIN_CONCIERGE_ENABLED=off" in c.message for c in s.checks)
    on = doctor.check_robin(Settings(_env_file=None, robin_enabled=False, robin_concierge_enabled=True))
    assert any(c.status == doctor.WARN and "CONCIERGE_ENABLED=on" in c.message for c in on.checks)


def test_nothing_mounts_when_off_or_when_ports_are_missing(container):
    from fastapi import FastAPI

    from friday.concierge.wiring import maybe_mount

    app = FastAPI()
    assert maybe_mount(app, container) is None  # switch off
    container.settings.robin_concierge_enabled = True
    assert maybe_mount(app, container) is None and not [p for p in app.openapi()["paths"] if "concierge" in p]  # on, but no directory/TOTP/family: not mounted
    rig = make_rig()
    container.override("concierge_ports", {"directory": rig.directory, "totp": rig.totp, "family": rig.family, "emergency": rig.emergency})
    parts = maybe_mount(app, container)
    try:
        assert parts and "/concierge/login" in app.openapi()["paths"]
        assert parts["desk"].cfg.desk_ack_s == 180 and parts["sessions"].idle.total_seconds() == 600
    finally:
        humanport.register_human_joined(None)


async def test_the_robin_ladder_stops_ringing_once_a_person_joined(w):
    """The one-line hook in friday/robin/alerts.py: with a person on the line the nudge/call steps are skipped (tested with Robin's fake dialler)."""
    from friday.robin.alerts import RobinAlert
    from friday.robin.models import CallResult, Tier

    async def run(joined: bool) -> int:
        fam, parent = await w.family()
        await w.hub.fam.admin_consent(fam, "device_signals")
        w.caller.script(CallResult.NO_ANSWER)
        res = await w.hub.alerts.raise_alert(RobinAlert(parent_member_id=parent.id, tier=Tier.HIGH, scenario="S1", why="x"))
        humanport.register_human_joined((lambda _i: _async(True)) if joined else None)
        for _ in range(12):
            w.go(minutes=2)
            await w.hub.alerts.tick()
        assert res.incident_id
        return len([c for c in w.caller.calls if c.purpose in ("nudge", "escalation_child", "escalation_second")])

    async def _async(v):
        return v

    try:
        stopped = await run(True)
    finally:
        humanport.register_human_joined(None)
    assert stopped == 1  # only the very first nudge (before the person joined)


async def test_robin_emergency_adapter_raises_a_real_alert(w):
    from friday.concierge.wiring import RobinEmergencyReroute
    from friday.robin import alerts as alerts_mod

    fam, parent = await w.family()
    await w.hub.fam.admin_consent(fam, "device_signals")
    alerts_mod.set_default_engine(w.hub.alerts)
    try:
        inc = await RobinEmergencyReroute().reroute(member_id=parent.id, parent_id=parent.id, reason="concierge_distress")
    finally:
        alerts_mod.set_default_engine(None)
    assert inc is not None


def test_migration_0021_up_down_chain_and_sql_files(tmp_path):
    from pathlib import Path

    from sqlalchemy import create_engine, inspect, text

    from friday.db import migrate
    from friday.db.base import Base
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0021_concierge"
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    names = ("robin_concierge_requests", "robin_concierge_audit", "robin_concierge_docs")
    insp = inspect(eng)
    for t in names:
        assert {c["name"] for c in insp.get_columns(t)} == {c.name for c in Base.metadata.tables[t].columns}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0021_concierge"
    migrate.downgrade(url, "0020_robin_device")
    assert not set(names) & set(inspect(eng).get_table_names()) and "robin_device_states" in inspect(eng).get_table_names()
    migrate.upgrade(url)
    eng.dispose()
    root = Path(doctor.__file__).resolve().parents[2] / "deploy" / "supabase"
    schema, rls = (root / "schema.sql").read_text(), (root / "rls.sql").read_text()
    for t in names:
        assert f"CREATE TABLE {t}" in schema and f"ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY;" in rls
    assert "'0021_concierge'" in schema


async def test_nothing_personal_is_stored_in_the_clear(db, rig):
    from sqlalchemy import text

    from friday.concierge.audit import AuditLog
    from friday.concierge.dbmodel import DbConciergeStore
    from friday.concierge.desk import DeskService
    from friday.concierge.service import ConciergeService

    store = DbConciergeStore(db)
    audit = AuditLog(store, rig.clock)
    svc = ConciergeService(store=store, audit=audit, clock=rig.clock, family=rig.family, directory=rig.directory, emergency=rig.emergency, bridge=rig.bridge)
    desk = DeskService(store=store, audit=audit, clock=rig.clock, directory=rig.directory, pager=rig.pager)
    r = (await svc.intake("par1", {"summary": "Refill Papa's thyroxine at Gupta Medicals", "category": "medicine"})).request_id
    await svc.claim(rig.staff("c1"), r)
    await svc.note(rig.staff("c1"), r, "Spoke to Gupta about thyroxine stock")
    await desk.set_shift(rig.staff("lead1"), Shift("s1", T0 - timedelta(hours=1), T0 + timedelta(hours=1), "e1", "e2"))
    await desk.receive(HandoffCard("incZ", "par1", "fam1", "hinglish", "high", "Caller asked for thyroxine money", ai_actions=("rang_parent",)))
    async with db.session() as s:
        dump = ""
        for t in ("robin_concierge_requests", "robin_concierge_audit", "robin_concierge_docs"):
            dump += repr((await s.execute(text(f"SELECT * FROM {t}"))).all())
    for marker in ("thyroxine", "Gupta", "Papa", "money", "rang_parent", "Refill"):
        assert marker not in dump
    assert dump  # and the rows exist
