"""No SMS provider (beta without MSG91/DLT): the SMS channel is off, nothing is recorded as
sent, WhatsApp carries the message, and a total delivery failure is surfaced loudly."""

from __future__ import annotations

import logging

import pytest

from friday.channels.notifier import NO_CHANNEL, build_notifier
from friday.channels.simulator import SimulatorChannel
from friday.core.models import Business, TemplateRef, User, UserStatus

PHONE = "+919800000001"


@pytest.fixture
async def setup(container, clock):
    await container.db.create_all()
    ch = SimulatorChannel(clock, dict(container.settings.whatsapp_templates))
    container.override("messaging", ch)
    container.override("sms", None)  # what the notifier gets when the sms component is disabled
    user = await container.repos.users.add(
        User(phone=PHONE, status=UserStatus.ACTIVE, last_inbound_at=clock.now())
    )
    n = build_notifier(container)
    assert n.sms is None
    return n, ch, user


async def test_sms_is_refused_and_not_recorded_as_sent(container, setup):
    n, _ch, user = setup
    biz = Business(name="Plumber", phone="+919845000001")
    await container.repos.businesses.upsert(biz)
    tpl = TemplateRef(key="business_enquiry_thanks", params=["Rahul", "Friday"])
    r = await n.business_touch(biz, tpl, user_id=user.id)
    assert not r.ok and r.error == NO_CHANNEL
    r2 = await n.send_sms(PHONE, TemplateRef(key="user_task_update", params=["x"]), user_id=user.id)
    assert not r2.ok and r2.error == NO_CHANNEL


async def test_whatsapp_works_and_total_failure_is_flagged(container, setup, caplog):
    n, ch, user = setup
    assert (await n.notify_user(user.id, "hello")).ok
    ch.fail_phones.add(PHONE)  # WhatsApp is down and there is no SMS to fall back on
    with caplog.at_level(logging.ERROR):
        r = await n.notify_user(user.id, "hello again")
    assert not r.ok
    assert any("undeliverable" in rec.message for rec in caplog.records)
    audit = await container.repos.audit.list_for_user(user.id, limit=20)
    assert any(e.action == "message.undeliverable" for e in audit)
