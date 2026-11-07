# ruff: noqa: E501
"""/ops-status/<token>/robin: counts only. Walks the whole response: integers and short status words, no digit run of 10+."""

from __future__ import annotations

import re
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.opsstatus import ops_status_router
from friday.robin import opscounts
from friday.robin.alerts import RobinAlert
from friday.robin.models import Tier
from friday.robin.store import Record
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE

TOKEN = "t" * 20
MAX_WORD = 8


def walk(node, found=None):
    """Every key and value; fail on a bool-less non-int, a long string or a 10+ digit run."""
    found = [] if found is None else found
    if isinstance(node, dict):
        for k, v in node.items():
            assert len(str(k)) <= 24 and not re.search(r"\d{10,}", str(k))
            walk(v, found)
    elif isinstance(node, list):
        for v in node:
            walk(v, found)
    elif isinstance(node, str):
        assert len(node) <= MAX_WORD and not re.search(r"\d{10,}", node), node
        found.append(node)
    else:
        assert type(node) is int, node
        assert len(str(abs(node))) < 10
    return found


def client(w, monkeypatch, *, robin_on=True, device_service=None):
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", TOKEN)
    monkeypatch.chdir("/")
    hub = w.hub
    hub.device_service = device_service
    c = SimpleNamespace(settings=SimpleNamespace(robin_enabled=robin_on), get=lambda name: hub)
    app = FastAPI()
    app.include_router(ops_status_router(), prefix="/ops-status")
    app.state.container = c
    return TestClient(app)


async def test_bad_token_is_404_on_both_routes(w, monkeypatch):
    cl = client(w, monkeypatch)
    for path in ("/ops-status/wrong-token-wrong-token/robin", "/ops-status/wrong-token-wrong-token/robin.json", "/ops-status/x/robin"):
        assert cl.get(path).status_code == 404
    assert cl.get(f"/ops-status/{TOKEN}/robin.json").status_code == 200


async def test_robin_off_reports_only_a_status_word(w, monkeypatch):
    r = client(w, monkeypatch, robin_on=False).get(f"/ops-status/{TOKEN}/robin.json")
    assert r.status_code == 200 and r.json() == {"status": "off"}


async def test_counts_after_a_busy_day_and_nothing_personal(w, monkeypatch):
    opscounts.reset_counters()
    fam, parent = await w.family()
    from friday.robin.models import ConsentSource

    await w.hub.fam.give_consent(parent.id, "device_signals", ConsentSource.ADMIN_CHAT)
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "unknown caller 22 minutes", dedupe_key="a"))
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.INFO, "S6", "night video activity", dedupe_key="b"))
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "sos", "pressed the SOS button", dedupe_key="c"))
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "fall", "a fall was detected", dedupe_key="d"))
    await w.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="checkin", key="2026-01-03", status="done", at=w.clock.now(), data={}))
    await w.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="checkin", key="2026-01-02", status="unanswered", at=w.clock.now(), data={}))
    await w.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=w.clock.now(), data={"text": "SECRET-TEXT", "member_id": parent.id}))
    w.channel.fail = True  # the parent's channel is down, so the T08 outbox drain leaves the line queued
    await w.hub.tick()
    cl = client(w, monkeypatch)
    r = cl.get(f"/ops-status/{TOKEN}/robin.json")
    assert r.status_code == 200
    doc = r.json()
    words = walk(doc)
    assert set(words) <= {"ok"}
    assert doc["families"]["active"] == 1
    assert doc["alerts_24h"]["high"] >= 1 and doc["alerts_24h"]["emergency"] >= 2 and doc["alerts_24h"]["info"] == 1
    assert doc["sos_24h"] == 1 and doc["falls_24h"] == 1
    assert doc["checkins_24h"] == {"done": 1, "unanswered": 1}
    assert doc["outbox_pending"] >= 1 and doc["incidents_active"] >= 3
    assert doc["last_tick_age_s"] == 0 and doc["errors"] == 0
    raw = r.text + cl.get(f"/ops-status/{TOKEN}/robin").text
    for forbidden in (CHILD_PHONE, PARENT_PHONE, "SECRET-TEXT", "Papa", "Asha", "unknown caller", "SOS button", fam.id, parent.id, "+91"):
        assert forbidden not in raw


async def test_plain_text_view_is_key_equals_integer(w, monkeypatch):
    t = client(w, monkeypatch).get(f"/ops-status/{TOKEN}/robin").text
    assert all(re.fullmatch(r"[a-z_0-9.]+=(-?\d{1,9}|ok)", ln) for ln in t.strip().splitlines()), t


async def test_devices_and_heartbeats_are_integers(w, monkeypatch):
    from friday.robindevice.store import Device, InMemoryDeviceStore

    store = InMemoryDeviceStore()
    for pid, s7 in (("p1", False), ("p2", True), ("p3", True)):
        st = store.state(pid)
        st.device = Device("h" * 64, 1, 1)
        st.s7_open = s7
    store.state("p4")  # known parent, no device: not counted
    doc = (await _doc(w, monkeypatch, SimpleNamespace(store=store)))
    assert doc["devices_paired"] == 3 and doc["heartbeats_missed"] == 2
    walk(doc)


async def _doc(w, monkeypatch, svc):
    return client(w, monkeypatch, device_service=svc).get(f"/ops-status/{TOKEN}/robin.json").json()


async def test_errors_counter_counts_failing_tick_steps_and_logs_a_fixed_name(w, monkeypatch, caplog):
    opscounts.reset_counters()

    async def boom() -> int:
        raise RuntimeError("secret detail +919800000102")

    monkeypatch.setattr(w.hub.meds, "tick", boom)
    with caplog.at_level("INFO"):
        await w.hub.tick()
    assert opscounts.counter("tick_step_errors") == 1
    assert any(r.getMessage() == "metric robin.tick_step_errors +1" for r in caplog.records)
    assert (await _doc(w, monkeypatch, None))["errors"] == 1
    opscounts.bump("not a real metric +919800000102")  # unknown names are ignored, never logged
    assert opscounts.counter("not a real metric +919800000102") == 0


async def test_digit_walker_rejects_leaks():
    import pytest

    for bad in ({"a": "x" * 30}, {"a": "9800000102"}, {"a": 1.5}, {"a": "98000001021"}, {"a": 1234567890}):
        with pytest.raises(AssertionError):
            walk(bad)
