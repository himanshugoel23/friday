"""Business call-backs, missed calls and business replies (BRIEF E30-35).

Inputs (no imports from friday.voice / friday.tasks):

* the voice side publishes ``core.events.InboundCallReceived`` /
  ``MissedCallReceived`` (``from_phone``, ``to_number``, ``provider_call_id``);
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
import re
from typing import TYPE_CHECKING, Any

from friday.core.container import ComponentNotAvailable
from friday.core.events import Event, InboundCallReceived, MissedCallReceived
from friday.core.logging import get_logger, mask_phone
from friday.core.models import InboundMessage, TaskType, normalize_phone
from friday.db.repositories import CallbackMatch, InboundContact, InboundKind, MatchStatus

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

# SECURITY-29: a minimised, non-sensitive label instead of ``spec.goal`` (which may
# carry health details, names, addresses).
_TYPE_LABELS: dict[TaskType, str] = {
    TaskType.BOOKING: "a booking",
    TaskType.ENQUIRY: "an enquiry",
    TaskType.RESCHEDULE: "a booking change",
    TaskType.CANCEL_BOOKING: "a cancellation",
    TaskType.RECONFIRM: "a booking confirmation",
    TaskType.RUNNING_LATE: "a booking",
    TaskType.ORDER: "an order",
    TaskType.STOCK_HUNT: "an availability check",
    TaskType.SERVICE_COORDINATION: "a service visit",
    TaskType.STATUS_CHASE: "a status check",
    TaskType.COMPLAINT: "a complaint",
    TaskType.RENTAL_HUNT: "a rental enquiry",
    TaskType.QUOTE: "a quote",
    TaskType.HEALTHCARE: "an appointment",
    TaskType.RECURRING_BOOKING: "a regular booking",
    TaskType.WELLBEING_CHECKIN: "a check-in",
    TaskType.CUSTOMER_CARE: "a service request",
    TaskType.HOTEL_BOOKING: "a room booking",
    TaskType.DISCOVERY: "an enquiry",
}
_SAFE_CATEGORY = re.compile(r"^[a-z][a-z /&-]{1,30}$")
_SENSITIVE_CATEGORY = re.compile(r"(clinic|doctor|hospital|lab|diagnos|pharma|medic|health|therap)")


def task_label(task_type: TaskType, category: str | None = None) -> str:
    """'a salon booking' / 'an appointment' - never the goal text, never medical words."""
    base = _TYPE_LABELS.get(task_type, "a request")
    cat = (category or "").strip().lower()
    if not cat or not _SAFE_CATEGORY.match(cat) or _SENSITIVE_CATEGORY.search(cat):
        return base
    noun = base.split(" ", 1)[1]
    article = "an" if cat[0] in "aeiou" else "a"
    return f"{article} {cat} {noun}"


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
        # The front door (friday.voice.frontdoor.FrontDoor), set by the Runtime. Duck-typed:
        # classify(phone, match) -> Decision, serve(decision, ref, phone, to_number),
        # reject_unparsable(ref). None = every answered call takes the business call-back path.
        self.front_door: Any = None

    # ------------------------------------------------------------------ wiring
    def subscribe(self) -> None:
        self.c.bus.subscribe(InboundCallReceived, self._on_inbound)
        self.c.bus.subscribe(MissedCallReceived, self._on_missed)
        if self.front_door is not None:
            self.front_door.subscribe()

    def unsubscribe(self) -> None:
        self.c.bus.unsubscribe(InboundCallReceived, self._on_inbound)
        self.c.bus.unsubscribe(MissedCallReceived, self._on_missed)
        if self.front_door is not None:
            self.front_door.unsubscribe()

    async def _on_inbound(self, event: InboundCallReceived) -> None:
        await self._from_event(event, answered=True)

    async def _on_missed(self, event: MissedCallReceived) -> None:
        await self._from_event(event, answered=False)

    async def _from_event(self, event: Event, *, answered: bool) -> None:
        from_phone = getattr(event, "from_phone", None)
        if not from_phone:
            return
        ref = getattr(event, "provider_call_id", None)
        try:
            await self.on_inbound_call(
                from_phone,
                getattr(event, "to_number", None),
                answered=answered,
                provider_ref=ref,
                call_id=ref,
            )
        except ValueError:  # "anonymous" / unparsable caller ID: nothing to match
            log.info("inbound call with unparsable caller id ignored")
            if answered and self.front_door is not None and getattr(self.front_door, "enabled", False):
                await self.front_door.reject_unparsable(ref)  # cheap fixed message, then hang up

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
        if answered and self.front_door is not None and getattr(self.front_door, "enabled", False):
            # Front door: classify the caller (user / business / unknown). Business call-backs
            # ("legacy") fall through to the unchanged path below.
            decision = await self.front_door.classify(match.from_phone, match)
            if decision.route != "legacy":
                await self.repos.audit.log(
                    "inbound.front_door",
                    user_id=decision.user_id,
                    actor="system",
                    kind=decision.kind.value,
                    route=decision.route,
                    reason=decision.reason or None,
                )
                await self.front_door.serve(
                    decision, provider_ref or call_id, match.from_phone, match.friday_number
                )
                await self.repos.calls.mark_handled(contact.id)
                return match, contact
        handled = False
        if answered and match.status == MatchStatus.UNMATCHED:
            # E33: greet, take a message, reveal nothing about any user.
            log.info("unmatched inbound call from %s (ops)", mask_phone(match.from_phone))
            handled = await self._engine_call(("handle_unknown_caller",), match, contact)
        elif answered:
            handled = await self._engine_call(("handle_business_callback",), match, contact)
        else:
            # The engine logs unmatched missed calls itself (no call-back, no details).
            handled = await self._engine_call(("handle_missed_call",), match, contact)
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
        if await self._engine_call(("handle_business_message",), msg, match):
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
        return {"on_behalf_of": name, "about": task_label(task.type, task.spec.category)}

    @staticmethod
    def greeting(context: dict[str, str]) -> str:
        if not context:
            return UNMATCHED_GREETING
        return (
            "Hi, this is Friday, an AI assistant. We called you earlier on behalf of "
            f"{context['on_behalf_of']} about: {context['about']}."
        )
