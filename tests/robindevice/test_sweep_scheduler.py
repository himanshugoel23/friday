# ruff: noqa: E501
"""T02: ``DeviceService.sweep`` runs from ``RobinHub.tick`` so S7 (unreachable) fires without a request. Fakes only, SQLite."""

from __future__ import annotations

import pytest

from friday.core.clock import FakeClock
from friday.core.models import User, UserStatus
from friday.robin.context import Ctx
from friday.robin.gate import AllowAllGate
from friday.robin.ports import FakeParentCaller, FakeParentChannel, RecordingSender
from friday.robin.store import RobinStore
from friday.robin.wiring import RobinHub
from tests.robin.conftest import at
from tests.robindevice.dbrig import B, DbRig


@pytest.fixture
async def rig(db):
    r = DbRig(db)
    yield r
    await r.close()


@pytest.fixture
async def make_hub(container, settings):
    async def build() -> RobinHub:
        clock = FakeClock(at(10))
        ctx = Ctx(store=RobinStore(container.repos.db, clock), clock=clock, send=RecordingSender(), caller=FakeParentCaller(),
                  gate=AllowAllGate(), users=container.repos.users, settings=settings, parent_channel=FakeParentChannel())
        return RobinHub(ctx)

    return build


def s7(node) -> list[dict]:
    return [a for a in node.alerts.of("p1") if a["scenario"] == "S7"]


async def test_tick_runs_the_sweep_and_s7_fires_once(rig, make_hub):
    node = await rig.node()
    await rig.pair(node)
    hub = await make_hub()
    hub.attach_device_sweep(node.service.sweep)
    await hub.tick()
    assert s7(node) == []  # the phone was just seen
    rig.clock.advance(hours=8)  # 22:00 IST, no heartbeat for 8 awake hours
    await hub.tick()
    assert [a["tier"] for a in s7(node)] == ["WATCH"]
    await hub.tick()
    await hub.tick()
    assert len(s7(node)) == 1  # cooldown/dedupe: ticking again does not repeat it


async def test_tick_without_a_device_service_is_unchanged(make_hub):
    hub = await make_hub()
    assert await hub.tick() >= 0  # nothing attached: no error, no sweep


async def test_a_failing_sweep_never_stops_the_other_tick_steps(make_hub):
    hub = await make_hub()
    calls = []

    async def boom() -> int:
        calls.append(1)
        raise RuntimeError("boom")

    hub.attach_device_sweep(boom)
    await hub.tick()
    assert calls == [1]


async def test_s7_fires_once_across_two_services_on_the_same_database(rig, make_hub):
    a = await rig.node()
    token = await rig.pair(a)
    b = await rig.node()  # second process, cache loaded BEFORE the alert fires
    assert b.store.peek("p1") is not None
    hub_a, hub_b = await make_hub(), await make_hub()
    hub_a.attach_device_sweep(a.service.sweep)
    hub_b.attach_device_sweep(b.service.sweep)
    rig.clock.advance(hours=8)
    await hub_a.tick()
    await hub_b.tick()
    await hub_a.tick()
    assert len(s7(a)) + len(s7(b)) == 1
    # the sweep result survived: a restart does not fire it again either
    c = await rig.node()
    hub_c = await make_hub()
    hub_c.attach_device_sweep(c.service.sweep)
    await hub_c.tick()
    assert s7(c) == []
    # the phone comes back: the heartbeat closes S7 (told once) and the state is saved
    hb = {"app_version": "1", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}}
    assert (await c.client.post(f"{B}/heartbeat", headers={"Authorization": f"Bearer {token}"}, json=hb)).status_code == 200
    assert [a["why"] for a in c.alerts.of("p1")][-1] == "phone is active again"


async def test_the_sweep_skips_parents_without_a_device_and_counts_alerts(rig):
    a = await rig.node()
    rig.parents.add("nodev", "en")
    a.service.set_policy("nodev", shadow_days=0)  # a state with no paired phone
    await rig.pair(a)
    rig.clock.advance(hours=8)
    assert await a.service.sweep() == 1
    assert a.alerts.of("nodev") == []


async def test_maybe_mount_wires_the_db_store_and_the_scheduler(container, settings):
    from fastapi import FastAPI

    from friday.robindevice.dbmodel import DbDeviceStore
    from friday.robindevice.wiring import maybe_mount

    settings.robin_enabled = True
    settings.robin_device_enabled = True
    await container.repos.users.add(User(phone="+919800000101", status=UserStatus.ACTIVE))
    service = maybe_mount(FastAPI(), container)
    hub = container.get("robin")
    assert service is not None and isinstance(service.store, DbDeviceStore)
    assert hub._device_sweep == service.sweep  # noqa: SLF001


async def test_switches_default_off(settings):
    from fastapi import FastAPI

    from friday.robindevice.wiring import maybe_mount

    assert settings.robin_device_enabled is False and settings.robin_enabled is False
    assert maybe_mount(FastAPI(), type("C", (), {"settings": settings})()) is None
