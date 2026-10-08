"""WhatsApp Cloud API adapter (Meta Graph API).

* ``verify_subscription`` - webhook GET handshake (hub.mode / hub.verify_token).
* ``verify_signature``    - POST ``X-Hub-Signature-256`` = HMAC-SHA256(app secret, body).
* ``parse_webhook``       - payload -> ``InboundMessage``s (text, voice note/audio,
  button / list replies, location, contacts, image, document) + ``StatusUpdate``s.
* ``send``                - text, reply buttons (<=3, title <=20 chars), templates,
  media (audio/image/document by link). Sends exactly what it is given; the
  24h-window and consent decisions are the notifier's.
* ``fetch_media``         - media id -> URL -> bytes (Bearer auth).

Never logs message bodies, tokens or full phone numbers.

Owner: Backend Engineer A.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    Channel,
    InboundMessage,
    LocationPin,
    MediaBlob,
    MessageKind,
    OutboundMessage,
    SendReceipt,
    normalize_phone,
)

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

GRAPH_BASE = "https://graph.facebook.com"
MEDIA_HOSTS = frozenset({"lookaside.fbsbx.com", "graph.facebook.com"})
MAX_MEDIA_BYTES = 16 * 1024 * 1024
ALLOWED_MEDIA_TYPES = ("audio/", "image/", "video/", "application/pdf")
MEDIA_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,128}")
MAX_TEXT = 4096
MAX_INTERACTIVE_BODY = 1024


class StatusUpdate(BaseModel):
    """Delivery status callback for an outbound message."""

    provider_message_id: str
    status: str  # sent | delivered | read | failed
    recipient_phone: str | None = None
    error: str | None = None
    at: datetime | None = None

    @property
    def failed(self) -> bool:
        return self.status == "failed"


class WebhookBatch(BaseModel):
    messages: list[InboundMessage] = []
    statuses: list[StatusUpdate] = []


# ------------------------------------------------------------------------------ verification


def verify_subscription(
    mode: str | None, token: str | None, challenge: str | None, expected_token: str
) -> str | None:
    """Return the challenge to echo if the GET handshake is valid, else None."""
    if (
        mode == "subscribe"
        and token is not None
        and challenge is not None
        and hmac.compare_digest(token, expected_token)
    ):
        return challenge
    return None


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256=") :], expected)


def sign(body: bytes, app_secret: str) -> str:
    """Helper for tests/simulators: the header value Meta would send."""
    return "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------------------ parsing


def _ts(raw: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError):
        return None


def _phone(raw: str | None, default_cc: str) -> str | None:
    if not raw:
        return None
    try:
        return normalize_phone(raw if raw.startswith("+") else "+" + raw, default_cc)
    except ValueError:
        return None


def parse_message(m: dict[str, Any], *, default_cc: str = "+91") -> InboundMessage | None:
    """One ``messages[]`` entry -> InboundMessage (None for unsupported types)."""
    from_phone = _phone(m.get("from"), default_cc)
    if from_phone is None:
        return None
    mtype = m.get("type")
    base: dict[str, Any] = {
        "channel": Channel.WHATSAPP,
        "from_phone": from_phone,
        "provider_message_id": m.get("id"),
        "reply_to_provider_id": (m.get("context") or {}).get("id"),
        "raw": m,
    }
    if (at := _ts(m.get("timestamp"))) is not None:
        base["received_at"] = at
    if mtype == "text":
        return InboundMessage(kind=MessageKind.TEXT, text=(m.get("text") or {}).get("body"), **base)
    if mtype in ("audio", "voice"):
        media = m.get(mtype) or {}
        return InboundMessage(
            kind=MessageKind.VOICE_NOTE,
            media_url=media.get("id"),
            media_mime=media.get("mime_type", "audio/ogg"),
            **base,
        )
    if mtype in ("image", "document", "video", "sticker"):
        media = m.get(mtype) or {}
        kind = MessageKind.DOCUMENT if mtype == "document" else MessageKind.IMAGE
        return InboundMessage(
            kind=kind,
            media_url=media.get("id"),
            media_mime=media.get("mime_type"),
            text=media.get("caption") or media.get("filename"),
            **base,
        )
    if mtype == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return InboundMessage(
            kind=MessageKind.BUTTON_REPLY,
            button_id=reply.get("id"),
            text=reply.get("title"),
            **base,
        )
    if mtype == "button":  # quick-reply button on a template message
        btn = m.get("button") or {}
        return InboundMessage(
            kind=MessageKind.BUTTON_REPLY,
            button_id=btn.get("payload"),
            text=btn.get("text"),
            **base,
        )
    if mtype == "location":
        loc = m.get("location") or {}
        try:
            pin = LocationPin(
                lat=float(loc["latitude"]),
                lng=float(loc["longitude"]),
                name=loc.get("name"),
                address=loc.get("address"),
            )
        except (KeyError, TypeError, ValueError):
            return None
        return InboundMessage(kind=MessageKind.LOCATION, location=pin, **base)
    if mtype == "system":  # number change / identity change (SECURITY-23 freeze)
        system = m.get("system") or {}
        return InboundMessage(kind=MessageKind.SYSTEM, text=system.get("type") or "system", **base)
    if mtype == "contacts":
        contacts = m.get("contacts") or []
        phone = None
        name = None
        if contacts:
            first = contacts[0]
            name = (first.get("name") or {}).get("formatted_name")
            phones = first.get("phones") or []
            if phones:
                raw = phones[0].get("wa_id") or phones[0].get("phone")
                try:
                    phone = normalize_phone(raw, default_cc) if raw else None
                except ValueError:
                    phone = None
        return InboundMessage(kind=MessageKind.CONTACT, contact_phone=phone, text=name, **base)
    return None


def parse_webhook(payload: dict[str, Any], *, default_cc: str = "+91") -> WebhookBatch:
    batch = WebhookBatch()
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for m in value.get("messages") or []:
                msg = parse_message(m, default_cc=default_cc)
                if msg is not None:
                    batch.messages.append(msg)
            for st in value.get("statuses") or []:
                errors = st.get("errors") or []
                batch.statuses.append(
                    StatusUpdate(
                        provider_message_id=st.get("id", ""),
                        status=st.get("status", ""),
                        recipient_phone=_phone(st.get("recipient_id"), default_cc),
                        error=(errors[0].get("title") or str(errors[0].get("code")))
                        if errors
                        else None,
                        at=_ts(st.get("timestamp")),
                    )
                )
    return batch


# ------------------------------------------------------------------------------ sending


def _wa_to(phone: str) -> str:
    return phone.lstrip("+")


def build_payload(
    msg: OutboundMessage, *, templates: dict[str, str], template_language: str
) -> dict[str, Any]:
    """OutboundMessage -> Graph API ``/messages`` JSON body."""
    body: dict[str, Any] = {"messaging_product": "whatsapp", "to": _wa_to(msg.to_phone)}
    if msg.template is not None:
        t = msg.template
        tpl: dict[str, Any] = {
            "name": templates.get(t.key, t.key),
            "language": {"code": t.language or template_language},
        }
        if t.params:
            tpl["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": _template_param(p)} for p in t.params],
                }
            ]
        body |= {"type": "template", "template": tpl}
        return body
    if msg.buttons:
        body |= {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": (msg.text or " ")[:MAX_INTERACTIVE_BODY]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b.id, "title": b.title[:20]}}
                        for b in msg.buttons[:3]
                    ]
                },
            },
        }
        return body
    if msg.media_url:
        mime = msg.media_mime or ""
        mtype = (
            "audio"
            if mime.startswith("audio")
            else "image"
            if mime.startswith("image")
            else "video"
            if mime.startswith("video")
            else "document"
        )
        media: dict[str, Any] = (
            {"link": msg.media_url} if msg.media_url.startswith("http") else {"id": msg.media_url}
        )
        if msg.text and mtype in ("image", "document", "video"):
            media["caption"] = msg.text[:1024]
        body |= {"type": mtype, mtype: media}
        return body
    body |= {"type": "text", "text": {"body": (msg.text or "")[:MAX_TEXT], "preview_url": False}}
    return body


def _template_param(p: str) -> str:
    """Meta rejects template params with newlines/tabs or >4 consecutive spaces."""
    cleaned = " · ".join(part.strip() for part in p.splitlines() if part.strip())
    cleaned = cleaned.replace("\t", " ")
    while "     " in cleaned:
        cleaned = cleaned.replace("     ", "    ")
    return cleaned[:1024] or "-"


class WhatsAppCloudChannel:
    channel = Channel.WHATSAPP

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        app_secret: str | None = None,
        verify_token: str = "",
        api_version: str = "v21.0",
        templates: dict[str, str] | None = None,
        template_language: str = "en",
        default_cc: str = "+91",
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = GRAPH_BASE,
        timeout_s: float = 15.0,
    ) -> None:
        self._token = access_token
        self.phone_number_id = phone_number_id
        self.app_secret = app_secret
        self.verify_token = verify_token
        self.api_version = api_version
        self.templates = templates or {}
        self.template_language = template_language
        self.default_cc = default_cc
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/{api_version}",
            transport=transport,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    # ------------------------------------------------------------------ webhook helpers
    def verify_subscription(
        self, mode: str | None, token: str | None, challenge: str | None
    ) -> str | None:
        return verify_subscription(mode, token, challenge, self.verify_token)

    def verify_signature(self, body: bytes, header: str | None) -> bool:
        if not self.app_secret:
            return False
        return verify_signature(body, header, self.app_secret)

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookBatch:
        return parse_webhook(payload, default_cc=self.default_cc)

    # ------------------------------------------------------------------ MessagingChannel
    async def send(self, msg: OutboundMessage) -> SendReceipt:
        payload = build_payload(
            msg, templates=self.templates, template_language=self.template_language
        )
        try:
            resp = await self._client.post(f"/{self.phone_number_id}/messages", json=payload)
        except httpx.HTTPError as e:
            log.warning(
                "whatsapp send to %s failed: %s", mask_phone(msg.to_phone), type(e).__name__
            )
            return SendReceipt(message_id=msg.id, ok=False, error=f"transport: {type(e).__name__}")
        if resp.status_code >= 400:
            err = _error_text(resp)
            log.warning(
                "whatsapp send to %s rejected (%s): %s",
                mask_phone(msg.to_phone),
                resp.status_code,
                err,
            )
            return SendReceipt(message_id=msg.id, ok=False, error=err)
        data = resp.json()
        wamid = ((data.get("messages") or [{}])[0]).get("id")
        return SendReceipt(message_id=msg.id, provider_message_id=wamid)

    async def fetch_media(self, media_url: str) -> MediaBlob:
        """SECURITY-20: the bearer token only ever goes to Meta hosts over https; size
        and content type are capped."""
        try:
            if media_url.startswith(("http://", "https://")):
                url, mime = media_url, None
            else:
                if not MEDIA_ID_RE.fullmatch(media_url):
                    raise ProviderError("whatsapp", "invalid media id")
                meta = await self._client.get(f"/{media_url}")
                if meta.status_code >= 400:
                    raise ProviderError("whatsapp", f"media lookup failed: {_error_text(meta)}")
                info = meta.json()
                url, mime = str(info.get("url") or ""), info.get("mime_type")
            if not _trusted_media_url(url):
                raise ProviderError("whatsapp", "media URL host not allowed")
            chunks: list[bytes] = []
            size = 0
            async with self._client.stream("GET", url) as blob:
                if blob.status_code >= 400:
                    raise ProviderError("whatsapp", f"media download failed ({blob.status_code})")
                declared = int(blob.headers.get("content-length") or 0)
                if declared > MAX_MEDIA_BYTES:
                    raise ProviderError("whatsapp", "media too large")
                ctype = mime or blob.headers.get("content-type", "application/octet-stream")
                if not ctype.split(";")[0].strip().lower().startswith(ALLOWED_MEDIA_TYPES):
                    raise ProviderError("whatsapp", "media type not allowed")
                async for chunk in blob.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_MEDIA_BYTES:
                        raise ProviderError("whatsapp", "media too large")
                    chunks.append(chunk)
        except httpx.HTTPError as e:
            raise ProviderError(
                "whatsapp", f"media download: {type(e).__name__}", retryable=True
            ) from e
        return MediaBlob(data=b"".join(chunks), mime=ctype.split(";")[0].strip())

    async def aclose(self) -> None:
        await self._client.aclose()


def _trusted_media_url(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "").lower() in MEDIA_HOSTS and not u.username


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return f"{err.get('code', resp.status_code)}: {err.get('message', '')}"[:200]
    except ValueError:
        return f"http {resp.status_code}"


def build_whatsapp_channel(c: Container) -> WhatsAppCloudChannel:
    s = c.settings
    if not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        raise ProviderError("whatsapp", "WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not set")
    return WhatsAppCloudChannel(
        access_token=s.whatsapp_access_token.get_secret_value(),
        phone_number_id=s.whatsapp_phone_number_id,
        app_secret=s.whatsapp_app_secret.get_secret_value() if s.whatsapp_app_secret else None,
        verify_token=s.whatsapp_verify_token.get_secret_value(),
        api_version=s.whatsapp_api_version,
        templates=dict(s.whatsapp_templates),
        template_language=s.whatsapp_template_language,
        default_cc=s.default_country_code,
    )
