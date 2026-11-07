# ruff: noqa: E501
"""T06: rate limits shared across replicas (DB rows, no new table), pairing limits (per source, per code, lockout), code strength,
token rotation on re-pair, SOS exempt. Tested with fakes on SQLite."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from friday.robindevice.api import (
    LIMITS,
    PAIR_CODE_ATTEMPTS,
    PAIR_LOCKOUT_BAD,
    PAIR_LOCKOUT_S,
    mount_robin_device,
)
from friday.robindevice.dbmodel import DbDeviceStore
from friday.robindevice.ports import (
    CONSENT_ITEMS,
    FakeAlertPort,
    FakeVoiceIntake,
    InMemoryConsent,
    InMemoryParents,
)
from friday.robindevice.service import DeviceService
from friday.robindevice.store import InMemoryDeviceStore, code_is_strong, new_pair_code
from tests.robindevice.conftest import Clock, ist_ms

B = "/robin/device"


def H(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Node:
    """One replica: its own service, its own store cache, its own HTTP app (default store-backed limiter, as in production)."""

    def __init__(self, clock, parents, consent, store, host: str = "10.0.0.1") -> None:
        self.alerts = FakeAlertPort()
        self.service = DeviceService(alerts=self.alerts, consent=consent, parents=parents, now_ms=clock, voice=FakeVoiceIntake(), brand="Robin", store=store)
        app = FastAPI()
        mount_robin_device(app, self.service)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(host, 1234)), base_url="http://test")

    async def pair_with(self, code: str):
        return await self.client.post(f"{B}/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})


class World:
    def __init__(self, store_factory) -> None:
        self.clock = Clock(ist_ms(2026, 9, 9, 14, 0))
        self.parents, self.consent = InMemoryParents(), InMemoryConsent()
        self.store_factory = store_factory
        self.nodes: list[Node] = []

    async def node(self, host: str = "10.0.0.1") -> Node:
        n = Node(self.clock, self.parents, self.consent, self.store_factory(), host)
        await n.service.store.ensure_loaded()
        self.nodes.append(n)
        return n

    async def pair(self, node: Node, parent_id: str = "p1") -> str:
        self.parents.add(parent_id, "en")
        self.consent.grant_all(parent_id, CONSENT_ITEMS)
        code = await node.service.create_pairing_code(parent_id)
        r = await node.pair_with(code)
        assert r.status_code == 200, r.text
        return r.json()["device_token"]

    async def close(self) -> None:
        for n in self.nodes:
            await n.client.aclose()


@pytest.fixture
async def mem():
    w = World(InMemoryDeviceStore)
    yield w
    await w.close()


@pytest.fixture
async def dbw(db):
    w = World(lambda: DbDeviceStore(db))
    yield w
    await w.close()


# ------------------------------------------------------------------ code strength
def test_new_codes_are_always_strong_and_weak_ones_are_rejected():
    for _ in range(300):
        assert code_is_strong(new_pair_code())
    for weak in ("AAAAAAAA", "ABABABAB", "ABCD", "ABCDEFGHI", "abcdefgh", "ABCDEF0O"):
        assert not code_is_strong(weak)
    assert code_is_strong("ABCDEFGH")


async def test_a_weak_code_is_never_even_looked_up(mem):
    node = await mem.node()
    looked_up: list[str] = []
    orig = node.service.store.take_code

    async def spy(code, now):  # noqa: ANN001, ANN202
        looked_up.append(code)
        return await orig(code, now)

    node.service.store.take_code = spy
    r = await node.pair_with("AAAAAAAA")
    assert r.status_code == 404 and looked_up == []


# ------------------------------------------------------------------ token rotation
async def test_repair_rotates_the_token_and_the_old_one_dies(mem):
    node = await mem.node()
    t1 = await mem.pair(node)
    code = await node.service.create_pairing_code("p1")
    t2 = (await node.pair_with(code)).json()["device_token"]
    assert t1 != t2
    assert (await node.client.get(f"{B}/prompts", headers=H(t1))).status_code == 404
    assert (await node.client.get(f"{B}/prompts", headers=H(t2))).status_code == 200
    assert (await node.pair_with(code)).status_code == 404  # single use


async def test_repair_rotates_the_token_in_the_db_store_too(dbw):
    node = await dbw.node()
    t1 = await dbw.pair(node)
    code = await node.service.create_pairing_code("p1")
    t2 = (await node.pair_with(code)).json()["device_token"]
    assert (await node.client.get(f"{B}/prompts", headers=H(t1))).status_code == 404
    other = await dbw.node()  # a fresh replica sees only the new token
    assert (await other.client.get(f"{B}/prompts", headers=H(t1))).status_code == 404
    assert (await other.client.get(f"{B}/prompts", headers=H(t2))).status_code == 200


# ------------------------------------------------------------------ pairing limits
async def test_lockout_after_n_bad_codes_even_the_right_code_waits_then_recovers(mem):
    node = await mem.node()
    mem.parents.add("p1", "en")
    good = await node.service.create_pairing_code("p1")
    bad = ["BCDFGHJK", "CDFGHJKL", "DFGHJKLM", "FGHJKLMN", "GHJKLMNP"]
    assert len(bad) == PAIR_LOCKOUT_BAD
    for c in bad:
        assert (await node.pair_with(c)).status_code == 404
    assert (await node.pair_with(good)).status_code == 429  # locked out: the right code is not even tried
    mem.clock.advance(minutes=PAIR_LOCKOUT_S / 60 + 1)
    assert (await node.pair_with(good)).status_code == 404  # the lockout ended, but the code (15 min TTL) has expired too
    fresh = await node.service.create_pairing_code("p1")
    assert (await node.pair_with(fresh)).status_code == 200


async def test_lockout_is_per_source(mem):
    a, b = await mem.node("10.0.0.1"), await mem.node("10.0.0.2")
    b.service.store = a.service.store  # same store: shared state, different source address
    for i in range(PAIR_LOCKOUT_BAD):
        await a.pair_with("BCDFGHJK"[: 7] + "LMNPQRST"[i])
    assert (await a.pair_with("BCDFGHJK")).status_code == 429
    assert (await b.pair_with("BCDFGHJK")).status_code == 404  # another source is not locked


async def test_same_wrong_code_is_limited_per_code_across_sources(mem):
    nodes = [await mem.node(f"10.0.1.{i}") for i in range(PAIR_CODE_ATTEMPTS + 2)]
    shared = nodes[0].service.store
    for n in nodes:
        n.service.store = shared
    codes = [(await n.pair_with("BCDFGHJK")).status_code for n in nodes]
    assert codes[:PAIR_CODE_ATTEMPTS] == [404] * PAIR_CODE_ATTEMPTS and codes[-1] == 429


async def test_malformed_pair_bodies_count_toward_the_lockout(mem):
    node = await mem.node()
    for _ in range(PAIR_LOCKOUT_BAD):
        r = await node.client.post(f"{B}/pair", json={"code": "x"})
        assert r.status_code == 422
    r = await node.pair_with("BCDFGHJK")
    assert r.status_code == 429


async def test_pair_limits_are_shared_between_replicas_in_the_db(dbw):
    a, b = await dbw.node(), await dbw.node()  # two replicas, two caches, one database
    for i in range(PAIR_LOCKOUT_BAD):
        assert (await a.pair_with("BCDFGHJK"[:7] + "LMNPQRST"[i])).status_code == 404
    assert (await b.pair_with("CDFGHJKL")).status_code == 429  # replica B knows A's failures


async def test_pair_route_rate_limit_is_shared_between_replicas(dbw):
    a, b = await dbw.node(), await dbw.node()
    limit = LIMITS["pair"][0]
    seen = []
    for i in range(limit + 3):
        n = a if i % 2 == 0 else b
        seen.append((await n.client.post(f"{B}/pair", json={"code": "x"})).status_code)
    # malformed bodies lock the source out first (429) or the route limit does; either way replicas agree
    assert seen[-1] == 429 and 429 not in seen[:3]


# ------------------------------------------------------------------ device limits persisted / shared
async def test_device_limits_shared_across_replicas(dbw):
    a = await dbw.node()
    token = await dbw.pair(a)
    b = await dbw.node()
    limit = LIMITS["erase"][0]  # 3 per minute
    codes = []
    for i in range(limit + 2):
        n = a if i % 2 == 0 else b
        codes.append((await n.client.get(f"{B}/transparency", headers=H(token))).status_code)
    allowed = LIMITS["transparency"][0]
    assert codes.count(200) == min(len(codes), allowed) and allowed >= len(codes)  # under the transparency limit: all fine
    codes = []
    for i in range(LIMITS["prompts"][0] + 4):
        n = a if i % 2 == 0 else b
        codes.append((await n.client.get(f"{B}/prompts", headers=H(token))).status_code)
    assert codes.count(200) == LIMITS["prompts"][0] and codes[-1] == 429


async def test_limit_window_slides_in_the_db(dbw):
    a = await dbw.node()
    token = await dbw.pair(a)
    for _ in range(LIMITS["prompts"][0]):
        assert (await a.client.get(f"{B}/prompts", headers=H(token))).status_code == 200
    assert (await a.client.get(f"{B}/prompts", headers=H(token))).status_code == 429
    dbw.clock.advance(minutes=1.1)
    assert (await a.client.get(f"{B}/prompts", headers=H(token))).status_code == 200


async def test_limits_survive_a_restart(dbw):
    a = await dbw.node()
    token = await dbw.pair(a)
    for _ in range(LIMITS["prompts"][0]):
        await a.client.get(f"{B}/prompts", headers=H(token))
    restarted = await dbw.node()  # new process, empty cache, same DB
    assert (await restarted.client.get(f"{B}/prompts", headers=H(token))).status_code == 429


async def test_other_parents_are_not_affected(mem):
    a = await mem.node()
    t1 = await mem.pair(a, "p1")
    t2 = await mem.pair(a, "p2")
    for _ in range(LIMITS["prompts"][0] + 1):
        await a.client.get(f"{B}/prompts", headers=H(t1))
    assert (await a.client.get(f"{B}/prompts", headers=H(t1))).status_code == 429
    assert (await a.client.get(f"{B}/prompts", headers=H(t2))).status_code == 200


# ------------------------------------------------------------------ SOS exempt
async def test_sos_is_never_rate_limited_in_memory(mem):
    await _sos_never_limited(mem)


async def test_sos_is_never_rate_limited_in_the_db(dbw):
    await _sos_never_limited(dbw)


async def _sos_never_limited(w):
    node = await w.node()
    token = await w.pair(node)
    for _ in range(60):  # far above any limit
        r = await node.client.post(f"{B}/sos", headers=H(token), json={})
        assert r.status_code == 200, r.text
    # and a flood of other calls that IS limited does not block the SOS
    for _ in range(LIMITS["prompts"][0] + 5):
        await node.client.get(f"{B}/prompts", headers=H(token))
    assert (await node.client.post(f"{B}/sos", headers=H(token), json={})).status_code == 200
    assert node.alerts.calls  # alerts were raised
