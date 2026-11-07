# ruff: noqa: E501
"""The parent's WhatsApp door (T07): voice-note first, in the parent's own language, no typing asked of the parent.

    outbound   RobinHub / IntroService / MissedCallService / GreetingService
                  -> ``ctx.parent_channel`` (``ParentChannel``) = ``WhatsAppParentChannel``
                  -> TTS (existing voice stack) -> Ogg/Opus -> ``upload_media`` -> ``send_audio``      (inside the 24 h window)
                  -> a pre-approved TEMPLATE carrying the text                                          (outside it)
    inbound    InboundPipeline (ONE early hook, before user resolution) -> ``RobinHub.parent_inbound`` -> ``ParentInbound.handle``
                  voice note: fetch media -> STT -> drop the audio -> ``RobinHub.parent_said(via="voice")``
                  words typed that are a control word (stop / help / I am fine ...) -> ``parent_said(via="text")``
                  other text, forwarded content, images, documents -> ``ScamIntake`` (T13 STUB below)
                  everything else -> a short hello. NOTHING from a Robin parent ever reaches the general assistant or its menu.

Privacy: the parent's audio exists only as bytes in memory between the fetch and the transcript. It is never written to disk or to the
database, never logged, never cached, and the provider's copy is deleted best-effort (``delete_media``). The transcript is handed to
``parent_said`` and is not stored by this module. Logs carry member ids and short status words only (no phone, no words).

Real Meta sending is BLOCKED (docs/META_UNBLOCK_PLAN.md): this is the adapter over ``channels/whatsapp.py`` and its fakes; the real
send has not been exercised. Every spoken/chat line is PENDING founder approval (``lines.LINE_STATUS`` is not touched here), and the
template wording below is PENDING too (docs/ROBIN_FAMILY_CORE.md section 10). The product name is only ever ``{brand}``.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from friday.core.logging import get_logger
from friday.core.models import (
    AudioClip,
    Channel,
    Language,
    MediaBlob,
    MessageKind,
    OutboundMessage,
    SendReceipt,
)
from friday.core.templates import make_template
from friday.robin import answers as ans
from friday.robin.models import Family, Member
from friday.robin.store import Record

log = get_logger(__name__)

# ---------------------------------------------------------------------------- templates (PENDING Meta approval)
# Registered in friday/core/templates.py (logical key -> Meta name); ``make_template`` checks the variable count.
TEMPLATE_MESSAGE = "robin_parent_message"  # robin_parent_message_v1: {{1}} = the line, already in the parent's language: used whenever the 24 h window is closed
TEMPLATE_REOPEN = "robin_parent_reopen"  # robin_parent_reopen_v1: {{1}} = how the family calls the parent, {{2}} = the child's name: asks for any reply to reopen the window
TEMPLATES: dict[str, tuple[str, ...]] = {TEMPLATE_MESSAGE: ("line",), TEMPLATE_REOPEN: ("parent", "child")}  # logical key -> ordered parameter names
MAX_PARAM = 900
OPUS_MIME = "audio/ogg; codecs=opus"
TEMPLATE_DEDUPE = timedelta(minutes=5)  # a voice note + its text out of window must not send the same template twice
NO_WINDOW_CODE = "131047"  # Meta: "re-engagement message" (the window closed while we were sending)


def _language(lang: str | None) -> Language:
    return {"en": Language.EN, "hi": Language.HI}.get((lang or "").lower(), Language.HINGLISH)


def _template_language(lang: str | None) -> str:
    return "hi" if (lang or "").lower() == "hi" else "en"  # same rule as channels/notifier.py (hinglish is Roman: the English frame)


# ---------------------------------------------------------------------------- the 24 h window
@runtime_checkable
class WindowTracker(Protocol):
    """When did this phone last write to us? (The parent's messages are not stored in the chat log, so the channel keeps its own marker.)"""

    async def last_inbound(self, phone: str) -> datetime | None: ...
    async def note(self, phone: str, at: datetime) -> None: ...


class MemoryWindow:
    def __init__(self) -> None:
        self.at: dict[str, datetime] = {}

    async def last_inbound(self, phone: str) -> datetime | None:
        return self.at.get(phone)

    async def note(self, phone: str, at: datetime) -> None:
        self.at[phone] = at


class CacheWindow:
    """The shared cache (keyed by the blind index of the phone, never the number). A restart with an in-process cache forgets the marker:
    the window then reads as CLOSED and the template is used, which always works."""

    def __init__(self, cache: Any, index: Any, ttl_s: int) -> None:
        self.cache, self.index, self.ttl_s = cache, index, ttl_s

    def _key(self, phone: str) -> str:
        return f"robin:wa:in:{self.index(phone)}"

    async def last_inbound(self, phone: str) -> datetime | None:
        raw = await self.cache.get(self._key(phone))
        try:
            return datetime.fromisoformat(raw) if raw else None
        except (TypeError, ValueError):
            return None

    async def note(self, phone: str, at: datetime) -> None:
        await self.cache.set(self._key(phone), at.isoformat(), ttl_s=self.ttl_s)


# ---------------------------------------------------------------------------- outbound
class WhatsAppParentChannel:
    """``ports.ParentChannel`` over the WhatsApp Cloud channel. Never raises: a failure returns False and the caller (intro, missed call,
    greetings) leaves the line in the app outbox (``pending`` record) for the T08 drain to retry."""

    def __init__(self, wa: Any, *, tts: Any, converter: Any, clock: Any, window: WindowTracker, window_h: int = 24) -> None:
        self.wa = wa  # send / upload_media / send_audio (channels/whatsapp.py)
        self._tts = tts  # a callable returning the TTSProvider or None (lazy: the container builds it on first use)
        self.converter = converter  # chatbot_media.convert.AudioConverter (text-to-Ogg/Opus)
        self.clock, self.window, self.window_h = clock, window, window_h
        self._recent: dict[tuple[str, str], datetime] = {}

    @property
    def tts(self) -> Any:
        try:
            return self._tts()
        except Exception as e:  # noqa: BLE001 - no TTS configured: voice notes degrade to text
            log.info("robin: no TTS available (%s)", type(e).__name__)
            return None

    async def note_inbound(self, phone: str) -> None:
        await self.window.note(phone, self.clock.now())

    async def in_window(self, phone: str) -> bool:
        last = await self.window.last_inbound(phone)
        return last is not None and self.clock.now() - last < timedelta(hours=self.window_h)

    # ------------------------------------------------------------------ ParentChannel
    async def send_text(self, member: Member, text: str) -> bool:
        if not member.phone or not text:
            return False
        if not await self.in_window(member.phone):
            return await self._template(member, TEMPLATE_MESSAGE, {"line": text})
        rec = await self._send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=member.phone, text=text))
        if rec is not None and not rec.ok and NO_WINDOW_CODE in (rec.error or ""):
            return await self._template(member, TEMPLATE_MESSAGE, {"line": text})  # the window closed under us
        return bool(rec and rec.ok)

    async def send_voice_note(self, member: Member, text: str, language: str) -> bool:
        if not member.phone or not text:
            return False
        if not await self.in_window(member.phone):
            return await self._template(member, TEMPLATE_MESSAGE, {"line": text})  # a voice note cannot open a conversation: the template carries the words
        tts = self.tts
        if tts is None or not getattr(self.converter, "available", False):
            return False
        try:
            clip: AudioClip = await tts.synthesize(text, _language(language or member.language))
            ogg = await self.converter.to_ogg_opus(clip)
            if not ogg:
                return False
            media_id = await self.wa.upload_media(ogg, OPUS_MIME, "voice.ogg")
            del ogg, clip  # our copy of the outgoing audio is not kept either
            receipt = await self.wa.send_audio(member.phone, media_id)
        except Exception as e:  # noqa: BLE001 - never raises into a safety path
            log.warning("robin: voice note to member %s failed (%s)", member.id, type(e).__name__)
            return False
        if not receipt.ok:
            log.warning("robin: voice note to member %s rejected (%s)", member.id, (receipt.error or "")[:40])
        return bool(receipt.ok)

    async def send_template(self, member: Member, template: str, params: dict[str, str], media: bytes | None = None, media_mime: str | None = None) -> bool:  # noqa: ARG002 - media: no template here carries a header
        if not member.phone or template not in TEMPLATES:
            return False
        return await self._template(member, template, params)

    # ------------------------------------------------------------------ helpers
    async def reopen(self, member: Member, parent_label: str, child_name: str) -> bool:
        """Ask the parent (outside the window) to reply with anything so queued lines can follow (used by the T08 outbox drain)."""
        return await self._template(member, TEMPLATE_REOPEN, {"parent": parent_label, "child": child_name})

    async def _template(self, member: Member, name: str, params: dict[str, str]) -> bool:
        assert member.phone
        values = [" ".join(str(params.get(k, "")).split())[:MAX_PARAM] or "-" for k in TEMPLATES[name]]
        now = self.clock.now()
        fp = (member.id, hashlib.sha256(f"{name}|{'|'.join(values)}".encode()).hexdigest()[:16])
        self._recent = {k: t for k, t in self._recent.items() if now - t < TEMPLATE_DEDUPE}
        if fp in self._recent:
            return True  # the same template was just sent (voice note + text of one message): once is enough
        rec = await self._send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=member.phone, template=make_template(name, values, _template_language(member.language))))
        ok = bool(rec and rec.ok)
        if ok:
            self._recent[fp] = now
        return ok

    async def _send(self, msg: OutboundMessage) -> SendReceipt | None:
        try:
            return await self.wa.send(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("robin: WhatsApp send failed (%s)", type(e).__name__)
            return None


# ---------------------------------------------------------------------------- T13 stub
@runtime_checkable
class ScamIntake(Protocol):
    async def handle(self, *, family: Family, parent: Member, msg: Any, text: str | None) -> str | None:
        """Return a short line to say back to the parent, or None."""
        ...


class UnbuiltScamIntake:
    """T13 STUB (docs/ROBIN_PHASE1_BACKLOG.md T13: scam check by forwarding). Text, links, forwarded messages and screenshots from a
    parent land here. NOTHING is analysed, stored or logged yet: ``scamcheck`` is wired in T13. Until then the parent gets the existing
    short hello (PENDING) and the content is dropped. It must never be handed to the general assistant."""

    async def handle(self, *, family: Family, parent: Member, msg: Any, text: str | None) -> str | None:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------- inbound
CONTROL_WORDS = (ans.is_stop, ans.is_start, ans.is_help, ans.is_fine, ans.is_threat)


@dataclass
class ParentInbound:
    """The route for a message from a Robin PARENT. ``handle`` returns True when the sender is a parent (the message is consumed, whatever
    happened) and False for anybody else (the pipeline carries on as before)."""

    hub: Any  # RobinHub
    messaging: Any  # getter -> the WhatsApp channel (fetch_media, delete_media) or None
    stt: Any  # getter -> STTProvider or None
    cache: Any = None  # getter -> shared cache or None (provider-retry de-dupe)
    scam: ScamIntake = field(default_factory=UnbuiltScamIntake)
    seen_ttl_s: int = 3600

    async def handle(self, msg: Any) -> bool:
        hit = await self.hub.fam.parent_by_phone(msg.from_phone)
        if hit is None:
            return False  # not a parent (or no Robin family): unknown numbers are NOT treated as parents
        fam, parent = hit
        try:
            await self._route(fam, parent, msg)
        except Exception as e:  # noqa: BLE001 - a bug here must not turn the parent into a general-assistant user
            log.error("robin: parent message handling failed (%s)", type(e).__name__)
        return True

    async def _route(self, fam: Family, parent: Member, msg: Any) -> None:
        ch = self.hub.ctx.parent_channel
        if ch is not None and hasattr(ch, "note_inbound"):
            await ch.note_inbound(msg.from_phone)  # their message opens a 24 h window
        if await self._duplicate(msg):
            return
        try:
            await self._handle(fam, parent, msg)
        finally:
            outbox = getattr(self.hub, "outbox", None)
            if outbox is not None:  # the window just opened: lines that waited in the app outbox go now (T08; each exactly once; a pause holds them)
                try:
                    fresh = await self.hub.ctx.store.get_member(parent.id)
                    if fresh is not None:
                        await outbox.drain_member(fam, fresh)
                except Exception as e:  # noqa: BLE001
                    log.warning("robin: outbox drain failed (%s)", type(e).__name__)

    async def _handle(self, fam: Family, parent: Member, msg: Any) -> None:
        kind = msg.kind
        if kind == MessageKind.VOICE_NOTE:
            text = await self._listen(msg, parent)
            if text:
                reply = await self.hub.parent_said(msg.from_phone, text, via="voice")
                if reply is None:
                    await self._hello(fam, parent)
            else:
                await self._unclear(fam, parent)  # could not hear it: ask to say it again, never silence (T08; PENDING line inbound.unclear)
            return
        text = (msg.text or "").strip() if kind in (MessageKind.TEXT, MessageKind.BUTTON_REPLY) else ""
        if text and any(f(text) for f in CONTROL_WORDS):
            reply = await self.hub.parent_said(msg.from_phone, text, via="text")  # 'stop' typed still stops
            if reply is None:
                await self._hello(fam, parent)
            return
        say = await self.scam.handle(family=fam, parent=parent, msg=msg, text=text or None)  # T13 STUB: text, links, forwards, screenshots
        if say:
            await self._say(fam, parent, say)
        else:
            await self._hello(fam, parent)

    async def _listen(self, msg: Any, parent: Member) -> str | None:
        """fetch -> STT -> forget. The bytes live only in this frame."""
        messaging, stt = self._get(self.messaging), self._get(self.stt)
        if messaging is None or stt is None or not msg.media_url:
            return None
        blob: MediaBlob | None = None
        try:
            blob = await messaging.fetch_media(msg.media_url)
            from friday.voice.voicenote import transcribe_voice_note

            tr = await transcribe_voice_note(stt, blob, language_hint=_language(parent.language))
            return (tr.text or "").strip() or None
        except Exception as e:  # noqa: BLE001
            log.info("robin: parent voice note could not be read (%s)", type(e).__name__)
            return None
        finally:
            blob = None  # drop the audio
            delete = getattr(messaging, "delete_media", None)
            if callable(delete):
                with contextlib.suppress(Exception):
                    await delete(msg.media_url)  # the provider's copy too (best effort)

    async def _duplicate(self, msg: Any) -> bool:
        cache, mid = self._get(self.cache), msg.provider_message_id
        if cache is None or not mid:
            return False
        key = f"robin:wa:mid:{hashlib.sha256(mid.encode()).hexdigest()[:24]}"
        if await cache.get(key):
            return True
        await cache.set(key, "1", ttl_s=self.seen_ttl_s)
        return False

    @staticmethod
    def _get(getter: Any) -> Any:
        try:
            return getter() if getter is not None else None
        except Exception:  # noqa: BLE001 - component not configured
            return None

    async def _hello(self, fam: Family, parent: Member) -> None:
        c = self.hub.ctx
        await self._say(fam, parent, c.say("inbound.hello", parent.language, **await c.slots(fam)))

    async def _unclear(self, fam: Family, parent: Member) -> None:
        c = self.hub.ctx
        await self._say(fam, parent, c.say("inbound.unclear", parent.language, **await c.slots(fam)), line="inbound.unclear")

    async def _say(self, fam: Family, parent: Member, text: str, line: str = "inbound.hello") -> None:
        """Voice note + text to the parent; with no channel (or a failed send) the line waits in the app outbox, like the other Robin lines."""
        c = self.hub.ctx
        ch, sent = c.parent_channel, False
        if ch is not None:
            try:
                sent = bool(await ch.send_voice_note(parent, text, parent.language))
                await ch.send_text(parent, text)
            except Exception as e:  # noqa: BLE001
                log.warning("robin: reply to the parent failed (%s)", type(e).__name__)
        if not sent:
            await c.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=c.clock.now(), data={"member_id": parent.id, "line": line, "purpose": "reply", "text": text, "incident_id": None}))


