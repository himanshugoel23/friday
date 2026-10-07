"""Simple in-process async event bus + the shared event types.

Used for decoupled notifications ("a call turn happened", "task status changed")
- audit log, simulator UI, metrics, proactive triggers. NOT for request/response:
call a service directly when you need an answer.

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
