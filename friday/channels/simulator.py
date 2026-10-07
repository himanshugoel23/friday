"""In-memory ``MessagingChannel`` standing in for WhatsApp (simulator mode).

* ``send`` records every outbound message per phone (users, circle members,
  businesses) and wakes listeners (CLI printer, /sim HTTP, tests).
* ``make_inbound`` turns a typed line into an ``InboundMessage`` the same way the
  WhatsApp adapter would: numbered choices -> button replies (for the last
  message with buttons sent to that phone), ``/pin lat,lng`` -> location,
  ``/voice text`` -> voice note (media = the text, as the fake STT expects),
  ``/contact +91...``, ``/image name``, ``/doc name``.

Owner: Backend Engineer A.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from friday.core.clock import Clock, SystemClock
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

Listener = Callable[[OutboundMessage], Awaitable[None] | None]

SIM_MEDIA_PREFIX = "sim-media:"


class SimulatorChannel:
    channel = Channel.SIMULATOR

    def __init__(self, clock: Clock | None = None, templates: dict[str, str] | None = None) -> None:
        self.clock = clock or SystemClock()
        self.templates = templates or {}
        self.outbox: list[OutboundMessage] = []
        self._by_phone: dict[str, list[OutboundMessage]] = defaultdict(list)
        self._media: dict[str, MediaBlob] = {}
        self._listeners: list[Listener] = []
        self._ids = itertools.count(1)
        self._cond = asyncio.Condition()
        self.fail_phones: set[str] = set()  # tests: simulate delivery failure / block

    # ------------------------------------------------------------------ MessagingChannel
    async def send(self, msg: OutboundMessage) -> SendReceipt:
        provider_id = f"sim.{next(self._ids)}"
        if msg.to_phone in self.fail_phones:
            return SendReceipt(
                message_id=msg.id,
                provider_message_id=provider_id,
                ok=False,
                error="simulated delivery failure",
                sent_at=self.clock.now(),
            )
        self.outbox.append(msg)
        self._by_phone[msg.to_phone].append(msg)
        log.debug("sim send to %s", mask_phone(msg.to_phone))
        for listener in list(self._listeners):
            try:
                res = listener(msg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:  # pragma: no cover - listener bugs never break sending
                log.exception("simulator listener failed")
        async with self._cond:
            self._cond.notify_all()
        return SendReceipt(
            message_id=msg.id, provider_message_id=provider_id, sent_at=self.clock.now()
        )

    async def fetch_media(self, media_url: str) -> MediaBlob:
        try:
            return self._media[media_url]
        except KeyError:
            from friday.core.interfaces import ProviderError

            raise ProviderError("simulator", "unknown media id") from None

    # ------------------------------------------------------------------ simulator helpers
    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def put_media(self, data: bytes, mime: str, filename: str | None = None) -> str:
        media_id = f"{SIM_MEDIA_PREFIX}{len(self._media) + 1}"
        self._media[media_id] = MediaBlob(data=data, mime=mime, filename=filename)
        return media_id

    def messages_to(self, phone: str) -> list[OutboundMessage]:
        return list(self._by_phone.get(phone, []))

    def last_to(self, phone: str) -> OutboundMessage | None:
        msgs = self._by_phone.get(phone)
        return msgs[-1] if msgs else None

    def clear(self) -> None:
        self.outbox.clear()
        self._by_phone.clear()

    async def wait_for(
        self, phone: str, count: int, timeout_s: float = 5.0
    ) -> list[OutboundMessage]:
        """Wait until at least ``count`` messages were sent to ``phone``."""

        async def _wait() -> None:
            async with self._cond:
                await self._cond.wait_for(lambda: len(self._by_phone.get(phone, [])) >= count)

        await asyncio.wait_for(_wait(), timeout_s)
        return self.messages_to(phone)

    def render(self, msg: OutboundMessage) -> str:
        """Human-readable rendering: text, numbered buttons, templates, media."""
        lines: list[str] = []
        if msg.template is not None:
            name = self.templates.get(msg.template.key, msg.template.key)
            params = " | ".join(msg.template.params)
            lines.append(f"[template {name}] {params}".rstrip())
        if msg.text:
            lines.append(msg.text)
        if msg.media_url:
            lines.append(f"[media {msg.media_mime or ''} {msg.media_url}]")
        for i, b in enumerate(msg.buttons, start=1):
            lines.append(f"  {i}) {b.title}")
        return "\n".join(lines)

    def make_inbound(self, phone: str, line: str, *, default_cc: str = "+91") -> InboundMessage:
        """Parse one typed line into an InboundMessage from ``phone``."""
        phone = normalize_phone(phone, default_cc)
        text = line.strip()
        now = self.clock.now()
        base = {"channel": self.channel, "from_phone": phone, "received_at": now}
        base["provider_message_id"] = f"sim.in.{next(self._ids)}"
        last = self.last_to(phone)
        if last and last.buttons and text.isdigit() and 1 <= int(text) <= len(last.buttons):
            b = last.buttons[int(text) - 1]
            return InboundMessage(
                kind=MessageKind.BUTTON_REPLY, text=b.title, button_id=b.id, **base
            )
        if text.startswith("/pin"):
            arg = text[4:].strip()
            lat_s, _, lng_s = arg.partition(",")
            try:
                pin = LocationPin(lat=float(lat_s), lng=float(lng_s))
            except ValueError:
                return InboundMessage(kind=MessageKind.TEXT, text=text, **base)
            return InboundMessage(kind=MessageKind.LOCATION, location=pin, **base)
        if text.startswith("/voice"):
            spoken = text[6:].strip()
            media = self.put_media(spoken.encode(), "audio/ogg", "voice.ogg")
            return InboundMessage(
                kind=MessageKind.VOICE_NOTE, media_url=media, media_mime="audio/ogg", **base
            )
        if text.startswith("/contact"):
            raw = text[8:].strip()
            try:
                contact = normalize_phone(raw, default_cc)
            except ValueError:
                contact = None
            return InboundMessage(kind=MessageKind.CONTACT, contact_phone=contact, text=raw, **base)
        for cmd, kind, mime in (
            ("/image", MessageKind.IMAGE, "image/jpeg"),
            ("/doc", MessageKind.DOCUMENT, "application/pdf"),
        ):
            if text.startswith(cmd):
                name = text[len(cmd) :].strip() or "file"
                media = self.put_media(name.encode(), mime, name)
                return InboundMessage(
                    kind=kind, media_url=media, media_mime=mime, text=None, **base
                )
        return InboundMessage(kind=MessageKind.TEXT, text=text, **base)


def build_simulator_channel(c: Container) -> SimulatorChannel:
    return SimulatorChannel(c.clock, templates=dict(c.settings.whatsapp_templates))
