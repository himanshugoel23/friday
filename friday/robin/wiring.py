# ruff: noqa: E501
"""Plumbing: the ``robin`` component (None unless FRIDAY_ROBIN_ENABLED) and the ``RobinHub`` that ties the services together.

    child chat / button        --InboundPipeline._active--> RobinHub.handle        (setup, commands, alert buttons)
    parent voice note / text   --(WhatsApp media path)----> RobinHub.parent_said   (stop, start, help, 'I am fine')
    widget press-to-talk / SOS --(device API, later)------> RobinHub.widget_voice / widget_sos   (interface only)
    device/signal package      --------------------------> alerts.raise_alert      (module-level, stable)
    Runtime                    --------------------------> RobinHub.loop()         (scheduler)

The dial is ``TelephonyParentCaller`` (refuses while the lines are PENDING) behind ``RobinGate`` (the real CallGate, pilot
allow-list). The care protocol is imported defensively (``ports.care_active_fn``). Nothing is sent or dialled in tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, ReplyButton, User
from friday.robin import alerts as alerts_mod
from friday.robin import answers as ans
from friday.robin import opscounts
from friday.robin.alerts import AlertEngine, RobinAlert
from friday.robin.authority import AuthorityService
from friday.robin.checkin import CheckinService
from friday.robin.commands import RobinCommands
from friday.robin.context import Ctx
from friday.robin.family import FamilyService
from friday.robin.greetings import GreetingService
from friday.robin.intro import IntroService
from friday.robin.medicine import MedicineService
from friday.robin.missedcall import MissedCallService, MissedResult
from friday.robin.models import Family, Member, Tier, normalise_scenario, parse_tier
from friday.robin.sos import SosResult, SosService

log = get_logger(__name__)
PURGE_EVERY_TICKS = 120


@dataclass
class ParentReply:
    text: str
    action: str  # paused | resumed | sos | fine | hello | care


class WidgetHooks(Protocol):
    """What the thin Android widget needs from the server (interface only; the transport is the device API of friday/robindevice)."""

    async def widget_voice(self, parent_member_id: str, transcript: str) -> ParentReply | None: ...
    async def widget_sos(self, parent_member_id: str, location: tuple[float, float] | None = None) -> SosResult: ...


class RobinHub:
    def __init__(self, ctx: Ctx, *, retries: int = 2, retry_minutes: int = 20, retention_days: int = 30, incident_retention_days: int = 90, tick_s: float = 30.0) -> None:
        self.ctx = ctx
        self.fam = FamilyService(ctx)
        self.meds = MedicineService(ctx, self.fam)
        self.alerts = AlertEngine(ctx, self.fam)
        self.intro = IntroService(ctx, self.fam)
        self.checkin = CheckinService(ctx, self.fam, self.meds, self.alerts, retries=retries, retry_minutes=retry_minutes)
        self.sos = SosService(ctx, self.alerts)
        self.greetings = GreetingService(ctx, self.fam, self.meds)
        self.authority = AuthorityService(ctx)
        self.alerts.authority = self.authority
        self.missed = MissedCallService(ctx, self.fam, self.alerts)
        self.commands = RobinCommands(ctx, self.fam, self.intro, self.checkin, self.meds, self.alerts, safe_word_switch=bool(getattr(ctx.settings, "robin_safe_word_enabled", False)))
        ctx.on_reached = self.checkin.note_reached
        self.retention_days, self.incident_retention_days, self.tick_s, self._ticks = retention_days, incident_retention_days, tick_s, 0
        self._device_sweep: Callable[[], Awaitable[int]] | None = None
        self.device_service: Any = None
        self.last_tick_at: datetime | None = None  # T05: ops counts only (an age in seconds), never shown to anyone
        self.parent_route: Any = None  # channel.ParentInbound (T07), set by build_robin; None = parents are not routed (tests that build a bare hub)

    # ------------------------------------------------------------------ the child's chat
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        try:
            return await self.commands.handle(user, msg)
        except Exception:  # noqa: BLE001 - a failure here never blocks the normal chat
            log.exception("robin: chat command failed")
            return False

    # ------------------------------------------------------------------ the parent's door (T07): the pipeline's ONE early hook
    async def parent_inbound(self, msg: InboundMessage) -> bool:
        """True when the sender is a Robin PARENT: the message is consumed here and never reaches the general assistant."""
        if self.parent_route is None:
            return False
        try:
            return bool(await self.parent_route.handle(msg))
        except Exception:  # noqa: BLE001 - never block the normal chat for a non-parent
            log.exception("robin: parent route failed")
            return False

    # ------------------------------------------------------------------ the parent's words (voice note already transcribed, or text)
    async def parent_said(self, phone: str, text: str, via: str = "text") -> ParentReply | None:
        hit = await self.fam.parent_by_phone(phone)
        if hit is None:
            return None
        fam, parent = hit
        c = self.ctx
        reply: ParentReply | None = None
        if ans.is_stop(text) or (c.brand.lower() in text.lower() and ans.is_stop(text.lower().replace(c.brand.lower(), ""))):
            await self.fam.pause(parent.id, via)  # stops everything; tells the child; only the PARENT can resume the sensitive items
            reply = ParentReply(c.say("pause.ack", parent.language, **await c.slots(fam)), "paused")
        elif (care := await self._parent_care(fam, parent, text)) is not None:
            reply = care
        elif ans.is_start(text) and parent.paused:
            await self.fam.resume(parent.id, via)
            reply = ParentReply(c.say("resume.ack", parent.language, **await c.slots(fam)), "resumed")
        elif ans.is_threat(text):  # "I am being threatened": EMERGENCY, physical, the desk's own signal
            res = await self.alerts.raise_alert(RobinAlert(parent.id, Tier.EMERGENCY, "threat", f"{fam.parent_label} says they are being threatened", dedupe_key=f"threat:{parent.id}:{int(c.clock.now().timestamp() // 300)}", category="physical", signals=("parent_said_threat",)))
            if res.accepted:
                reply = ParentReply(c.say("sos.parent", parent.language, **await c.slots(fam)), "sos")
        elif ans.is_help(text):
            res = await self.sos.trigger(parent.id, "call" if via == "call" else "app")
            if res.alert.accepted:
                reply = ParentReply(c.say("sos.parent", parent.language, **await c.slots(fam)), "sos")
        elif ans.is_fine(text):
            if await self.alerts.parent_fine(parent.id):
                reply = ParentReply(c.say("nudge.fine_ack", parent.language, **await c.slots(fam)), "fine")
        if reply is None and via == "call":
            reply = ParentReply(c.say("inbound.hello", parent.language, **await c.slots(fam)), "hello")
        if not parent.paused:
            await self.checkin.note_reached(fam, parent)  # any word from the parent ends an 'unanswered' ladder
        if reply is not None and c.parent_channel is not None and via not in ("call", "widget"):  # the widget gets its reply in the HTTP answer
            await c.parent_channel.send_voice_note(parent, reply.text, parent.language)  # voice note first, then the same words as text
            await c.parent_channel.send_text(parent, reply.text)
        return reply

    async def _parent_care(self, fam: Family, parent: Member, text: str) -> ParentReply | None:
        """The parent's own words pass the care protocol (docs/CARE_PROTOCOL.md): HIGH distress -> the care lines to the parent, in their
        language; the child is told ONLY with the parent's ``share_summary_with_child`` consent (``authority.distress`` line), and never with the words (no content kept).
        Stop always wins (checked before this), a physical threat/help is handled by the SOS branches below only when this is not HIGH."""
        from friday.care import copy as care_copy
        from friday.care.detect import Tier as CareTier
        from friday.care.detect import assess

        a = assess(text)
        if a.tier != CareTier.HIGH:
            return None
        c = self.ctx
        lang = parent.language if parent.language in ("en", "hinglish", "hi") else "hinglish"
        log.info("robin: care tier=high from a parent (member %s)", parent.id)
        if await c.has_consent(parent, "share_summary_with_child"):  # a plain message to the child at any hour (security paths ignore time of day); no words, no alert-engine consent gate
            await c.tell_child(fam, c.say("authority.distress", await c.chat_lang(fam), parent=fam.parent_label))
            await c.audit(fam, "parent_distress", f"{fam.parent_label} may be in distress; the care protocol line was sent to them and you were told.")
        return ParentReply(care_copy.line("high_first", lang, elder=True), "care")

    # ------------------------------------------------------------------ missed calls, either direction (the voice front door calls this)
    async def on_missed_call(self, missed_phone: str, caller_phone: str | None, answers: list[Any]) -> MissedResult | None:
        return await self.missed.on_missed(missed_phone, caller_phone, answers)

    # ------------------------------------------------------------------ widget hooks (interface; transport later)
    async def widget_voice(self, parent_member_id: str, transcript: str) -> ParentReply | None:
        m = await self.ctx.store.get_member(parent_member_id)
        return await self.parent_said(m.phone, transcript, "widget") if m and m.phone else None

    async def widget_sos(self, parent_member_id: str, location: tuple[float, float] | None = None) -> SosResult:
        return await self.sos.trigger(parent_member_id, "app", location)

    # ------------------------------------------------------------------ prescription photo (document reader)
    async def on_document_confirmed(self, user_id: str, doc: Any) -> str | None:
        """Called by the document service when the child confirmed a document. Only a 'prescription' type is used; the child then
        confirms the medicines (yes/no) before anything is saved. NOTE: docunderstand has no PRESCRIPTION type yet (unverified)."""
        if getattr(getattr(doc, "doc_type", None), "value", "") != "prescription":
            return None
        fam = await self.fam.family_of_owner(user_id)
        if fam is None:
            return None
        texts = [f.value for f in getattr(doc, "fields", {}).values() if getattr(f, "value", "")]
        meds = await self.meds.from_document_lines(fam, texts)
        if not meds:
            return None
        lang = await self.ctx.chat_lang(fam)
        return self.ctx.say("med.confirm", lang, list="; ".join(f"{m.name} {m.dose_text} at {', '.join(m.times)}" for m in meds))

    # ------------------------------------------------------------------ scheduler
    def attach_device_sweep(self, sweep: Callable[[], Awaitable[int]]) -> None:
        """The device package registers ``DeviceService.sweep`` (time-based scenarios S7/S8) when it is mounted."""
        self._device_sweep = sweep
        self.device_service = getattr(sweep, "__self__", None)  # T05: only for integer counts in /ops-status/<token>/robin

    async def _device_tick(self) -> int:
        return int(await self._device_sweep() or 0) if self._device_sweep is not None else 0

    async def tick(self) -> int:
        n = 0
        for step in (self.intro.retry_due, self.authority.tick, self.checkin.tick, self.meds.tick, self.greetings.tick, self._monthly, self._device_tick):
            try:
                n += int(await step() or 0)
            except Exception:  # noqa: BLE001 - one failing step never stops the others
                log.exception("robin: tick step failed")
                opscounts.bump("tick_step_errors")
        self._ticks += 1
        self.last_tick_at = self.ctx.clock.now()
        opscounts.write_tick_marker()
        if self._ticks % PURGE_EVERY_TICKS == 0:
            try:
                await self.retention()
            except Exception:  # noqa: BLE001
                log.exception("robin: retention failed")
        return n

    async def retention(self) -> dict[str, int]:
        """Scheduled deletion (every ``PURGE_EVERY_TICKS`` ticks): audit rows after ``retention_days`` (30), finished incident
        records after ``incident_retention_days`` (90; an open incident is never deleted). Device events and call-pattern cues
        are cleaned by ``DeviceService.sweep`` in the same tick. Returns counts (no PII)."""
        now = self.ctx.clock.now()
        store = self.ctx.store
        return {
            "audit": await store.purge_before("audit", now - timedelta(days=self.retention_days)),
            "incident": await store.purge_before("incident", now - timedelta(days=self.incident_retention_days), ("closed", "exhausted")),
        }

    async def _monthly(self) -> int:
        n = 0
        for f in await self.ctx.store.all_families(("active",)):
            n += int(await self.fam.monthly_reminder(f))
        return n

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("robin: tick failed")
                opscounts.bump("tick_errors")
            await asyncio.sleep(self.tick_s)

    async def forget_user(self, user_id: str) -> None:
        from friday.robin.models import Role
        from friday.robin.ports import run_erase_hooks

        parents = [m.id for f in await self.ctx.store.families_for_owner(user_id) for m in await self.ctx.store.members(f.id, Role.PARENT)]
        await self.ctx.store.erase_owner(user_id)
        await run_erase_hooks(parents)

    async def family(self, user_id: str) -> Family | None:
        return await self.fam.family_of_owner(user_id)

    async def parent(self, family: Family) -> Member | None:
        return await self.ctx.parent(family)


def build_robin(c: Any) -> RobinHub | None:
    s = c.settings
    if not s.robin_enabled:
        return None
    from friday.calls.dnc import DncRegistry
    from friday.calls.gate import CallGate
    from friday.calls.numbers import NumberHasher
    from friday.calls.settings import CallsSettings
    from friday.pause import is_paused
    from friday.robin.gate import RobinGate
    from friday.robin.store import RobinStore
    from friday.robin.telephony import TelephonyParentCaller

    repos = c.get("repos")
    hasher = NumberHasher()
    store = RobinStore(repos.db, c.clock, hasher)

    async def send(user_id: str, text: str, buttons: Sequence[ReplyButton]) -> None:
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    gate = RobinGate(
        CallGate(store=repos.consumer_calls, dnc=DncRegistry(repos.call_dnc, hasher, c.clock), hasher=hasher, settings=CallsSettings(), core_settings=s),
        hasher, s,
    )  # fmt: skip

    def paused() -> bool:
        return is_paused(s)

    async def audit_sink(action: str, user_id: str, *, actor: str, source: str, counts: dict[str, int]) -> None:
        await repos.audit.log(action, user_id=user_id, actor="user", by=actor, source=source, counts=counts)  # counts only, no PII

    parent_channel = build_parent_channel(c)  # None unless FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED and the cloud WhatsApp channel is configured
    ctx = Ctx(store=store, clock=c.clock, send=send, caller=TelephonyParentCaller(lambda: c.telephony, s, paused=paused), gate=gate, users=repos.users, settings=s, care=_care_gate(c), paused=paused, audit_sink=audit_sink, parent_channel=parent_channel)
    ctx.extra_senders["second"] = make_second_sender(lambda: c.get("notifier"))  # T20: the second contact's alert line (WhatsApp); the "ops" sender is NOT wired (no founder channel exists)
    hub = RobinHub(ctx, retries=int(s.robin_checkin_retries), retry_minutes=int(s.robin_checkin_retry_minutes), retention_days=int(s.robin_audit_retention_days), incident_retention_days=int(s.robin_incident_retention_days), tick_s=float(s.robin_tick_s))
    alerts_mod.set_default_engine(hub.alerts)
    from friday.care.service import register_passthrough

    register_passthrough("robin", hub.commands.is_open_ack)  # T20: the child's typed "I have it" / "Mark safe" passes a care episode while an alert is open
    hub.parent_route = _parent_route(c, hub)
    return hub


def _opt_component(c: Any, name: str) -> Any:
    try:
        return c.get(name)
    except Exception:  # noqa: BLE001 - not configured
        return None


def _parent_route(c: Any, hub: RobinHub) -> Any:
    """Inbound route for Robin parents (T07). Always built with Robin: a parent's message must never fall through to the general assistant,
    whether or not the outbound channel is configured."""
    from friday.robin.channel import ParentInbound

    return ParentInbound(hub, messaging=lambda: _opt_component(c, "messaging"), stt=lambda: _opt_component(c, "stt"), cache=lambda: _opt_component(c, "cache"))


def build_parent_channel(c: Any) -> Any:
    """``WhatsAppParentChannel`` over the container's WhatsApp channel, only when the switch is on AND the cloud channel is configured
    (token + phone number id). Otherwise None: lines wait in the app outbox. Real Meta sending is blocked; nothing here has run against Meta."""
    s = c.settings
    if not getattr(s, "robin_parent_whatsapp_enabled", False) or s.resolve_whatsapp() != "cloud" or not s.whatsapp_access_token or not s.whatsapp_phone_number_id:
        return None
    wa = _opt_component(c, "messaging")
    if wa is None or not all(callable(getattr(wa, n, None)) for n in ("send", "upload_media", "send_audio")):
        return None
    from friday.chatbot_media.convert import FfmpegConverter
    from friday.db.repositories._base import phone_index
    from friday.robin.channel import CacheWindow, WhatsAppParentChannel

    window = CacheWindow(c.get("cache"), phone_index, int(s.whatsapp_session_window_h) * 3600)
    return WhatsAppParentChannel(wa, tts=lambda: _opt_component(c, "tts"), converter=FfmpegConverter(), clock=c.clock, window=window, window_h=int(s.whatsapp_session_window_h))


def make_second_sender(get_notifier: Callable[[], Any]) -> Callable[[Member, str], Awaitable[None]]:
    """The production ``ctx.extra_senders["second"]``: a thin sender over the existing Notifier / WhatsApp channel.

    It carries ONLY the alert line the engine built (``alert.second`` / ``sos.second``), and only to a contact the child named in advance
    (role SECOND_CONTACT with ``call_ok``). It raises on any refusal so the engine records "could not send"; the Notifier applies the 24 h
    window rule, so outside the window a free-text alert is refused (TEMPLATE_REQUIRED) until a pre-approved template exists (Meta is blocked).
    """
    from friday.core.models import Channel, OutboundMessage
    from friday.robin.models import Role

    async def send_second(member: Member, text: str) -> None:
        if member.role != Role.SECOND_CONTACT or not member.call_ok or not member.phone:
            raise PermissionError("not a named second contact")
        receipt = await get_notifier().send(OutboundMessage(channel=Channel.WHATSAPP, to_phone=member.phone, text=text))
        if not getattr(receipt, "ok", False):
            raise RuntimeError(f"not delivered: {getattr(receipt, 'error', None) or 'unknown'}")

    return send_second


def _care_gate(c: Any) -> Any:
    """The care protocol's ``is_active`` from the container's "care" component, resolved lazily (the pipeline registers it
    after the container is built). Absent or broken -> inactive."""
    from friday.robin.ports import care_active_fn

    fallback = care_active_fn()

    async def active(user_id: str) -> bool:
        try:
            svc = c.get("care")
            return bool(await svc.is_active(user_id))
        except Exception:  # noqa: BLE001 - never block a family call because the care module is missing
            res = fallback(user_id)
            return bool(await res) if hasattr(res, "__await__") else bool(res)

    return active


# device item (friday/robindevice/ports.py CONSENT_ITEMS) -> family consent item (friday/robin/models.py ConsentItem)
DEVICE_TO_FAMILY_CONSENT = {
    "calls": "device_signals", "camera": "device_signals", "remote_access": "device_signals", "payment_app": "device_signals",
    "unknown_sources": "device_signals", "heartbeat": "device_signals", "payment_notifications": "payment_alerts",
    "share_check": "scam_check", "share_alert_child": "share_summary_with_child", "location": "location",
    "voice_messages": "scam_check", "call_pattern": "call_listening",
}


# T09: press-to-talk and the SOS button's location are explicit actions by the parent, so they stay available while Robin is paused; the
# consent itself is still required and can still be withdrawn. (Location is only ever sent with an SOS, never as a background signal.)
PARENT_ACTION_ITEMS = frozenset({"voice_messages", "location"})


class _DeviceAlerts:
    def __init__(self, hub: Any) -> None:
        self.hub = hub

    async def raise_alert(self, parent_id: str, tier: str, scenario: str, why: str, details: dict[str, Any]) -> None:
        from friday.robin import alerts as alerts_mod

        d = details or {}
        tier, known = parse_tier(tier)  # the device package sends 'HIGH'/'EMERGENCY'; unknown -> HIGH, never lower
        if not known:
            log.warning("robin: device sent an unknown alert tier, treated as HIGH")
        loc = d.get("location")
        location = (float(loc["lat"]), float(loc["lon"])) if isinstance(loc, dict) and "lat" in loc and "lon" in loc else None  # the engine re-checks consent and uses it for SOS only
        await alerts_mod.raise_alert(alerts_mod.RobinAlert(
            parent_member_id=parent_id, tier=tier, scenario=normalise_scenario(scenario), why=why, money=bool(d.get("money")),
            dedupe_key=d.get("dedupe_key"), amount_text=d.get("amount_text"), signals=tuple(d.get("signals", ()) or ()), location=location,
        ))


class _DeviceConsent:
    """The family package owns consent. The phone can only read it and WITHDRAW; a grant from the phone is ignored."""

    def __init__(self, hub: Any) -> None:
        self.hub = hub

    async def has(self, parent_id: str, item: str) -> bool:
        member = await self.hub.ctx.store.get_member(parent_id)
        mapped = DEVICE_TO_FAMILY_CONSENT.get(item)
        if member is None or mapped is None or (getattr(member, "paused", False) and item not in PARENT_ACTION_ITEMS):
            return False
        return await self.hub.ctx.has_consent(member, mapped)

    async def set(self, parent_id: str, item: str, granted: bool, source: str = "app") -> None:  # noqa: ARG002
        mapped = DEVICE_TO_FAMILY_CONSENT.get(item)
        if granted or mapped is None:
            return  # only the admin (child) grants, in the family package
        await self.hub.fam.withdraw_consent(parent_id, mapped, tell_child=True, actor="user", source="parent_device")


class _DeviceParents:
    def __init__(self, hub: Any) -> None:
        self.hub = hub

    async def get(self, parent_id: str) -> Any:
        from friday.robindevice.ports import ParentInfo

        member = await self.hub.ctx.store.get_member(parent_id)
        if member is None:
            return None
        lang = member.language if member.language in ("en", "hinglish", "hi") else "hinglish"
        return ParentInfo(parent_id=parent_id, language=lang)  # type: ignore[arg-type]


def build_device_ports(c: Any) -> dict[str, Any] | None:
    """Ports for the Android device API (friday/robindevice): alerts, consent and parent lookup backed by the family package."""
    hub = c.get("robin")
    if hub is None:
        return None
    from friday.robin.devicevoice import DeviceVoiceIntake
    from friday.robindevice.replyaudio import ReplyAudioStore

    ports: dict[str, Any] = {
        "alerts": _DeviceAlerts(hub), "consent": _DeviceConsent(hub), "parents": _DeviceParents(hub),
        "voice": DeviceVoiceIntake(hub, stt=lambda: _opt_component(c, "stt"), tts=lambda: _opt_component(c, "tts")),  # T09: press-to-talk
        "reply_audio": ReplyAudioStore(),  # in memory, one fetch, short TTL
    }
    if getattr(c.settings, "robin_device_scam_llm_enabled", False):  # OFF by default: masked shared text goes to the model provider
        ports["llm"] = _LazyLLM(c)  # can only RAISE a verdict (scamcheck.merge_second_opinion)
    return ports


class _LazyLLM:
    """Resolves the container's LLM at the first call, so a missing key only costs the optional second opinion."""

    def __init__(self, c: Any) -> None:
        self.c = c

    async def complete(self, **kwargs: Any) -> Any:
        return await self.c.get("llm").complete(**kwargs)
