"""T02: the DB store against a real Postgres. SKIPPED unless FRIDAY_TEST_POSTGRES_URL (or FRIDAY_TEST_PG_URL) is set.

Not run in the build environment that produced this ticket (no Postgres there): the SQL is only verified on SQLite.
It creates and drops only the two ``robin_device_*`` tables, so point it at a throwaway database.
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi import FastAPI

from friday.db.base import Base
from friday.db.session import Database
from friday.robindevice.api import RateLimiter, mount_robin_device
from friday.robindevice.dbmodel import DbDeviceStore, RobinDeviceCodeRow, RobinDeviceStateRow
from friday.robindevice.ports import CONSENT_ITEMS, FakeAlertPort, InMemoryConsent, InMemoryParents
from friday.robindevice.service import DeviceService
from tests.robindevice.conftest import Clock, ist_ms

PG_URL = os.environ.get("FRIDAY_TEST_POSTGRES_URL") or os.environ.get("FRIDAY_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="FRIDAY_TEST_POSTGRES_URL not set (Postgres store test not run)")

B = "/robin/device"


@pytest.fixture
async def pg():
    import friday.db.tables  # noqa: F401

    database = Database(PG_URL)
    tables = [Base.metadata.tables[RobinDeviceStateRow.__tablename__], Base.metadata.tables[RobinDeviceCodeRow.__tablename__]]
    async with database.engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=tables))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    try:
        yield database
    finally:
        async with database.engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=tables))
        await database.dispose()


async def _node(pg, clock, consent, parents):
    service = DeviceService(alerts=FakeAlertPort(), consent=consent, parents=parents, now_ms=clock, brand="Robin", store=DbDeviceStore(pg))
    app = FastAPI()
    mount_robin_device(app, service, RateLimiter())
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await service.store.ensure_loaded()
    return service, client


async def test_pair_restart_and_single_use_code_on_postgres(pg):
    clock, consent, parents = Clock(ist_ms(2026, 9, 9, 14, 0)), InMemoryConsent(), InMemoryParents()
    parents.add("p1", "en")
    consent.grant_all("p1", CONSENT_ITEMS)
    a, ca = await _node(pg, clock, consent, parents)
    code = await a.create_pairing_code("p1")
    body = {"code": code, "app_version": "1.0.0", "os_sdk": 34}
    token = (await ca.post(f"{B}/pair", json=body)).json()["device_token"]
    assert (await ca.post(f"{B}/pair", json=body)).status_code == 404
    b, cb = await _node(pg, clock, consent, parents)  # restart
    st = await b.authenticate(token)
    assert st is not None and st.parent_id == "p1" and st.shadow_start_ms == clock.ms
    r = await cb.post(f"{B}/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={"app_version": "1", "os_sdk": 34, "ts_ms": clock.ms, "roles": {}})
    assert r.status_code == 200
    clock.advance(hours=8)
    assert await b.sweep() == 1
    c, _ = await _node(pg, clock, consent, parents)
    assert await c.sweep() == 0  # already fired and persisted
    await ca.aclose()
    await cb.aclose()
