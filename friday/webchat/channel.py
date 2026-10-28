# ruff: noqa: E501
"""The web channel: implements the same outbound port as the WhatsApp channel (``MessagingChannel``:
``send``, ``fetch_media``, ``upload_media``, ``send_audio``) but delivers to a tester's web chat.

* No network at all: this class never talks to Meta or any other server.
* A message is delivered only to an ACTIVE tester's own number; any other recipient is refused.
* Outbound messages go through the normal Notifier, so they are logged in ``repos.messages`` exactly
  like WhatsApp ones (that is what "what do you remember", "delete everything" and purge work on).
  The page copy kept here is in memory only.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    Channel,
    InboundMessage,
    MediaBlob,
    OutboundMessage,
    SendReceipt,
)
from friday.webchat.registry import Registry

log = get_logger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
MAX_ENTRIES = 400
MAX_MEDIA = 40
MAX_MEDIA_BYTES = 8 * 1024 * 1024
WEB_MEDIA_PREFIX = "web-media:"
_MEDIA_IDS = itertools.count(1)  # unique across testers


class ChatStore:
    """One tester's chat as the page shows it (in memory)."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now
        self.entries: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
        self.media: dict[str, MediaBlob] = {}
        self._seq = itertools.count(1)

    def _stamp(self) -> dict[str, Any]:
        t = self._now()
        return {
            "seq": next(self._seq),
            "at": t.isoformat(),
            "time": t.astimezone(IST).strftime("%d %b %H:%M"),
        }

    def add_in(self, msg: InboundMessage, label: str) -> dict[str, Any]:
        entry = {
            **self._stamp(),
            "dir": "in",
            "id": msg.id,
            "kind": msg.kind.value,
            "text": msg.text if msg.kind.value in ("text", "button_reply") else None,
            "label": label,
            "button_id": msg.button_id,
            "location": msg.location.model_dump() if msg.location else None,
            "contact_phone": None,
            "status": "sent",
            "mark": None,
        }
        self.entries.append(entry)
        return entry

    def add_out(self, msg: OutboundMessage, provider_id: str) -> dict[str, Any]:
        text = msg.text
        if text is None and msg.template is not None:
            text = msg.template.params[-1] if msg.template.params else ""  # a template body, as text
        lst = None
        if msg.list_menu is not None:
            lst = {
                "title": "",
                "button": msg.list_menu.button,
                "sections": [
                    {
                        "title": msg.list_menu.section or "",
                        "items": [
                            {"id": r.id, "title": r.title, "description": r.description}
                            for r in msg.list_menu.rows
                        ],
                    }
                ],
            }
        entry = {
            **self._stamp(),
            "dir": "out",
            "id": msg.id,
            "provider_id": provider_id,
            "text": text,
            "buttons": [{"id": b.id, "title": b.title} for b in msg.buttons],
            "list": lst,
            "template": None,
            "media": {"url": msg.media_url, "mime": msg.media_mime} if msg.media_url else None,
            "mark": None,
        }
        for e in self.entries:  # Friday answered: everything the tester sent before is read
            if e["dir"] == "in" and e["status"] != "read":
                e["status"] = "read"
        self.entries.append(entry)
        return entry

    def out_count(self) -> int:
        return sum(1 for e in self.entries if e["dir"] == "out")

    def find_out(self, message_id: str) -> dict[str, Any] | None:
        return next((e for e in reversed(self.entries) if e["dir"] == "out" and e["id"] == message_id), None)

    def put_media(self, data: bytes, mime: str, filename: str | None = None) -> str:
        if len(self.media) >= MAX_MEDIA:
            self.media.pop(next(iter(self.media)))
        media_id = f"{WEB_MEDIA_PREFIX}{next(_MEDIA_IDS)}"
        self.media[media_id] = MediaBlob(data=data, mime=mime, filename=filename)
        return media_id

    def clear(self) -> None:
        self.entries.clear()
        self.media.clear()

    def public_entries(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in e.items() if k != "provider_id"} for e in self.entries]


class WebChannel:
    # Stored and treated as a WhatsApp-style chat by the notifier, window rules and the pipeline;
    # the class (not this value) is what says "web": ``is_web``.
    channel = Channel.WHATSAPP
    is_web = True

    def __init__(self, registry: Registry, now: Callable[[], datetime] | None = None) -> None:
        self.registry = registry
        self._now = now or (lambda: datetime.now(UTC))
        self.stores: dict[str, ChatStore] = {}  # tester id -> chat
        self._ids = itertools.count(1)
        self.sent_count = 0

    def store_for(self, tester_id: str) -> ChatStore:
        return self.stores.setdefault(tester_id, ChatStore(self._now))

    def _tester_store(self, phone: str) -> tuple[Any, ChatStore] | None:
        t = self.registry.by_phone(phone, self._now())
        return (t, self.store_for(t.id)) if t is not None else None

    # ------------------------------------------------------------------ MessagingChannel
    async def send(self, msg: OutboundMessage) -> SendReceipt:
        hit = self._tester_store(msg.to_phone)
        if hit is None:
            log.warning("web channel: refused a message to %s (not an active tester)", mask_phone(msg.to_phone))
            return SendReceipt(message_id=msg.id, ok=False, error="web_channel_testers_only")
        _, store = hit
        pid = f"web.{next(self._ids)}"
        store.add_out(msg, pid)
        self.sent_count += 1
        return SendReceipt(message_id=msg.id, provider_message_id=pid, sent_at=self._now())

    async def fetch_media(self, media_url: str) -> MediaBlob:
        for store in self.stores.values():
            if media_url in store.media:
                return store.media[media_url]
        raise ProviderError("web", "unknown media id")

    async def upload_media(self, data: bytes, mime: str, filename: str = "voice.ogg") -> str:
        if not data or len(data) > MAX_MEDIA_BYTES:
            raise ProviderError("web", "bad media size")
        # the voice note belongs to whoever receives it: send_audio files it under that tester
        return self._pending_upload(data, mime, filename)

    def _pending_upload(self, data: bytes, mime: str, filename: str) -> str:
        pool = self.store_for("_uploads")
        return pool.put_media(data, mime, filename)

    async def send_audio(self, to_phone: str, media_id: str, *, user_id: str | None = None) -> SendReceipt:
        return await self.send(
            OutboundMessage(
                channel=Channel.WHATSAPP,
                to_phone=to_phone,
                user_id=user_id,
                media_url=media_id,
                media_mime="audio/ogg; codecs=opus",
            )
        )

    def media_for(self, tester_id: str, media_id: str) -> MediaBlob | None:
        """A media blob the page may fetch: its own uploads or the shared voice-note pool."""
        own = self.store_for(tester_id).media.get(media_id)
        return own or self.store_for("_uploads").media.get(media_id)

    async def aclose(self) -> None:
        return None
