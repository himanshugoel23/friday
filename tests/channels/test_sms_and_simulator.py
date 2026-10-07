from __future__ import annotations

import json

import httpx

from friday.channels.simulator import SimulatorChannel, build_simulator_channel
from friday.channels.sms import MSG91SMS, build_fake_sms
from friday.core.interfaces import MessagingChannel, SMSProvider
from friday.core.models import (
    Channel,
    MessageKind,
    OutboundMessage,
    ReplyButton,
    TemplateRef,
)


async def test_fake_sms_records_and_rejects_unknown_templates(container):
    sms = build_fake_sms(container)
    assert isinstance(sms, SMSProvider)
    r = await sms.send_template("+919800000001", TemplateRef(key="user_task_update", params=["x"]))
    assert r.ok and sms.sent[0].dlt_template_id == "DLT_TPL_USER_UPDATE"
    bad = await sms.send_template("+919800000001", TemplateRef(key="free_form"))
    assert not bad.ok


async def test_msg91_flow_payload():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append((req.headers.get("authkey"), json.loads(req.content)))
        return httpx.Response(200, json={"type": "success", "message": "req-1"})

    sms = MSG91SMS(
        auth_key="KEY",
        sender_id="FRIDAY",
        templates={"business_booking_confirmed": "TPL1"},
        transport=httpx.MockTransport(handler),
    )
    r = await sms.send_template(
        "+919800000001", TemplateRef(key="business_booking_confirmed", params=["Haircut", "Sat"])
    )
    assert r.ok and r.provider_message_id == "req-1"
    key, body = bodies[0]
    assert key == "KEY" and body["template_id"] == "TPL1"
    assert body["recipients"][0] == {"mobiles": "919800000001", "var1": "Haircut", "var2": "Sat"}
    await sms.aclose()

    def failing(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"type": "error", "message": "invalid template"})

    sms2 = MSG91SMS(
        auth_key="K",
        sender_id="F",
        templates={"business_booking_confirmed": "T"},
        transport=httpx.MockTransport(failing),
    )
    r2 = await sms2.send_template("+919800000001", TemplateRef(key="business_booking_confirmed"))
    assert not r2.ok and "invalid" in r2.error
    await sms2.aclose()


async def test_simulator_channel_send_render_and_parse(container):
    ch = build_simulator_channel(container)
    assert isinstance(ch, SimulatorChannel) and isinstance(ch, MessagingChannel)
    phone = "+919800000001"
    got = []
    ch.subscribe(got.append)
    msg = OutboundMessage(
        channel=Channel.SIMULATOR,
        to_phone=phone,
        text="4pm or 6pm?",
        buttons=[ReplyButton(id="q:x:0", title="4pm"), ReplyButton(id="q:x:1", title="6pm")],
    )
    r = await ch.send(msg)
    assert r.ok and got == [msg]
    assert "2) 6pm" in ch.render(msg)
    assert await ch.wait_for(phone, 1) == [msg]

    tap = ch.make_inbound(phone, "2")
    assert tap.kind == MessageKind.BUTTON_REPLY and tap.button_id == "q:x:1"
    pin = ch.make_inbound(phone, "/pin 12.97, 77.64")
    assert pin.kind == MessageKind.LOCATION and pin.location.lng == 77.64
    voice = ch.make_inbound(phone, "/voice kal haircut book karo")
    assert voice.kind == MessageKind.VOICE_NOTE
    assert (await ch.fetch_media(voice.media_url)).data == b"kal haircut book karo"
    contact = ch.make_inbound(phone, "/contact 98111 11111")
    assert contact.contact_phone == "+919811111111"
    assert ch.make_inbound(phone, "/doc quote.pdf").kind == MessageKind.DOCUMENT
    assert ch.make_inbound("98000 00002", "hello").from_phone == "+919800000002"

    tpl = OutboundMessage(
        channel=Channel.SIMULATOR, to_phone=phone, template=TemplateRef(key="nudge", params=["a"])
    )
    assert "friday_nudge_v1" in ch.render(tpl)
    ch.fail_phones.add(phone)
    assert not (await ch.send(tpl)).ok
