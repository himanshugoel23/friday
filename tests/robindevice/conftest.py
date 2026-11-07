"""Fixtures: a service with in-memory fakes for the family ports, a mutable clock, and an ASGI client."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from friday.core.clock import IST
from friday.robindevice.api import RateLimiter, mount_robin_device
from friday.robindevice.ports import (
    CONSENT_ITEMS,
    FakeAlertPort,
    FakeVoiceIntake,
    InMemoryConsent,
    InMemoryParents,
)
from friday.robindevice.replyaudio import ReplyAudioStore
from friday.robindevice.service import DeviceService

MIN = 60_000
HOUR = 60 * MIN


def ist_ms(y: int, mo: int, d: int, h: int = 14, mi: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=IST).timestamp() * 1000)


class Clock:
    def __init__(self, ms: int) -> None:
        self.ms = ms

    def __call__(self) -> int:
        return self.ms

    def advance(self, minutes: float = 0, hours: float = 0) -> None:
        self.ms += int(minutes * MIN + hours * HOUR)


_ids = itertools.count(1)


def ev(type_: str, clock_ms: int, **fields: Any) -> dict[str, Any]:
    return {"id": f"evt-{next(_ids):08d}", "type": type_, "ts_ms": clock_ms, **fields}


@dataclass
class Rig:
    clock: Clock
    alerts: FakeAlertPort
    consent: InMemoryConsent
    parents: InMemoryParents
    voice: FakeVoiceIntake
    service: DeviceService
    app: FastAPI
    client: httpx.AsyncClient

    async def pair(self, parent_id: str = "p1", *, shadow_days: int | None = 0, language: str = "en",
                   grant: bool = True, tags: frozenset[str] | None = None) -> str:
        """Pair a device for a parent and return its bearer token."""
        self.parents.add(parent_id, language, tags)  # type: ignore[arg-type]
        if grant:
            self.consent.grant_all(parent_id, CONSENT_ITEMS)
        if shadow_days is not None:
            self.service.set_policy(parent_id, shadow_days=shadow_days)
        code = await self.service.create_pairing_code(parent_id)
        r = await self.client.post("/robin/device/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
        assert r.status_code == 200, r.text
        return r.json()["device_token"]

    def h(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def rig():
    clock = Clock(ist_ms(2026, 9, 9, 14, 0))
    alerts, consent, parents, voice = FakeAlertPort(), InMemoryConsent(), InMemoryParents(), FakeVoiceIntake()
    service = DeviceService(alerts=alerts, consent=consent, parents=parents, now_ms=clock, voice=voice, brand="Robin", reply_audio=ReplyAudioStore(), public_base_url="https://robin-server.invalid")
    app = FastAPI()
    mount_robin_device(app, service, RateLimiter())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Rig(clock, alerts, consent, parents, voice, service, app, client)
