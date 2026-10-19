"""Offline fakes for the consumer-call flow (used by tests/calls and available to W2's tests).

Nothing here dials anything. ``FakeLiveCallEngine`` plays scripted outcomes per callee name so
the whole path (request -> approval -> gate -> call -> report -> retry) runs without a network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.calls.interfaces import Callee
from friday.calls.models import (
    CallBrief,
    CallOutcome,
    CallRequest,
    OutcomeStatus,
)
from friday.core.clock import utcnow
from friday.core.models import ReplyButton


@dataclass
class DialRecord:
    brief: CallBrief
    callee: Callee


class FakeLiveCallEngine:
    """Scripted engine. ``script[name]`` is a list of outcomes (or callables returning one),
    consumed in order; the last repeats. Default: a completed call."""

    def __init__(self) -> None:
        self.script: dict[str, list[Any]] = {}
        self.dials: list[DialRecord] = []

    def on(self, name: str, *outcomes: Any) -> None:
        self.script[name] = list(outcomes)

    async def run(self, brief: CallBrief, callee: Callee) -> CallOutcome:
        self.dials.append(DialRecord(brief, callee))
        seq = self.script.get(callee.name)
        attempt = sum(1 for d in self.dials if d.brief.request_id == brief.request_id)
        if not seq:
            return CallOutcome(
                request_id=brief.request_id,
                attempt=attempt,
                status=OutcomeStatus.COMPLETED,
                summary="Baat ho gayi.",
                started_at=utcnow(),
                duration_s=42,
            )
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        out = item(brief, callee) if callable(item) else item
        out = out.model_copy(update={"request_id": brief.request_id, "attempt": attempt})
        if out.started_at is None:
            out = out.model_copy(update={"started_at": utcnow()})
        return out


class FakeOpeningLineProvider:
    async def opening_line(self, brief: CallBrief, callee_name: str | None) -> str:
        who = brief.user_display_name or "the user"
        return f"Namaste, main {who} ki assistant bol rahi hoon. {brief.goal}"


@dataclass
class Sent:
    user_id: str
    text: str
    buttons: list[ReplyButton]
    urgent: bool


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Sent] = []

    async def send(
        self, user_id: str, text: str, buttons: Sequence[ReplyButton] = (), *, urgent: bool = False
    ) -> None:
        self.sent.append(Sent(user_id, text, list(buttons), urgent))

    def texts(self, user_id: str | None = None) -> list[str]:
        return [s.text for s in self.sent if user_id is None or s.user_id == user_id]


@dataclass
class FakeTask:
    id: str
    key: str
    request_id: str
    run_at: datetime
    parent_task_id: str | None
    cancelled: bool = False


@dataclass
class FakeTaskPort:
    tasks: dict[str, FakeTask] = field(default_factory=dict)
    by_key: dict[str, str] = field(default_factory=dict)
    on_create: Callable[[FakeTask], None] | None = None

    async def create(
        self,
        *,
        key: str,
        request: CallRequest,
        run_at: datetime,
        parent_task_id: str | None = None,
    ) -> str:
        if key in self.by_key:
            return self.by_key[key]
        t = FakeTask(f"task{len(self.tasks) + 1}", key, request.id, run_at, parent_task_id)
        self.tasks[t.id] = t
        self.by_key[key] = t.id
        if self.on_create:
            self.on_create(t)
        return t.id

    async def cancel(self, task_id: str) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].cancelled = True


class FakeDraftLLM:
    """Returns a fixed proposal, to test that ungrounded values are rejected."""

    def __init__(self, proposal: dict[str, Any] | None) -> None:
        self.proposal = proposal
        self.calls = 0

    async def propose(
        self, text: str, *, prior: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        self.calls += 1
        return self.proposal
