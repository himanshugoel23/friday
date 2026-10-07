"""Simple in-process async event bus + the shared event types.

Used for decoupled, NON-CRITICAL notifications ("a call turn happened", "task
status changed") - audit mirror, simulator UI, metrics. NOT for request/response and
NOT for anything that must survive a crash or run on another process: task steps,
calls, retries, scheduled call-backs, nudges and outbound messages go through the
durable ``JobQueue`` / outbox (friday.core.scale, docs/ARCHITECTURE.md section 10).

    bus = EventBus()
    bus.subscribe(TaskStatusChanged, handler)      # async def handler(event) -> None
    await bus.publish(TaskStatusChanged(...))

Delivery: handlers for the event's class AND its base classes run concurrently;
``publish`` awaits them all. A failing handler is logged and never breaks the
publisher or other handlers.

Owner: Engineering Manager (core). New event classes: add them in your own package
by subclassing ``Event`` (no core change needed); the ones below are shared.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from friday.core.clock import utcnow
from friday.core.logging import get_logger
from friday.core.models import (
    CallOutcome,
    Language,
    CallTurn,
    InboundMessage,
    MidCallQuestion,
    OutboundMessage,
    TaskStatus,
    UserAnswer,
    new_id,
)

log = get_logger(__name__)

E = TypeVar("E", bound="Event")
Handler = Callable[[Any], Awaitable[None]]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=new_id)
    at: datetime = Field(default_factory=utcnow)


class MessageReceived(Event):
    message: InboundMessage


class MessageSent(Event):
    message: OutboundMessage
    ok: bool = True


class TaskStatusChanged(Event):
    task_id: str
    user_id: str
    old: TaskStatus | None
    new: TaskStatus


class CallStarted(Event):
    task_id: str
    call_id: str
    to_phone: str
    provider: str


class CallTurnRecorded(Event):
    task_id: str
    call_id: str
    turn: CallTurn


class MidCallQuestionAsked(Event):
    question: MidCallQuestion
    user_id: str | None = None


class UserAnswerReceived(Event):
    answer: UserAnswer


class CallFinished(Event):
    task_id: str
    call_id: str
    outcome: CallOutcome


# ------------------------------------------------------------------ voice (merged from
# friday/voice/events.py; that module re-exports these for backward compatibility)


class InboundCallReceived(Event):
    """Someone called a Friday number; the call is ANSWERED and parked. The backend
    matches ``from_phone`` (+ ``to_number``) to call memory and claims the leg with
    ``telephony.take_inbound(provider_call_id)`` -> ``call_runner.run_inbound(...)``."""

    from_phone: str  # caller ID (E.164; may be "anonymous")
    to_number: str | None = None  # the Friday number that was dialled
    provider_call_id: str | None = None
    provider: str = "unknown"
    business_id: str | None = None  # simulator only

    @property
    def friday_number(self) -> str | None:
        return self.to_number


class MissedCallReceived(Event):
    """A call to a Friday number that rang and was dropped before it was answered."""

    from_phone: str
    to_number: str | None = None
    provider_call_id: str | None = None
    provider: str = "unknown"
    ring_seconds: float = 0.0
    reason: str = "caller_hung_up"  # caller_hung_up | no_answer | short_ring

    @property
    def friday_number(self) -> str | None:
        return self.to_number


class CallLanguageSwitched(Event):
    task_id: str
    call_id: str
    old: Language | None
    new: Language


class CallLatencyReport(Event):
    task_id: str
    call_id: str
    turns: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    policy_p95_ms: float
    stt_p95_ms: float
    tts_p95_ms: float


class CallCostReport(Event):
    """Per-call cost components for the internal cost ledger (never user-facing)."""

    task_id: str
    call_id: str
    provider: str
    telephony_seconds: float = 0.0
    hold_seconds: int = 0
    stt_seconds: float = 0.0
    tts_chars: int = 0
    tts_billed_chars: int = 0
    policy_calls: int = 0
    translate_calls: int = 0
    cost_inr_est: float = 0.0


# ------------------------------------------------------------------ tasks (merged from
# friday/tasks/events.py; re-exported there)


class WellbeingAlertRaised(Event):
    """A13: a check-in sounded wrong (or nobody answered) -> SAFETY nudge."""

    task_id: str
    user_id: str
    person_id: str | None = None
    text: str


# ------------------------------------------------------------------ caller-ID pool


class NumberStatusChanged(Event):
    number_id: str
    phone: str
    old: str
    new: str  # NumberStatus value
    reason: str = ""


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def handlers_for(self, event_type: type[Event]) -> list[Handler]:
        out: list[Handler] = []
        for cls in event_type.__mro__:
            if isinstance(cls, type) and issubclass(cls, Event):
                out.extend(self._handlers.get(cls, []))
        return out

    async def publish(self, event: Event) -> None:
        handlers = self.handlers_for(type(event))
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, BaseException):
                log.error(
                    "event handler %s failed for %s: %r",
                    getattr(handler, "__qualname__", handler),
                    type(event).__name__,
                    result,
                )
