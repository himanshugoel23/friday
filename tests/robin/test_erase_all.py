# ruff: noqa: E501
"""T03: 'delete everything' reaches the family rows AND the device package (rows, pairing codes, token cache, live analyzers).

The CHILD (admin) owns the erase. ``FamilyService.erase`` and ``DataPurger.purge_user`` are both driven through a full family
with a paired phone, signals, an incident, a medicine and audit rows. Tested with fakes on SQLite; nothing is dialled.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from friday.robin import ports as robin_ports
from friday.robin.alerts import RobinAlert
from friday.robin.medicine import Medicine
from friday.robin.models import Tier
from friday.robin.wiring import _DeviceAlerts, _DeviceConsent, _DeviceParents
from friday.robindevice.api import RateLimiter, mount_robin_device
from friday.robindevice.dbmodel import DbDeviceStore
from friday.robindevice.service import DeviceService
from tests.robindevice.conftest import ev

B = "/robin/device"
TABLES = ("robin_families", "robin_members", "robin_consents", "robin_records", "robin_device_states", "robin_device_codes")


class Phone:
    """A paired device on the same database as the family, wired through the REAL family-backed ports."""

    def __init__(self, w, db) -> None:
        self.w = w
        self.store = DbDeviceStore(db)
        self.service = DeviceService(
            alerts=_DeviceAlerts(w.hub), consent=_DeviceConsent(w.hub), parents=_DeviceParents(w.hub),
            now_ms=lambda: int(w.clock.now().timestamp() * 1000), brand="Robin", store=self.store,
        )
        app = FastAPI()
        mount_robin_device(app, self.service, RateLimiter())
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.token = ""

    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def pair(self, parent_id: str) -> None:
        await self.store.ensure_loaded()
        self.service.set_policy(parent_id, shadow_days=0)
        code = await self.service.create_pairing_code(parent_id)
        r = await self.client.post(f"{B}/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
        assert r.status_code == 200, r.text
        self.token = r.json()["device_token"]


async def counts(db, tables=TABLES) -> dict[str, int]:
    out = {}
    async with db.session() as s:
        for t in tables:
            out[t] = (await s.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar_one()  # noqa: S608 - fixed names
    return out


@pytest.fixture
async def full(w, db):
    """A family with a paired phone, signals, a pairing code still unused, a live analyzer, an incident, a medicine and audit rows."""
    fam, parent = await w.family(second=True)
    for item in ("device_signals", "payment_alerts", "call_listening"):
        assert await w.hub.fam.admin_consent(fam, item) == "given"
    phone = Phone(w, db)
    await phone.pair(parent.id)
    ms = int(w.clock.now().timestamp() * 1000)
    r = await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": [ev("camera_in_use_start", ms)]})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    await phone.service.feed_call_turn(parent.id, "call-1", "caller", "main police se bol raha hoon paise bhejo abhi", 1.0)
    assert any(k[0] == parent.id for k in phone.service._analyzers)
    await phone.service.create_pairing_code(parent.id)  # an unused code stays behind
    await w.hub.meds.add(fam, Medicine(name="Metformin", dose_text="500 mg", times=["09:00"], strips=2))
    res = await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S1", "unknown caller 22 minutes + camera on"))
    assert res.accepted
    before = await counts(db)
    assert all(before[t] > 0 for t in TABLES), before
    robin_ports.register_erase_hook("robindevice", phone.service.erase_parent)
    yield w, db, fam, parent, phone
    robin_ports.unregister_erase_hook("robindevice")
    await phone.client.aclose()


async def test_family_erase_removes_every_robin_and_device_row_and_kills_the_token(full):
    w, db, fam, parent, phone = full
    sent_before = len(w.sender.sent)
    audits: list[tuple] = []

    async def sink(action, user_id, *, actor, source, counts):
        audits.append((action, user_id, actor, source, counts))

    w.ctx.audit_sink = sink
    out = await w.hub.fam.erase(fam, tell_child=True)
    assert all(v == 0 for v in (await counts(db)).values())  # zero rows everywhere
    assert out["robindevice.state"] == 1 and out["robindevice.analyzers"] == 1 and out["robin_records"] > 0
    # the live phone is dead: token rejected (the API answers a plain 404 for any bad token, by design), cache empty, analyzers dropped
    assert (await phone.client.post(f"{B}/heartbeat", headers=phone.h(), json={"app_version": "1.0.0", "os_sdk": 34, "roles": {}, "battery_low": False})).status_code == 404
    assert (await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": []})).status_code == 404
    assert phone.service._analyzers == {} and phone.store.parent_ids() == []
    # the child is audited (counts only, no personal data) and told exactly once
    assert len(audits) == 1 and audits[0][0] == "robin.family_erased" and audits[0][2:4] == ("admin_on_behalf", "admin_chat")
    assert "Papa" not in repr(audits) and "+91" not in repr(audits)
    told = w.sender.sent[sent_before:]
    assert len(told) == 1 and "Deleted everything" in told[0].text
    # a second erase is harmless
    await w.hub.fam.erase(fam)
    assert all(v == 0 for v in (await counts(db)).values())


async def test_the_chat_command_delete_tells_the_child_once_and_erases_the_device(full):
    w, db, fam, parent, phone = full
    from friday.core.models import Channel, InboundMessage, MessageKind
    from tests.robin.test_commands import CHILD_PHONE

    n = len(w.sender.sent)
    for body in ("delete everything for my parent", "DELETE"):
        msg = InboundMessage(channel=Channel.SIMULATOR, from_phone=CHILD_PHONE, text=body, kind=MessageKind.TEXT)
        assert await w.hub.handle(w.child_user, msg)
    told = w.sender.sent[n:]
    assert sum("Deleted everything" in m.text for m in told) == 1  # the chat reply is the one telling; erase() adds none
    assert all(v == 0 for v in (await counts(db)).values())
    assert phone.service._analyzers == {} and (await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": []})).status_code == 404


async def test_purge_user_removes_every_row_even_when_the_device_package_is_off(full):
    w, db, fam, parent, phone = full
    robin_ports.unregister_erase_hook("robindevice")  # device API not mounted in this process: rows must still go
    from friday.db.repositories.purge import DataPurger

    out = await DataPurger(db, w.clock).purge_user(w.child_user.id)
    assert all(v == 0 for v in (await counts(db)).values())
    assert out["robin_device_states"] == 1 and out["robin_device_codes"] == 1
    # the token cannot come back from the DB either (a fresh process would also say 401)
    fresh = DbDeviceStore(db)
    assert await fresh.parent_for_token(phone.token) is None


async def test_purge_user_also_drops_the_live_analyzers_and_cache_through_the_hook(full):
    w, db, fam, parent, phone = full
    from friday.db.repositories.purge import DataPurger

    await DataPurger(db, w.clock).purge_user(w.child_user.id)
    assert phone.service._analyzers == {} and phone.store.parent_ids() == []
    assert (await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": []})).status_code == 404


async def test_another_family_is_untouched(full, container):
    w, db, fam, parent, phone = full
    from friday.core.models import User, UserStatus

    other = await container.repos.users.add(User(phone="+919800000909", status=UserStatus.ACTIVE))
    f2 = await w.hub.fam.create_family(other, parent_label="Mummy", child_name="Ravi")
    p2 = await w.hub.fam.add_parent(f2, "+919800000910")
    phone2 = Phone(w, db)
    await w.hub.fam.admin_consent(f2, "device_signals")
    await phone2.pair(p2.id)
    await w.hub.fam.erase(fam)
    c = await counts(db)
    assert c["robin_families"] == 1 and c["robin_device_states"] == 1
    assert (await phone2.client.post(f"{B}/signals", headers=phone2.h(), json={"events": []})).status_code == 200
    await phone2.client.aclose()


async def test_a_failing_hook_never_blocks_the_erase(full):
    w, db, fam, parent, phone = full

    async def boom(pid):
        raise RuntimeError("down")

    robin_ports.register_erase_hook("zz_broken", boom)
    try:
        await w.hub.fam.erase(fam)
    finally:
        robin_ports.unregister_erase_hook("zz_broken")
    assert all(v == 0 for v in (await counts(db)).values())
