# ruff: noqa: E501
"""One forwarded call, from the webhook to the WhatsApp summary; plus buttons and "what did I miss?".

    handle_call(port, caller, redirecting_raw)
        resolve the user (redirecting number) -> kill switch -> block list -> caps
        -> ReceptionistFlow (<= 90 s) -> classify (rules first) -> store -> notify

Notification rules: URGENT is sent at once (even in quiet hours) with buttons Call back / Ignore /
Block; NORMAL and SPAM wait for the morning digest (sent once the user's quiet hours end). A call
with no message is still reported ("X called and left no message"). Logs carry masked numbers only.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from friday.core.clock import Clock, to_ist
from friday.core.logging import get_logger, mask_phone
from friday.core.models import ReplyButton
from friday.liveagent.ports import CallDropped, TelephonyPort
from friday.receptionist import copy, lines
from friday.receptionist.classify import Classifier
from friday.receptionist.flow import ReceptionistFlow
from friday.receptionist.identify import RedirectResolver, Resolution, Route
from friday.receptionist.models import (
    CallCapture,
    CallOutcomeKind,
    Classification,
    MessageStatus,
    ReceptionistConfig,
    StoredMessage,
    Urgency,
)
from friday.receptionist.store import ReceptionistStore

log = get_logger(__name__)

Sender = Callable[[str, str, list[ReplyButton]], Awaitable[None]]
BUTTON_PREFIX = "rcp"
MISSED_RE = (
    "what did i miss", "what i missed", "what have i missed", "kya miss kiya", "kya miss hua",
    "kis kis ka call aaya", "kaun kaun call", "miss call", "missed call", "miss ho gaya kya",
    "mere calls", "kisne call kiya", "kisne phone kiya", "morning friday",
)  # fmt: skip


class CalendarPort(Protocol):
    async def events_today(self, user_id: str, now: datetime) -> list[str]: ...


class CallReport:
    """What a handled call produced (for the caller of ``handle_call``, tests and the simulator)."""

    def __init__(
        self,
        capture: CallCapture,
        classification: Classification | None,
        message: StoredMessage | None,
        route: Route,
        spoken: list[tuple[str, str]],
        notified: bool = False,
    ) -> None:
        self.capture, self.classification, self.message = capture, classification, message
        self.route, self.spoken, self.notified = route, spoken, notified


class ReceptionistService:
    def __init__(
        self,
        store: ReceptionistStore,
        classifier: Classifier,
        send: Sender,
        clock: Clock,
        resolver: RedirectResolver,
        *,
        paused: Callable[[], bool] = lambda: False,
        per_user_per_day: int = 40,
        per_caller_per_hour: int = 3,
        max_call_s: float = 90.0,
        snippet_days: int = 30,
        calendar: CalendarPort | None = None,
        mono: Callable[[], float] = time.monotonic,
        listen_s: float = 7.0,
        spam_shared_threshold: int = 5,
    ) -> None:
        self.store, self.classifier, self.send, self.clock = store, classifier, send, clock
        self.resolver, self.paused = resolver, paused
        self.per_user_per_day, self.per_caller_per_hour = per_user_per_day, per_caller_per_hour
        self.max_call_s, self.snippet_days = max_call_s, snippet_days
        self.calendar, self.mono, self.listen_s = calendar, mono, listen_s
        self.spam_shared_threshold = spam_shared_threshold

    # ================================================================== a forwarded call
    async def claims(
        self,
        redirecting_raw: str | None,
        caller: str | None,
        call_fields: Mapping[str, str] | None = None,
        dialled: str | None = None,
    ) -> Resolution:
        """Is this a forwarded call for us? NOT_FORWARDED -> the front door keeps it."""
        return await self.resolver.resolve(redirecting_raw, caller, call_fields, dialled)

    async def handle_call(
        self,
        port: TelephonyPort,
        caller_number: str | None,
        redirecting_raw: str | None,
        *,
        resolution: Resolution | None = None,
        call_fields: Mapping[str, str] | None = None,
    ) -> CallReport | None:
        res = resolution or await self.resolver.resolve(redirecting_raw, caller_number, call_fields)
        if res.route == Route.NOT_FORWARDED:
            return None
        now = self.clock.now()
        if res.route == Route.TEST_RING:
            return await self._test_ring(port, res, now)
        caller = caller_number if caller_number and caller_number.lstrip("+").isdigit() else None
        cfg = ReceptionistConfig()
        if res.route == Route.MATCHED and res.user_id:
            cfg = (await self.store.get_config(res.user_id)) or ReceptionistConfig(enabled=True)
        log.info(
            "receptionist: forwarded call route=%s caller=%s", res.route.value, mask_phone(caller)
        )
        # ---- refusals that speak one fixed line and store nothing
        refusal = await self._refusal(res, caller, now)
        if refusal is not None:
            return await self._refuse(port, cfg, refusal, res, caller, now)
        # ---- the conversation
        generic = res.route != Route.MATCHED
        flow = ReceptionistFlow(
            port, cfg, generic=generic, now=self.mono, max_call_s=self.max_call_s,
            listen_s=self.listen_s,
        )  # fmt: skip
        try:
            cap = await flow.run()
        finally:
            with contextlib.suppress(Exception):  # the line may already be gone
                await port.hangup()
        return await self._finish(cap, flow.spoken, cfg, res, caller, now)

    async def _test_ring(self, port: TelephonyPort, res: Resolution, now: datetime) -> CallReport:
        """The user's own test ring, declined and forwarded back from Friday's pool number: nothing is
        spoken or stored; the user is told (existing text ``test.confirmed``) that forwarding works."""
        with contextlib.suppress(Exception):  # the line may already be gone
            await port.hangup()
        cap = CallCapture(outcome=CallOutcomeKind.NO_MESSAGE)
        notified = False
        if not self.paused() and res.user_id:
            cfg = await self.store.get_config(res.user_id) or ReceptionistConfig()
            if not cfg.forwarding_verified:
                cfg.forwarding_verified = True
                await self.store.save_config(res.user_id, cfg)
            lang = "en" if cfg.language == "en" else "hinglish"
            try:
                await self.send(res.user_id, copy.t("test.confirmed", lang), [])
                notified = True
            except Exception as e:  # noqa: BLE001
                log.warning("receptionist: test-ring confirmation failed (%s)", type(e).__name__)
        log.info("receptionist: test ring recognised, forwarding works")
        return CallReport(cap, None, None, Route.TEST_RING, [], notified)

    async def _refusal(self, res: Resolution, caller: str | None, now: datetime) -> str | None:
        if self.paused():
            return "blocked.end"  # kill switch: answer politely, store and send nothing
        if res.route == Route.REFUSED:
            return "blocked.end"  # receptionist-only number, nobody identified: cannot take a message
        if res.route == Route.DISABLED:
            return "blocked.end"
        if res.route == Route.MATCHED and res.user_id:
            if await self.store.is_blocked(res.user_id, caller):
                return "blocked.end"
            if await self.store.count_for_user(res.user_id, now - timedelta(days=1)) >= self.per_user_per_day:
                return "cap.end"
        if await self.store.count_from_caller(caller, now - timedelta(hours=1)) >= self.per_caller_per_hour:
            return "cap.end"
        return None

    async def _refuse(
        self, port: TelephonyPort, cfg: ReceptionistConfig, key: str, res: Resolution,
        caller: str | None, now: datetime,
    ) -> CallReport:  # fmt: skip
        text = lines.say(key, cfg.language)
        try:
            from friday.liveagent.contracts import CallLanguage

            await port.speak(text, CallLanguage(cfg.language))
        except CallDropped:
            pass
        finally:
            with contextlib.suppress(Exception):
                await port.hangup()
        cap = CallCapture(outcome=CallOutcomeKind.BLOCKED if key == "blocked.end" else CallOutcomeKind.CAP_REACHED)
        msg = None
        # a blocked / capped call is counted (so caps hold) but carries no content and no push
        if res.route == Route.MATCHED and res.user_id and not self.paused():
            msg = await self.store.add_message(
                StoredMessage(
                    user_id=res.user_id, caller_number=caller, outcome=cap.outcome,
                    urgency=Urgency.SPAM if key == "blocked.end" else Urgency.NORMAL,
                    status=MessageStatus.IGNORED, created_at=now,
                )  # fmt: skip
            )
        return CallReport(cap, None, msg, res.route, [(key, text)])

    async def _finish(
        self, cap: CallCapture, spoken: list[tuple[str, str]], cfg: ReceptionistConfig,
        res: Resolution, caller: str | None, now: datetime,
    ) -> CallReport:  # fmt: skip
        if res.route != Route.MATCHED or not res.user_id:
            # unrouted: kept (no user) for a few days for ops; nobody is notified, nothing guessed
            msg = await self.store.add_message(
                StoredMessage(
                    user_id=None, caller_number=caller, caller_name=cap.caller_name, reason=cap.reason,
                    callback_number=cap.callback_number, outcome=CallOutcomeKind.UNROUTED,
                    urgency=Urgency.NORMAL, status=MessageStatus.IGNORED,
                    duration_s=cap.duration_s, created_at=now,
                )  # fmt: skip
            )
            return CallReport(cap, None, msg, res.route, spoken)
        cls = await self.classifier.classify(cap, caller, cfg)
        if caller:  # shared anonymised spam table (keyed hash + count, no user id)
            if cls.urgency == Urgency.SPAM:
                await self.store.record_spam(caller)
            elif (
                cls.urgency == Urgency.NORMAL
                and not cls.known_contact
                and await self.store.spam_reports(caller) >= self.spam_shared_threshold
            ):
                cls = cls.model_copy(
                    update={"urgency": Urgency.SPAM, "reasons": [*cls.reasons, "number reported as spam on several Friday lines"]}
                )
        if cls.urgency == Urgency.SPAM and cap.outcome == CallOutcomeKind.MESSAGE:
            cap.outcome = CallOutcomeKind.SPAM_ENDED
        msg = await self.store.add_message(
            StoredMessage(
                user_id=res.user_id, caller_number=caller, caller_name=cap.caller_name,
                reason=cap.reason, urgency=cls.urgency, snippet=cap.snippet,
                callback_number=cap.callback_number, outcome=cap.outcome, status=MessageStatus.NEW,
                known_contact_name=cls.contact_name, duration_s=cap.duration_s, created_at=now,
                classification_reasons=cls.reasons,
            )  # fmt: skip
        )
        notified = False
        if cls.urgency == Urgency.URGENT:
            notified = await self._push(res.user_id, msg, cfg)
        return CallReport(cap, cls, msg, res.route, spoken, notified)

    # ================================================================== notifications
    def _who(self, m: StoredMessage, lang: str) -> str:
        if m.known_contact_name:
            return copy.t("who.contact", lang, contact=m.known_contact_name)
        if m.caller_name and m.caller_number:
            return copy.t("who.named", lang, name=m.caller_name, number=m.caller_number)
        if m.caller_name:
            return m.caller_name
        return m.caller_number or copy.t("who.unknown", lang)

    def _when(self, m: StoredMessage) -> str:
        return to_ist(m.created_at).strftime("%I:%M %p").lstrip("0") if m.created_at else ""

    def summary_text(self, m: StoredMessage, lang: str = "hinglish") -> str:
        head = {Urgency.URGENT: "urgent.head", Urgency.SPAM: "spam.head"}.get(m.urgency, "normal.head")
        out = [copy.t(head, lang, who=self._who(m, lang), when=self._when(m))]
        if m.reason:
            out.append(copy.t("line.reason", lang, reason=m.reason))
        elif m.outcome == CallOutcomeKind.MESSAGE and m.status != MessageStatus.IGNORED and not m.snippet:
            out.append(copy.t("line.declined", lang))
        else:
            out.append(copy.t("line.no_message", lang))
        if m.snippet and m.snippet != m.reason:
            out.append(copy.t("line.snippet", lang, snippet=m.snippet))
        if m.callback_number:
            out.append(copy.t("line.callback_number", lang, number=m.callback_number))
        if m.caller_number and not m.known_contact_name:
            out.append(copy.t("line.number", lang, number=m.caller_number))
        if m.urgency != Urgency.NORMAL and m.classification_reasons:
            out.append(copy.t("line.why", lang, why="; ".join(m.classification_reasons[:2])))
        return "\n".join(out)

    def buttons(self, m: StoredMessage, lang: str = "hinglish") -> list[ReplyButton]:
        return [
            ReplyButton(id=f"{BUTTON_PREFIX}:{m.id}:{a}", title=copy.button_title(a, lang))
            for a in ("callback", "ignore", "block")
        ]

    async def _push(self, user_id: str, m: StoredMessage, cfg: ReceptionistConfig) -> bool:
        lang = "en" if cfg.language == "en" else "hinglish"
        try:
            await self.send(user_id, self.summary_text(m, lang), self.buttons(m, lang))
        except Exception as e:  # noqa: BLE001 - a failed send is retried by the digest, never lost
            log.warning("receptionist: summary send failed (%s)", type(e).__name__)
            return False
        await self.store.set_status(user_id, m.id, MessageStatus.NOTIFIED, notified_at=self.clock.now())
        return True

    async def digest_text(self, user_id: str, lang: str, msgs: Sequence[StoredMessage]) -> str | None:
        shown = [m for m in msgs if m.urgency != Urgency.SPAM and m.outcome != CallOutcomeKind.BLOCKED]
        spam = [m for m in msgs if m.urgency == Urgency.SPAM and m.outcome != CallOutcomeKind.BLOCKED]
        if not shown and not spam:
            return None
        out = [copy.t("digest.head", lang, n=len(shown) + len(spam))]
        for m in shown:
            out.append(copy.t("digest.item", lang, when=self._when(m), who=self._who(m, lang),
                              reason=m.reason or copy.t("line.no_message", lang)))  # fmt: skip
        if spam:
            names = ", ".join(self._who(m, lang) for m in spam[:3])
            out.append(copy.t("digest.spam", lang, n=len(spam), names=names))
        return "\n".join(out)

    async def tick(self, user_ids: Sequence[str] | None = None) -> int:
        """Morning digest: for each enabled user whose quiet hours are over, send what is waiting
        (NEW normal/spam messages) once, then mark it notified. Also purges expired data."""
        now = self.clock.now()
        sent = 0
        for uid in user_ids if user_ids is not None else await self._enabled_users():
            cfg = await self.store.get_config(uid)
            if cfg is None or not cfg.enabled or cfg.quiet_hours.contains(to_ist(now).hour):
                continue
            waiting = await self.store.list_messages(uid, statuses=(MessageStatus.NEW,))
            lang = "en" if cfg.language == "en" else "hinglish"
            text = await self.digest_text(uid, lang, waiting)
            if text is None:
                continue
            try:
                await self.send(uid, text, [])
            except Exception as e:  # noqa: BLE001
                log.warning("receptionist: digest send failed (%s)", type(e).__name__)
                continue
            for m in waiting:
                await self.store.set_status(uid, m.id, MessageStatus.NOTIFIED, notified_at=now)
            sent += 1
        await self.store.purge_expired(now, self.snippet_days)
        return sent

    async def _enabled_users(self) -> list[str]:
        fn = getattr(self.store, "enabled_user_ids", None)
        return list(await fn()) if fn else []

    async def loop(self, every_s: float = 300.0) -> None:  # pragma: no cover - runtime plumbing
        import asyncio

        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("receptionist tick failed")
            await asyncio.sleep(every_s)

    # ================================================================== buttons
    async def on_button(self, user_id: str, button_id: str) -> tuple[str, list[ReplyButton]] | None:
        """``rcp:<message id>:<callback|ignore|block>``. Not ours -> None. Stale or someone
        else's message -> a short 'no longer available' reply (never another user's data)."""
        parts = (button_id or "").split(":")
        if len(parts) != 3 or parts[0] != BUTTON_PREFIX:
            return None
        _, mid, action = parts
        cfg = await self.store.get_config(user_id) or ReceptionistConfig()
        lang = "en" if cfg.language == "en" else "hinglish"
        m = await self.store.get_message(user_id, mid)
        if m is None or action not in {"callback", "ignore", "block"}:
            return copy.t("reply.stale", lang), []
        number = m.callback_number or m.caller_number
        if action == "callback":
            await self.store.set_status(user_id, mid, MessageStatus.CALLED_BACK)
            if not number:
                return copy.t("reply.stale", lang), []
            return copy.t("reply.callback", lang, number=number), []
        if action == "ignore":
            await self.store.set_status(user_id, mid, MessageStatus.IGNORED)
            return copy.t("reply.ignore", lang), []
        if m.caller_number:
            await self.store.block(user_id, m.caller_number)
        await self.store.set_status(user_id, mid, MessageStatus.BLOCKED)
        return copy.t("reply.block", lang, number=m.caller_number or number or ""), []

    # ================================================================== "what did I miss?"
    def is_missed_question(self, text: str) -> bool:
        t = " ".join((text or "").lower().split())
        return any(k in t for k in MISSED_RE)

    async def _since(self, user_id: str, now: datetime) -> list[StoredMessage]:
        msgs = await self.store.list_messages(
            user_id, since=now - timedelta(days=2), statuses=(MessageStatus.NEW, MessageStatus.NOTIFIED)
        )
        return [m for m in msgs if m.outcome != CallOutcomeKind.BLOCKED]

    async def missed_text(self, user_id: str, lang: str = "hinglish") -> str:
        now = self.clock.now()
        msgs = await self._since(user_id, now)
        if not msgs:
            return copy.t("missed.none", lang)
        counts = {u: sum(1 for m in msgs if m.urgency == u) for u in Urgency}
        out = [copy.t("missed.head", lang, n=len(msgs), urgent=counts[Urgency.URGENT],
                      normal=counts[Urgency.NORMAL], spam=counts[Urgency.SPAM])]  # fmt: skip
        for m in sorted(msgs, key=lambda x: (x.urgency != Urgency.URGENT, x.created_at or now)):
            if m.urgency == Urgency.SPAM:
                continue
            out.append(copy.t("missed.item", lang, when=self._when(m), who=self._who(m, lang),
                              reason=m.reason or copy.t("line.no_message", lang)))  # fmt: skip
        events = await self._calendar(user_id, now)
        if events:
            out.append(copy.t("missed.calendar", lang, events="; ".join(events[:4])))
        return "\n".join(out)

    async def missed_spoken(self, user_id: str, lang: str = "hinglish") -> str:
        """A short version for calling Friday: counts, then the urgent ones by name and reason.
        At most two urgent items are read out; the full list goes to WhatsApp."""
        now = self.clock.now()
        msgs = await self._since(user_id, now)
        if not msgs:
            return copy.t("spoken.none", lang)
        urgent = [m for m in msgs if m.urgency == Urgency.URGENT]
        normal = [m for m in msgs if m.urgency == Urgency.NORMAL]
        spam = [m for m in msgs if m.urgency == Urgency.SPAM]
        u_part = ""
        for i, m in enumerate(urgent[:2]):
            who = m.known_contact_name or m.caller_name or copy.t("who.unknown", lang)
            reason = " ".join((m.reason or "").split()[:10]) or copy.t("line.no_message", lang)
            u_part += copy.t("spoken.urgent", lang, n=1 if i else len(urgent), who=who, reason=reason)
        out = copy.t(
            "spoken.head", lang, n=len(msgs), urgent_part=u_part,
            normal_part=copy.t("spoken.normal", lang, n=len(normal)) if normal else "",
            spam_part=copy.t("spoken.spam", lang, n=len(spam)) if spam else "",
        )  # fmt: skip
        return (out + copy.t("spoken.more", lang)).strip()

    async def _calendar(self, user_id: str, now: datetime) -> list[str]:
        if self.calendar is None:
            return []
        try:
            return await self.calendar.events_today(user_id, now)
        except Exception:  # noqa: BLE001 - a calendar failure never blocks the answer
            return []

    async def handle_text(self, user_id: str, text: str) -> bool:
        """WhatsApp text 'what did I miss?' -> the full list. True when handled."""
        if not self.is_missed_question(text):
            return False
        cfg = await self.store.get_config(user_id) or ReceptionistConfig()
        await self.send(user_id, await self.missed_text(user_id, "en" if cfg.language == "en" else "hinglish"), [])
        return True

    async def set_config(self, user_id: str, cfg: ReceptionistConfig) -> None:
        await self.store.save_config(user_id, cfg)

    def status_text(self, cfg: ReceptionistConfig, lang: str = "hinglish") -> str:
        return copy.t("status.on" if cfg.enabled else "status.off", lang, rings=cfg.rings, cancel="##002#")

