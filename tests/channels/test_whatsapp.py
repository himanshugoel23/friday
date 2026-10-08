"""WhatsApp Cloud adapter: fixture payloads, signature, sending via MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from friday.channels.whatsapp import (
    WhatsAppCloudChannel,
    build_payload,
    parse_webhook,
    sign,
    verify_signature,
    verify_subscription,
)
from friday.core.interfaces import MessagingChannel, ProviderError
from friday.core.models import (
    Channel,
    MessageKind,
    OutboundMessage,
    ReplyButton,
    TemplateRef,
)


def _envelope(*messages, statuses=()):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "PNID"},
                            "messages": list(messages),
                            "statuses": list(statuses),
                        },
                    }
                ],
            }
        ],
    }


BASE = {"from": "919800000001", "timestamp": "1767600000"}


def test_parse_all_message_types():
    payload = _envelope(
        {**BASE, "id": "w1", "type": "text", "text": {"body": "book haircut"}},
        {**BASE, "id": "w2", "type": "audio", "audio": {"id": "MEDIA1", "mime_type": "audio/ogg"}},
        {
            **BASE,
            "id": "w3",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "q:abc:1", "title": "6pm"},
            },
            "context": {"id": "wout"},
        },
        {
            **BASE,
            "id": "w4",
            "type": "location",
            "location": {"latitude": 12.97, "longitude": 77.64, "name": "Home"},
        },
        {
            **BASE,
            "id": "w5",
            "type": "contacts",
            "contacts": [
                {"name": {"formatted_name": "Ramesh"}, "phones": [{"phone": "+91 98111 11111"}]}
            ],
        },
        {
            **BASE,
            "id": "w6",
            "type": "image",
            "image": {"id": "IMG", "mime_type": "image/jpeg", "caption": "menu"},
        },
        {
            **BASE,
            "id": "w7",
            "type": "document",
            "document": {"id": "DOC", "mime_type": "application/pdf", "filename": "quote.pdf"},
        },
        {**BASE, "id": "w8", "type": "button", "button": {"payload": "n:nid:yes", "text": "Yes"}},
        {**BASE, "id": "w9", "type": "unsupported"},
        statuses=[
            {
                "id": "wout",
                "status": "failed",
                "recipient_id": "919800000001",
                "errors": [{"code": 131047, "title": "Re-engagement message"}],
            }
        ],
    )
    batch = parse_webhook(payload)
    kinds = [m.kind for m in batch.messages]
    assert kinds == [
        MessageKind.TEXT,
        MessageKind.VOICE_NOTE,
        MessageKind.BUTTON_REPLY,
        MessageKind.LOCATION,
        MessageKind.CONTACT,
        MessageKind.IMAGE,
        MessageKind.DOCUMENT,
        MessageKind.BUTTON_REPLY,
    ]
    m = batch.messages
    assert m[0].from_phone == "+919800000001" and m[0].text == "book haircut"
    assert m[0].channel == Channel.WHATSAPP and m[0].provider_message_id == "w1"
    assert m[1].media_url == "MEDIA1"
    assert m[2].button_id == "q:abc:1" and m[2].reply_to_provider_id == "wout"
    assert m[3].location.lat == 12.97
    assert m[4].contact_phone == "+919811111111"
    assert m[5].text == "menu" and m[6].media_mime == "application/pdf"
    assert m[7].button_id == "n:nid:yes"
    assert batch.statuses[0].failed and "Re-engagement" in batch.statuses[0].error


def test_signature_and_subscription():
    body = json.dumps(_envelope()).encode()
    header = sign(body, "s3cret")
    assert verify_signature(body, header, "s3cret")
    assert not verify_signature(body, header, "other")
    assert not verify_signature(body + b" ", header, "s3cret")
    assert not verify_signature(body, None, "s3cret")
    assert verify_subscription("subscribe", "tok", "123", "tok") == "123"
    assert verify_subscription("subscribe", "bad", "123", "tok") is None


def test_build_payloads():
    tpls = {"task_update": "friday_task_update_v1"}
    text = OutboundMessage(channel=Channel.WHATSAPP, to_phone="+919800000001", text="hi")
    assert build_payload(text, templates=tpls, template_language="en") == {
        "messaging_product": "whatsapp",
        "to": "919800000001",
        "type": "text",
        "text": {"body": "hi", "preview_url": False},
    }
    btn = text.model_copy(
        update={
            "buttons": [
                ReplyButton(id="a:t:yes", title="Yes"),
                ReplyButton(id="a:t:no", title="No"),
            ]
        }
    )
    p = build_payload(btn, templates=tpls, template_language="en")
    assert p["type"] == "interactive"
    assert [b["reply"]["id"] for b in p["interactive"]["action"]["buttons"]] == [
        "a:t:yes",
        "a:t:no",
    ]
    tpl = text.model_copy(
        update={"text": None, "template": TemplateRef(key="task_update", params=["line1\nline2"])}
    )
    p = build_payload(tpl, templates=tpls, template_language="en")
    assert p["template"]["name"] == "friday_task_update_v1"
    assert "\n" not in p["template"]["components"][0]["parameters"][0]["text"]
    media = text.model_copy(update={"media_url": "https://x/rec.mp3", "media_mime": "audio/mpeg"})
    assert build_payload(media, templates=tpls, template_language="en")["type"] == "audio"


async def test_send_and_fetch_media_with_mock_transport():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/messages"):
            body = json.loads(request.content)
            if body["to"] == "910000000000":
                return httpx.Response(
                    400, json={"error": {"code": 131026, "message": "undeliverable"}}
                )
            return httpx.Response(200, json={"messages": [{"id": "wamid.OK"}]})
        if request.url.path.endswith("/MEDIA1"):
            return httpx.Response(
                200, json={"url": "https://lookaside.fbsbx.com/m1", "mime_type": "audio/ogg"}
            )
        if request.url.host == "lookaside.fbsbx.com":
            return httpx.Response(200, content=b"OGG", headers={"content-type": "audio/ogg"})
        return httpx.Response(404)

    ch = WhatsAppCloudChannel(
        access_token="TOKEN",
        phone_number_id="PNID",
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(ch, MessagingChannel)
    msg = OutboundMessage(channel=Channel.WHATSAPP, to_phone="+919800000001", text="hello")
    r = await ch.send(msg)
    assert r.ok and r.provider_message_id == "wamid.OK" and r.message_id == msg.id
    assert seen[0].headers["authorization"] == "Bearer TOKEN"
    assert seen[0].url.path == "/v21.0/PNID/messages"
    bad = await ch.send(msg.model_copy(update={"to_phone": "+910000000000"}))
    assert not bad.ok and "131026" in bad.error
    blob = await ch.fetch_media("MEDIA1")
    assert blob.data == b"OGG" and blob.mime == "audio/ogg"
    with pytest.raises(ProviderError):
        await ch.fetch_media("MISSING")
    await ch.aclose()


async def test_fetch_media_refuses_foreign_hosts_and_big_files():
    """SECURITY-20: the bearer token never goes to other hosts; size/type capped."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/EVIL"):
            return httpx.Response(200, json={"url": "https://attacker.example/x", "mime_type": "audio/ogg"})
        if request.url.path.endswith("/BIG"):
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/big", "mime_type": "audio/ogg"})
        if request.url.path.endswith("/HTML"):
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/h"})
        if request.url.path == "/big":
            return httpx.Response(200, content=b"x" * 10, headers={"content-length": str(17 * 1024 * 1024)})
        if request.url.path == "/h":
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    ch = WhatsAppCloudChannel(access_token="TOKEN", phone_number_id="PNID", transport=httpx.MockTransport(handler))
    for ref in ("EVIL", "http://lookaside.fbsbx.com/x", "https://attacker.example/x", "BIG", "HTML", "../../x"):
        with pytest.raises(ProviderError):
            await ch.fetch_media(ref)
    assert all(r.url.host != "attacker.example" for r in seen)
    await ch.aclose()
