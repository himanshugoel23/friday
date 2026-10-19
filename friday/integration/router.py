"""The front door of the consumer beta: which handler gets a WhatsApp message.

``ConsumerRouter.handle(user, msg)`` is called by the inbound pipeline BEFORE the quotes flow. It
returns True when it consumed the message and False when the pipeline should carry on exactly as it
did before this package existed. Rules that keep the old flows untouched:

* a switch that is off removes its handlers completely (all four default to off; with all four off
  the pipeline never builds this object);
* while the vendor-quotes flow owns the conversation (an active quote conversation, or a message
  that looks like a salon request) every free-text handler stays out; only the consumer buttons
  (``callap:``/``callact:``/``led:``/``bill:``/``life:``) are still answered;
* a message that matches no handler returns False;
* a confident BUSINESS call ("Taj restaurant ko call karke table book karo") is NOT taken: business
  calls keep their approved playbooks.

Order for text: pending call question -> Google -> memory controls -> savings -> new call request
-> "mat poocho"/follow-up reply -> "what is my day" -> "Zomato pe 640" (card question) -> "galat"
-> capture of a life statement ("kal 2 baje interview hai"). Every reply is sent through ``send``.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from friday.calls.contacts import ContactBook
from friday.calls.flow import CallIntake, IntakeState
from friday.calls.orchestrator import CallOrchestrator
from friday.core.clock import Clock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, ReplyButton, User
from friday.integration import copy
from friday.integration.buttons import ButtonRegistry, Handled
from friday.lifestate import copy as life_copy
from friday.lifestate.capture import PendingCapture, capture_message, undo_last
from friday.lifestate.conversation import LifeContextProvider
from friday.lifestate.followups import FollowupScheduler, build_morning_brief
from friday.lifestate.memory import MemoryControls
from friday.lifestate.models import EventKind
from friday.lifestate.ports import BillsPort, CalendarPort
from friday.lifestate.store import LifeStore
from friday.lifestate.sync import (
    GoogleCalendarAdapter,
    check_booking_slot,
    record_booking_from_task,
    sync_calendar,
)
from friday.savings.categories import parse_purchase
from friday.savings.commands import SavingsCommands

log = get_logger(__name__)

Send = Callable[[str, str, Sequence[ReplyButton]], Awaitable[None]]
STATE_TTL = timedelta(minutes=30)

_CALL_VERB = re.compile(
    r"\b(?:phone|call|fone)\s+(?:karke|kar\s*ke|karo|kar\s*do|kardo|karna|kijiye|kijiyega|"
    r"krke|krna|karein|kare|lagao|lagana)\b|"
    r"^\s*(?:please\s+|plz\s+)?(?:call|phone|ring)\s+\w|"
    r"\b(?:ko|se)\s+(?:phone|call|fone)\b|"
    r"\bmissed\s+call\b.{0,30}\b(?:wapas|vapas|call\s*back|callback|jawab)\b",
    re.I,
)
_CANCEL = re.compile(
    r"^\s*(?:cancel|rehne\s+do|chhodo|chodo|nahi\s+karna|ruk\s*jao)\s*[.!]?\s*$", re.I
)
_GOOGLE_CONNECT = re.compile(
    r"\b(?:connect|link|jodo|jod\s*do|jod\s*lo)\b.{0,20}\b(?:google|gmail|calendar)\b|"
    r"\b(?:google|gmail|calendar)\b.{0,12}\b(?:connect|link|jodo|jod\s*do|jod\s*lo)\b",
    re.I,
)
_GOOGLE_DISCONNECT = re.compile(
    r"\b(?:disconnect|unlink|remove|hatao|hata\s*do|hata\s*dena)\b.{0,20}\b(?:google|gmail|calendar)\b|"
    r"\b(?:google|gmail|calendar)\b.{0,12}\b(?:disconnect|unlink|hatao|hata\s*do|hata\s*dena)\b",
    re.I,
)
_GOOGLE_STATUS = re.compile(
    r"\b(?:google|gmail|calendar)\b.{0,12}\b(?:status|connected)\b|"
    r"\bkya\b.{0,12}\b(?:google|gmail|calendar)\b.{0,12}\bjuda\b",
    re.I,
)
_DAY = re.compile(
    r"(?:\bmera\s+din\b|\baaj\s+ka\s+(?:din|schedule|plan)\b|\bwhat(?:'s|\s+is)\s+my\s+day\b|"
    r"\bmy\s+(?:day|schedule)\b|\baaj\s+kya\s+(?:hai|plan|schedule)\b|\bwhat(?:'s|\s+is)\s+today\b)",
    re.I,
)
_GALAT = re.compile(r"^\s*galat\s*[.!]?\s*$", re.I)
_PE = re.compile(r"\b(?:pe|par|on|mein|me)\b", re.I)


@dataclass
class _Timed:
    value: Any
    expires: datetime


class _State:
    """Per-user, in-process, short-lived (30 min) conversation state. Holds a pending number while
    a call question is open, so it lives in memory only, never in the shared cache or a log."""

    def __init__(self, clock: Clock, ttl: timedelta = STATE_TTL) -> None:
        self.clock, self.ttl = clock, ttl
        self._d: dict[str, _Timed] = {}

    def get(self, user_id: str) -> Any | None:
        item = self._d.get(user_id)
        if item is None:
            return None
        if item.expires <= self.clock.now():
            self._d.pop(user_id, None)
            return None
        return item.value

    def set(self, user_id: str, value: Any | None) -> None:
        if value is None:
            self._d.pop(user_id, None)
        else:
            self._d[user_id] = _Timed(value, self.clock.now() + self.ttl)


@dataclass
class CallsParts:
    orchestrator: CallOrchestrator
    intake: CallIntake
    contacts: ContactBook
    jobs: Any  # ConsumerJobs


@dataclass
class LifeParts:
    store: LifeStore
    memory: MemoryControls
    provider: LifeContextProvider
    scheduler: FollowupScheduler
    bills: BillsPort | None = None


@dataclass
class GoogleParts:
    oauth: Callable[[], Any]  # -> GoogleOAuth
    calendar: Callable[[str], Awaitable[CalendarPort | None]]  # user_id -> read-only calendar
    users: Callable[[], Awaitable[list[str]]] = field(default_factory=lambda: _no_users)


async def _no_users() -> list[str]:
    return []


Profile = Callable[[str], Awaitable[tuple[str | None, str]]]  # user_id -> (name, language)


class ConsumerRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Clock,
        send: Send,
        profile: Profile,
        buttons: ButtonRegistry,
        calls: CallsParts | None = None,
        savings: SavingsCommands | None = None,
        life: LifeParts | None = None,
        google: GoogleParts | None = None,
    ) -> None:
        self.settings, self.clock, self.send, self.profile = settings, clock, send, profile
        self.buttons = buttons
        self.calls, self.savings, self.life, self.google = calls, savings, life, google
        self._intake = _State(clock)
        self._capture = _State(clock, timedelta(minutes=10))
        self._edit = _State(clock)  # user -> request id whose plan the next message replaces
        self.last_sync: datetime | None = None
        self.extras: dict[str, Any] = {}  # pieces wiring.attach() registers on the engines

    # ------------------------------------------------------------------ switches
    @property
    def any_on(self) -> bool:
        return bool(self.calls or self.savings or self.life or self.google)

    # ------------------------------------------------------------------ entry point
    async def handle(self, user: User, msg: InboundMessage, quotes: Any = None) -> bool:
        if msg.kind == MessageKind.BUTTON_REPLY and msg.button_id:
            return await self._button(user, msg.button_id)
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        if await self._quotes_own(quotes, user, text):
            return False
        try:
            return await self._text(user, msg, text)
        except Exception as e:  # noqa: BLE001 - the old flows must still get the message
            log.warning("consumer router failed (%s); passing the message on", type(e).__name__)
            return False

    async def _quotes_own(self, quotes: Any, user: User, text: str) -> bool:
        if quotes is None or not getattr(quotes, "enabled", False):
            return False
        try:
            from friday.quotes.parse import looks_like_request

            return bool(
                await quotes.store.active_for_user(user.id) is not None or looks_like_request(text)
            )
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ buttons
    async def _button(self, user: User, button_id: str) -> bool:
        if not self.buttons.owns(button_id):
            return False  # not ours (or its owner is switched off): unchanged behaviour
        res = await self.buttons.dispatch(user.id, button_id)
        if res is not None and (res.text or res.buttons):
            await self.send(user.id, res.text or "", res.buttons)
        return True

    # ------------------------------------------------------------------ text
    async def _text(self, user: User, msg: InboundMessage, text: str) -> bool:
        uid = user.id
        if self.calls and self._edit.get(uid) is not None:
            return await self._edit_turn(user, text)
        if self.calls and self._intake.get(uid) is not None:
            return await self._call_turn(user, msg, text)
        if self.google and await self._google(user, text):
            return True
        if _CALL_VERB.search(text):
            # a call request: ours when the calls switch is on (and it is not a business call);
            # otherwise untouched, so no other handler can mistake "X ko call karo" for an edit
            if self.calls and await self._is_ours(text):
                return await self._call_turn(user, msg, text)
            return False
        if self.life and await self._memory(user, text):
            return True
        if self.savings and (reply := await self.savings.handle(uid, text)) is not None:
            await self.send(uid, reply.text, reply.buttons)
            return True
        if self.life:
            if (r := await self.life.scheduler.handle_reply(uid, text)).handled:
                await self.send(uid, r.text or "", [])
                return True
            if _DAY.search(text):
                return await self._my_day(uid)
        if self.savings and await self._card_question(uid, text):
            return True
        if self.life:
            return await self._capture_turn(uid, text)
        return False

    # ------------------------------------------------------------------ calls
    async def _is_ours(self, text: str) -> bool:
        """A confident BUSINESS call keeps its approved playbook; everything else is ours."""
        assert self.calls is not None
        u = await self.calls.intake.understander.understand(text, now=self.clock.now())
        from friday.calls.models import CalleeKind

        return not (u.draft.callee_kind == CalleeKind.BUSINESS and u.draft.kind_confident)

    async def _call_turn(self, user: User, msg: InboundMessage, text: str) -> bool:
        assert self.calls is not None
        uid = user.id
        state: IntakeState | None = self._intake.get(uid)
        if state is not None and _CANCEL.match(text):
            self._intake.set(uid, None)
            await self.send(uid, copy.line("intake_cancelled", await self._lang(uid)), [])
            return True
        name, lang = await self.profile(uid)
        reply = await self.calls.intake.handle(
            user, text, message_id=msg.provider_message_id or msg.id, state=state,
            user_display_name=name, language=lang if lang in ("hinglish", "en") else None,
        )  # fmt: skip
        self._intake.set(uid, reply.state)
        if reply.text:  # an empty text is a re-delivered message: say nothing twice
            await self.send(uid, reply.text, reply.buttons)
        return True

    def expect_edit(self, user_id: str, request_id: str) -> None:
        """The user tapped Edit: their next message replaces what the call says or asks."""
        self._edit.set(user_id, request_id)

    async def _edit_turn(self, user: User, text: str) -> bool:
        assert self.calls is not None
        uid = user.id
        request_id: str = self._edit.get(uid)
        self._edit.set(uid, None)
        orch = self.calls.orchestrator
        if _CANCEL.match(text):
            await orch.cancel(request_id)
            await self.send(uid, copy.line("intake_cancelled", await self._lang(uid)), [])
            return True
        brief = await orch.store.get_brief(request_id)
        if brief is None:
            return False
        changes: dict[str, Any] = {
            "goal": text,
            "must_say" if brief.must_say else "ask_list": [text],
            "shareable_facts": [text],
        }
        # a new brief version with no approval: a new approval message goes out (new opening,
        # new hash), and a tap on the old message can no longer approve anything
        await orch.apply_edit(request_id, **changes)
        return True

    async def _lang(self, user_id: str) -> str:
        _, lang = await self.profile(user_id)
        return lang if lang in ("hinglish", "en") else copy.DEFAULT_LANGUAGE

    # ------------------------------------------------------------------ Google
    async def _google(self, user: User, text: str) -> bool:
        assert self.google is not None
        if _GOOGLE_DISCONNECT.search(text):
            action = "disconnect"
        elif _GOOGLE_CONNECT.search(text):
            action = "connect"
        elif _GOOGLE_STATUS.search(text):
            action = "status"
        else:
            return False
        lang = await self._lang(user.id)
        from friday.google.oauth import NotConfigured

        oauth = self.google.oauth()
        try:
            if action == "connect":
                start = await oauth.start(user.id)
                out = copy.line("google_connect_link", lang, link=start.link)
            elif action == "disconnect":
                st = await oauth.status(user.id)
                if st.status == "not_connected":
                    out = copy.line("google_disconnect_nothing", lang)
                else:
                    await oauth.disconnect(user.id)
                    out = copy.line("google_disconnected", lang)
            else:
                st = await oauth.status(user.id)
                if st.connected:
                    out = copy.line("google_connected", lang, email=st.email_masked or "-")
                elif st.status == "needs_reconnect":
                    out = copy.line("google_needs_reconnect", lang)
                else:
                    out = copy.line("google_not_connected", lang)
        except NotConfigured:
            out = copy.line("google_not_configured", lang)
        await self.send(user.id, out, [])
        return True

    # ------------------------------------------------------------------ life state
    async def _memory(self, user: User, text: str) -> bool:
        assert self.life is not None
        r = await self.life.memory.handle(user.id, text)
        # "delete everything" and "export" stay with the existing PIN-protected flows
        if not r.handled or r.action in ("delete_prompt", "export"):
            return False
        await self.send(user.id, r.text or "", [])
        return True

    async def _my_day(self, user_id: str) -> bool:
        assert self.life is not None
        brief = await build_morning_brief(
            self.life.store, user_id, self.clock.now(), bills=self.life.bills
        )
        lang = await self._lang(user_id)
        await self.send(user_id, brief.text or copy.line("day_empty", lang), [])
        return True

    async def _capture_turn(self, user_id: str, text: str) -> bool:
        assert self.life is not None
        now = self.clock.now()
        if _GALAT.match(text):
            if await undo_last(self.life.store, user_id, now):
                await self.send(user_id, life_copy.undo_done(), [])
                return True
            return False
        pending: PendingCapture | None = self._capture.get(user_id)
        res = await capture_message(self.life.store, user_id, text, now, pending=pending)
        if res.status == "none":
            if pending is not None:
                self._capture.set(user_id, None)  # the answer was not for us: drop the question
            return False
        self._capture.set(user_id, res.pending)
        await self.send(user_id, res.reply or "", [])
        return True

    # ------------------------------------------------------------------ savings
    async def _card_question(self, user_id: str, text: str) -> bool:
        """ "Zomato pe 640": a short purchase phrase from a user with cards is a card question."""
        assert self.savings is not None
        if len(text.split()) > 8 or not _PE.search(text):
            return False
        p = parse_purchase(text)
        if p.category is None or p.amount_paise is None:
            return False
        if not await self.savings.wallet.list(user_id):
            return False
        reply = await self.savings.which_card(user_id, text)
        await self.send(user_id, reply.text, reply.buttons)
        return True

    # ------------------------------------------------------------------ context for the brain
    async def context_summary(self, user_id: str) -> str | None:
        if not self.life:
            return None
        try:
            return await self.life.provider.context_for(user_id, self.clock.now())
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ booking time proposed
    async def clash_note(self, user_id: str, at: datetime) -> str:
        """A one-line note when a proposed booking time collides with the user's day."""
        if not self.life:
            return ""
        cal = await self.google.calendar(user_id) if self.google else None
        res = await check_booking_slot(
            self.life.store, user_id, at, at + timedelta(hours=1), calendar=cal
        )
        if res.ok:
            return ""
        kind = res.clashes[0].kind if res.clashes else EventKind.OTHER
        return life_copy.clash_note(kind, life_copy.fmt_when(at, self.clock.now()))

    async def on_task_done(self, task: Any) -> None:
        """A booking the task engine made becomes a protected event in the user's day."""
        if self.life:
            await record_booking_from_task(self.life.store, task)

    # ------------------------------------------------------------------ periodic work
    async def periodic(self) -> dict[str, Any]:
        """One pass of everything periodic: the call jobs (run_due, recover_stale, purge_expired)
        and, behind the Google switch, the calendar sync. Cheap and safe to call often."""
        out: dict[str, Any] = {}
        if self.calls:
            out["calls"] = await self.calls.jobs.tick()
        if self.google and self.life:
            out["calendar_sync"] = await self.sync_calendars()
        return out

    async def loop(self, interval_s: float = 30.0) -> None:
        """The periodic loop the runtime starts beside its other loops."""
        import asyncio

        while True:
            try:
                await self.periodic()
            except Exception as e:  # noqa: BLE001 - a bad pass never kills the loop
                log.warning("consumer periodic pass failed (%s)", type(e).__name__)
            await asyncio.sleep(interval_s)

    async def sync_calendars(self, *, every: timedelta = timedelta(minutes=15)) -> int:
        """Import each connected user's calendar into their life state (read-only, windowed)."""
        assert self.google is not None and self.life is not None
        now = self.clock.now()
        if self.last_sync is not None and now - self.last_sync < every:
            return 0
        self.last_sync = now
        done = 0
        for uid in await self.google.users():
            cal = await self.google.calendar(uid)
            if cal is None:
                continue
            report = await sync_calendar(self.life.store, uid, cal, now)
            done += 0 if report.error else 1
        return done


def calendar_port(client: object) -> CalendarPort:
    """A read-only calendar for the life state from a ``CalendarClient``."""
    return GoogleCalendarAdapter(client)  # type: ignore[return-value]


def handled(text: str | None = None, buttons: Sequence[ReplyButton] = ()) -> Handled:
    return Handled(text, list(buttons))
