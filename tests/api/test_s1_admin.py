"""S-1 (idempotent fast-ack webhook), S-4 (outbox), SECURITY-28, NP-5."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from friday.api.admin import admin_token
from friday.api.app import create_app
from friday.channels.notifier import Notifier
from friday.channels.whatsapp import sign
from friday.core.models import (
    Channel,
    FridayNumber,
    NumberOutcome,
    OutboundMessage,
    User,
    UserStatus,
)
from friday.core.scale import MemoryJobQueue, QueueOutbox
from tests.api.conftest import ADMIN
from tests.api.test_app import _wa_payload


@pytest.fixture
def client(wired):
    app = create_app(wired, background=False, fast_pin_hash=True)
    with TestClient(app) as c:
        yield c


def _post(client, wired, text: str, mid: str):
    wired.settings.whatsapp_app_secret = SecretStr("appsecret")
    body = json.dumps(_wa_payload(text, mid=mid)).encode()
    return client.post(
        "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": sign(body, "appsecret")}
    )


def test_duplicate_deliveries_are_processed_once(wired, client):
    assert _post(client, wired, "hi", "wamid.A").json()["messages"] == 1
    again = _post(client, wired, "hi", "wamid.A")
    assert again.status_code == 200 and again.json()["messages"] == 0  # acked, skipped
    assert len(wired.messaging.messages_to(ADMIN)) == 1
    assert _post(client, wired, "Rahul", "wamid.B").json()["messages"] == 1
    assert len(wired.messaging.messages_to(ADMIN)) == 2


async def test_webhook_enqueues_durably_before_processing(wired):
    """The ack path only stores + enqueues; a job exists until a worker drains it."""
    app = create_app(wired, background=False, fast_pin_hash=True)
    rt = app.state.runtime
    queue = wired.get("job_queue")
    from friday.core.models import InboundMessage

    msg = InboundMessage(channel="simulator", from_phone=ADMIN, text="hi", provider_message_id="w1")
    assert await rt.accept_inbound(msg)
    assert await queue.depth() == 1 and wired.messaging.messages_to(ADMIN) == []
    assert not await rt.accept_inbound(msg)  # duplicate
    assert await rt.drain() == 1
    assert wired.messaging.messages_to(ADMIN)  # processed by the worker
    assert await queue.depth() == 0


def _acli(app):
    import httpx

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_health_is_minimal_and_sim_absent_in_live(wired):
    app = create_app(wired, background=False)
    async with _acli(app) as cl:
        assert (await cl.get("/health")).json() == {"status": "ok"}
        assert (
            await cl.post("/sim/messages", json={"phone": ADMIN, "text": "x"})
        ).status_code == 200
    wired.settings = wired.settings.model_copy(update={"mode": "live"})
    paths = set(create_app(wired, background=False).openapi()["paths"])
    assert not any(p.startswith("/sim") for p in paths)


async def test_admin_numbers_requires_token(wired):
    app = create_app(wired, background=False)
    async with _acli(app) as cl:
        assert (await cl.get("/admin/numbers")).status_code == 401
        assert (
            await cl.get("/admin/numbers", headers={"Authorization": "Bearer nope"})
        ).status_code == 401
        h = {"Authorization": f"Bearer {admin_token(wired.settings)}"}
        n = FridayNumber(phone="+918000000001", provider="simulator", circle="KA")
        await wired.repos.numbers.upsert(n)
        await wired.repos.numbers.add_outcome(n.phone, NumberOutcome.ANSWERED)
        await wired.repos.numbers.assign("+919845000001", n.phone)
        body = (await cl.get("/admin/numbers", headers=h)).json()
        row = body["numbers"][0]
        assert row["calls_24h"] == 1 and row["businesses"] == 1 and row["status"] == "warming"
        assert "+918000000001" not in json.dumps(body)  # masked
        assert body["totals"]["count"] == 1
        assert (await cl.get("/admin/health", headers=h)).json()["components"]["repos"] is True


async def test_admin_disabled_in_live_without_token(wired, monkeypatch):
    monkeypatch.delenv("FRIDAY_ADMIN_TOKEN", raising=False)
    wired.settings = wired.settings.model_copy(update={"mode": "live"})
    app = create_app(wired, background=False)
    async with _acli(app) as cl:
        assert (await cl.get("/admin/numbers")).status_code == 404
        monkeypatch.setenv("FRIDAY_ADMIN_TOKEN", "ops-secret")
        assert (await cl.get("/admin/numbers")).status_code == 401
        ok = await cl.get("/admin/numbers", headers={"Authorization": "Bearer ops-secret"})
        assert ok.status_code == 200


async def test_outbox_delivery_survives_consumer_crash(wired, clock):
    """S-4: kill the consumer mid-send (lease expires) -> exactly one delivery."""
    repos = wired.repos
    user = await repos.users.add(
        User(phone="+919800000777", status=UserStatus.ACTIVE, last_inbound_at=clock.now())
    )
    queue = MemoryJobQueue(clock)
    notifier = Notifier(
        settings=wired.settings,
        clock=clock,
        bus=wired.bus,
        repos=repos,
        messaging=wired.messaging,
        sms=wired.get("sms"),
        outbox=QueueOutbox(queue),
        durable=True,
    )
    r = await notifier.notify_user(user.id, "Booked!")
    assert r.ok and wired.messaging.messages_to(user.phone) == []  # only queued
    assert await queue.depth() == 1
    (job,) = await queue.claim("worker-1", lease_s=30)
    # worker-1 crashes before doing anything: lease expires, another worker takes over
    clock.advance(31)
    (job,) = await queue.claim("worker-2")
    await notifier.handle_job(job)
    await queue.ack(job.id)
    # crash AFTER sending but before ack: redelivery must not send again
    await notifier.handle_job(job)
    assert [m.text for m in wired.messaging.messages_to(user.phone)] == ["Booked!"]
    # the same logical message can't be enqueued twice either
    msg = OutboundMessage(
        channel=Channel.SIMULATOR, to_phone=user.phone, user_id=user.id, text="dup"
    )
    await notifier.send(msg)
    await notifier.send(msg)
    assert await queue.depth() == 1
    # failing channel -> job error (so the queue retries), not a silent drop
    wired.messaging.fail_phones.add(user.phone)
    (j2,) = await queue.claim("worker-2")
    with pytest.raises(RuntimeError):
        await notifier.handle_job(j2)
    wired.messaging.fail_phones.clear()
    await notifier.handle_job(j2)
    assert [m.text for m in wired.messaging.messages_to(user.phone)] == ["Booked!", "dup"]
