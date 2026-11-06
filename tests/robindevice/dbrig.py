"""Test helper: device services on a shared SQLite DB, so 'a restart' = a new service and a new store on the same DB."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from friday.robindevice.api import RateLimiter, mount_robin_device
from friday.robindevice.dbmodel import DbDeviceStore
from friday.robindevice.ports import (
    CONSENT_ITEMS,
    FakeAlertPort,
    FakeVoiceIntake,
    InMemoryConsent,
    InMemoryParents,
)
from friday.robindevice.service import DeviceService
from tests.robindevice.conftest import Clock, ist_ms

B = "/robin/device"


@dataclass
class Node:
    """One 'process': a service, its own store cache and its own HTTP app."""

    service: DeviceService
    store: DbDeviceStore
    alerts: FakeAlertPort
    client: httpx.AsyncClient


class DbRig:
    def __init__(self, db) -> None:  # noqa: ANN001
        self.db = db
        self.clock = Clock(ist_ms(2026, 9, 9, 14, 0))
        self.consent, self.parents = InMemoryConsent(), InMemoryParents()
        self.clients: list[httpx.AsyncClient] = []

    async def node(self) -> Node:
        """A fresh service + store (empty cache) over the same database, as after a restart."""
        alerts = FakeAlertPort()
        store = DbDeviceStore(self.db)
        service = DeviceService(alerts=alerts, consent=self.consent, parents=self.parents, now_ms=self.clock,
                                voice=FakeVoiceIntake(), brand="Robin", store=store)
        app = FastAPI()
        mount_robin_device(app, service, RateLimiter())
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.clients.append(client)
        await store.ensure_loaded()
        return Node(service, store, alerts, client)

    async def pair(self, node: Node, parent_id: str = "p1", *, shadow_days: int | None = 0) -> str:
        self.parents.add(parent_id, "en")
        self.consent.grant_all(parent_id, CONSENT_ITEMS)
        if shadow_days is not None:
            node.service.set_policy(parent_id, shadow_days=shadow_days)
        code = await node.service.create_pairing_code(parent_id)
        r = await node.client.post(f"{B}/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
        assert r.status_code == 200, r.text
        return r.json()["device_token"]

    async def close(self) -> None:
        for c in self.clients:
            await c.aclose()
