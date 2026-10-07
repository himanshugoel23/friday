"""Business call-backs, missed calls and business replies (BRIEF E30-35).

Inputs (no imports from friday.voice / friday.tasks):

* the voice side publishes bus events named ``InboundCallReceived`` /
  ``MissedCallReceived`` (fields ``from_phone``, ``to_number`` / ``to_phone`` /
  ``friday_number``, optional ``provider_call_id`` / ``call_id``); we subscribe to the base
  ``Event`` and filter by class name until the core events land (CORE_CHANGES);
* the inbound message pipeline calls ``on_business_message`` for messages from
  business numbers.

Each contact is matched against call memory (``repos.calls.match``), recorded
(``inbound_contacts``) and handed to the task engine through duck-typed methods:

    handle_business_callback(match, contact)   answered inbound call (resume task)
    handle_missed_call(match, contact)         missed call (call back, notify after N)
    handle_business_message(msg, match)        WhatsApp/SMS reply from a business

Safety (E33/E34): an UNMATCHED contact never gets user/task details;
``safe_context`` returns details only for a MATCHED caller whose number is the
called business number, and only the requester's first name + the task goal.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from friday.core.container import ComponentNotAvailable
from friday.core.events import Event
from friday.core.logging import get_logger, mask_phone
from friday.core.models import InboundMessage, normalize_phone
from friday.db.repositories import CallbackMatch, InboundContact, InboundKind, MatchStatus

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

INBOUND_CALL_EVENTS = {"InboundCallReceived", "InboundCall", "BusinessCallReceived"}
MISSED_CALL_EVENTS = {"MissedCallReceived", "MissedCall"}

UNMATCHED_GREETING = (
    "Hi, this is Friday, an AI assistant. I couldn't find what this is about. "
    "May I have your name, what it's regarding, and a number to call back?"
)


class CallbackService:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.repos = c.repos
        self.clock = c.clock
        self.settings = c.settings

    # ------------------------------------------------------------------ wiring
    def subscribe(self) -> None:
        self.c.bus.subscribe(Event, self._on_event)

    def unsubscribe(self) -> None:
        self.c.bus.unsubscribe(Event, self._on_event)

    async def _on_event(self, event: Event) -> None:
        name = type(event).__name__
        if name not in INBOUND_CALL_EVENTS and name not in MISSED_CALL_EVENTS:
            return
        from_phone = getattr(event, "from_phone", None)
        if not from_phone:
            return
        # Field names differ between producers: accept both spellings defensively.
        friday_number = (
            getattr(event, "to_number", None)
            or getattr(event, "to_phone", None)
            or getattr(event, "friday_number", None)
        )
        provider_ref = getattr(event, "provider_call_id", None)
        call_id = getattr(event, "call_id", None) or provider_ref
        await self.on_inbound_call(
            from_phone,
            friday_number,
            answered=name in INBOUND_CALL_EVENTS,
            provider_ref=provider_ref or call_id,
            call_id=call_id,
        )

    def _engine(self) -> Any:
        try:
            return self.c.get("task_engine")
        except ComponentNotAvailable:
            return None

    async def _engine_call(self, names: tuple[str, ...], *args: Any) -> bool:
        engine = self._engine()
        for name in names:
            fn = getattr(engine, name, None) if engine is not None else None
            if callable(fn):
                res = fn(*args)
                if inspect.isawaitable(res):
                    await res
                return True
        return False

    def _norm(self, phone: str) -> str:
        return normalize_phone(phone, self.settings.default_country_code)

    # ------------------------------------------------------------------ calls
    async def match(self, from_phone: str, friday_number: str | None = None) -> CallbackMatch:
        """Side-effect-free lookup (the voice router may call it via c.repos.calls too)."""
        return await self.repos.calls.match(
            self._norm(from_phone), friday_number=self._maybe_norm(friday_number)
        )

    def _maybe_norm(self, phone: str | None) -> str | None:
        if not phone:
            return None
        try:
            return self._norm(phone)
        except ValueError:
            return phone

    async def on_inbound_call(
        self,
        from_phone: str,
        friday_number: str | None,
        *,
        answered: bool,
        provider_ref: str | None = None,
        call_id: str | None = None,
    ) -> tuple[CallbackMatch, InboundContact]:
        match = await self.match(from_phone, friday_number)
        kind = InboundKind.CALL if answered else InboundKind.MISSED_CALL
        contact = await self.repos.calls.record_inbound(
            kind, match, channel="voice", provider_ref=provider_ref, call_id=call_id
        )
        await self.repos.audit.log(
            f"inbound.{kind.value}",
            user_id=match.user_id,
            actor="system",
            subject_id=match.task_id,
            status=match.status.value,
        )
        handled = False
        if answered and match.status == MatchStatus.UNMATCHED:
            # E33: greet, take a message, reveal nothing about any user.
            log.info("unmatched inbound call from %s (ops)", mask_phone(match.from_phone))
            handled = await self._engine_call(("handle_unknown_caller",), match, contact)
        elif answered:
            handled = await self._engine_call(
                ("handle_business_callback", "resume_from_callback"), match, contact
            )
        else:
            # The engine logs unmatched missed calls itself (no call-back, no details).
            handled = await self._engine_call(
                ("handle_missed_call", "on_missed_call"), match, contact
            )
        if handled:
            await self.repos.calls.mark_handled(contact.id)
        return match, contact

    # ------------------------------------------------------------------ messages
    async def on_business_message(
        self, msg: InboundMessage, match: CallbackMatch | None = None
    ) -> CallbackMatch:
        match = match or await self.match(msg.from_phone)
        contact = await self.repos.calls.record_inbound(
            InboundKind.MESSAGE,
            match,
            channel=msg.channel.value,
            provider_ref=msg.provider_message_id,
        )
        if await self._engine_call(
            ("handle_business_message", "handle_business_reply"), msg, match
        ):
            await self.repos.calls.mark_handled(contact.id)
        return match

    # ------------------------------------------------------------------ safe context
    async def safe_context(self, match: CallbackMatch) -> dict[str, str]:
        """What Friday may say to this caller about the earlier call. Empty unless the
        match is unique AND the caller ID is the number we called for that task."""
        if match.status != MatchStatus.MATCHED or not match.task_id:
            return {}
        task = await self.repos.tasks.get(match.task_id)
        if task is None:
            return {}
        called = {m.business_phone for m in match.candidates if m.task_id == task.id}
        target_phone = task.target.phone if task.target else task.spec.business_phone
        if match.from_phone not in called or (target_phone and target_phone != match.from_phone):
            return {}
        name = (task.spec.on_behalf_of or "").split(" ")[0] or "our user"
        return {"on_behalf_of": name, "about": task.spec.goal}

    @staticmethod
    def greeting(context: dict[str, str]) -> str:
        if not context:
            return UNMATCHED_GREETING
        return (
            "Hi, this is Friday, an AI assistant. We called you earlier on behalf of "
            f"{context['on_behalf_of']} about: {context['about']}."
        )
