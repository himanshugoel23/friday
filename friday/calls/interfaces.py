"""Ports between W1 (before and after the call) and everything else.

W2 implements ``LiveCallEngine`` and ``OpeningLineProvider``; the lead wires ``UserNotifier`` to the
channel layer and ``TaskPort`` to the task engine. Nothing here imports W2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from friday.calls.models import CallBrief, CalleeKind, CallOutcome, CallRequest
from friday.core.models import ReplyButton


@dataclass(frozen=True)
class Callee:
    """Who the engine dials. ``number`` is plain E.164 and exists only for the dial; the engine
    must never log it (use ``friday.calls.numbers.mask``)."""

    name: str
    number: str = field(repr=False)
    kind: CalleeKind
    language: str = "hinglish"
    max_duration_s: int = 300
    from_number: str | None = None  # caller ID chosen by the number pool


@runtime_checkable
class LiveCallEngine(Protocol):
    """W2: runs the live conversation for one approved brief and returns what happened.

    Contract: the engine speaks ``brief.opening_line`` exactly as approved, answers only from
    ``brief.shareable_facts``, never from ``private_facts``, turns any promise not in the brief
    into ``needs_user_approval``, ends at ``callee.max_duration_s``, and sets
    ``do_not_call_again`` / OutcomeStatus.OPTED_OUT / WRONG_PERSON when the callee says so.
    """

    async def run(self, brief: CallBrief, callee: Callee) -> CallOutcome: ...


@runtime_checkable
class OpeningLineProvider(Protocol):
    """W2: the exact first line the call will start with, so the user can approve it."""

    async def opening_line(self, brief: CallBrief, callee_name: str | None) -> str: ...


class UserNotifier(Protocol):
    """Sends a WhatsApp message to the user (adapter over the core Notifier)."""

    async def send(
        self, user_id: str, text: str, buttons: Sequence[ReplyButton] = (), *, urgent: bool = False
    ) -> None: ...


class TaskPort(Protocol):
    """The task engine as seen from W1: create a tracked, idempotent task for one call attempt."""

    async def create(
        self,
        *,
        key: str,
        request: CallRequest,
        run_at: datetime,
        parent_task_id: str | None = None,
    ) -> str:
        """Return the task id. The same ``key`` must always return the same task (no duplicates)."""
        ...

    async def cancel(self, task_id: str) -> None: ...
