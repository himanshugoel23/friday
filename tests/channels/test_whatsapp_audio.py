"""WhatsApp media upload + audio-by-id send: request shapes against a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from friday.channels.simulator import SimulatorChannel
from friday.channels.whatsapp import VOICE_NOTE_MIME, WhatsAppCloudChannel, build_payload
from friday.core.interfaces import ProviderError
from friday.core.models import Channel, OutboundMessage

OGG = b"OggS" + b"\x00" * 64


def _channel(handler) -> WhatsAppCloudChannel:  # noqa: ANN001
    return WhatsAppCloudChannel(
        access_token="TOKEN", phone_number_id="PNID", transport=httpx.MockTransport(handler)
    )


async def test_upload_media_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "MEDIA123"})

    ch = _channel(handler)
    media_id = await ch.upload_media(OGG, "audio/ogg; codecs=opus", "voice.ogg")
    assert media_id == "MEDIA123"
    (req,) = seen
    assert req.method == "POST" and req.url.path.endswith("/PNID/media")
    assert req.headers["authorization"] == "Bearer TOKEN"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="messaging_product"' in body and b"whatsapp" in body
    assert b'name="type"\r\n\r\naudio/ogg\r\n' in body  # the parameter after ';' is dropped
    assert b'name="file"; filename="voice.ogg"' in body
    assert OGG in body
    await ch.aclose()


async def test_upload_media_failures_raise_provider_error() -> None:
    def rejected(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": "bad file"}})

    ch = _channel(rejected)
    with pytest.raises(ProviderError):
        await ch.upload_media(OGG, "audio/ogg")
    with pytest.raises(ProviderError):
        await ch.upload_media(b"", "audio/ogg")
    with pytest.raises(ProviderError):
        await ch.upload_media(OGG, "text/html")  # type not allowed, same list as downloads
    with pytest.raises(ProviderError):
        await ch.upload_media(b"x" * (16 * 1024 * 1024 + 1), "audio/ogg")  # size cap
    await ch.aclose()

    def no_id(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "bad id with spaces"})

    ch2 = _channel(no_id)
    with pytest.raises(ProviderError):
        await ch2.upload_media(OGG, "audio/ogg")
    await ch2.aclose()


async def test_upload_transport_error_is_retryable() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    ch = _channel(boom)
    with pytest.raises(ProviderError) as e:
        await ch.upload_media(OGG, "audio/ogg")
    assert e.value.retryable
    await ch.aclose()


async def test_send_audio_by_media_id_payload() -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.AUDIO"}]})

    ch = _channel(handler)
    receipt = await ch.send_audio("+919800000001", "MEDIA123", user_id="u1")
    assert receipt.ok and receipt.provider_message_id == "wamid.AUDIO"
    assert seen == [
        {
            "messaging_product": "whatsapp",
            "to": "919800000001",
            "type": "audio",
            "audio": {"id": "MEDIA123"},
        }
    ]
    bad = await ch.send_audio("+919800000001", "not a valid id!")
    assert not bad.ok and len(seen) == 1  # nothing was sent
    await ch.aclose()


def test_build_payload_audio_by_id_and_link_still_work() -> None:
    by_id = OutboundMessage(
        channel=Channel.WHATSAPP,
        to_phone="+919800000001",
        media_url="M1",
        media_mime=VOICE_NOTE_MIME,
    )
    assert build_payload(by_id, templates={}, template_language="en")["audio"] == {"id": "M1"}
    by_link = by_id.model_copy(update={"media_url": "https://example.com/a.ogg"})
    assert build_payload(by_link, templates={}, template_language="en")["audio"] == {
        "link": "https://example.com/a.ogg"
    }
    text = OutboundMessage(channel=Channel.WHATSAPP, to_phone="+919800000001", text="hi")
    assert build_payload(text, templates={}, template_language="en")["type"] == "text"


async def test_simulator_has_the_same_two_methods() -> None:
    sim = SimulatorChannel()
    media_id = await sim.upload_media(OGG, "audio/ogg")
    receipt = await sim.send_audio("+919800000001", media_id)
    assert receipt.ok
    last = sim.last_to("+919800000001")
    assert last is not None and last.media_url == media_id
    assert (await sim.fetch_media(media_id)).data == OGG