# ---------------------------------------------------------------------------- fakes (tests and the simulator; nothing leaves the process)
@dataclass
class FakeWhatsApp:
    """Stands in for ``WhatsAppCloudChannel``: records sends/uploads, serves ``media`` by id, can be told to fail."""

    sent: list[OutboundMessage] = field(default_factory=list)
    uploads: list[tuple[bytes, str]] = field(default_factory=list)
    audios: list[tuple[str, str]] = field(default_factory=list)  # (phone, media id)
    deleted: list[str] = field(default_factory=list)
    media: dict[str, MediaBlob] = field(default_factory=dict)
    fail_send: bool = False
    fail_upload: bool = False
    send_error: str | None = None  # e.g. "131047: re-engagement" to simulate a closed window

    async def send(self, msg: OutboundMessage) -> SendReceipt:
        if self.fail_send:
            raise RuntimeError("send failed")
        if self.send_error:
            return SendReceipt(message_id=msg.id, ok=False, error=self.send_error)
        self.sent.append(msg)
        return SendReceipt(message_id=msg.id, provider_message_id=f"wamid.fake{len(self.sent)}")

    async def upload_media(self, data: bytes, mime: str, filename: str = "voice.ogg") -> str:
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploads.append((data, mime))
        return f"FAKEMEDIA{len(self.uploads)}"

    async def send_audio(self, to_phone: str, media_id: str, *, user_id: str | None = None) -> SendReceipt:  # noqa: ARG002
        if self.fail_send:
            raise RuntimeError("send failed")
        self.audios.append((to_phone, media_id))
        return SendReceipt(message_id=media_id, provider_message_id=f"wamid.fakeaudio{len(self.audios)}")

    async def fetch_media(self, media_url: str) -> MediaBlob:
        return self.media[media_url]

    async def delete_media(self, media_id: str) -> bool:
        self.deleted.append(media_id)
        return True
