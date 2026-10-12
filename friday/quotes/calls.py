# ruff: noqa: E501
"""Vendor calls for the quotes flow, placed through the existing task engine.

One engine task per vendor call (type BOOKING, so the salon playbook runs: ``quote_only`` mode
with no delegation, ``book`` mode only with the delegation built here). The engine owns
everything about the call (pilot allow-list, redirect, DNC, caller-ID pool, kill switch,
retries are NOT used: the flow does its own single retry after the first pass).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import (
    CallOutcome,
    Delegation,
    Person,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
)
from friday.playbooks.model import PlaybookError
from friday.playbooks.select import book_now_delegation
from friday.quotes.finder import VendorFinder
from friday.quotes.models import Conv, Outcome, Vendor
from friday.tasks.engine import PILOT_NO_REAL_CALLS, ROLE_VENDOR_QUOTE

log = get_logger(__name__)


@dataclass
class CallReport:
    finished: bool
    outcome: Outcome | None = None
    price_inr: int | None = None
    slots: list[str] = field(default_factory=list)
    deferred: bool = False  # the engine parked the call for later (vendor closed)


class EngineVendorCalls:
    def __init__(self, c: Any, finder: VendorFinder) -> None:
        self.c = c
        self.finder = finder

    @property
    def engine(self) -> Any:
        return self.c.get("task_engine")

    @property
    def repos(self) -> Any:
        return self.c.get("repos")

    async def _person(self, conv: Conv) -> str | None:
        name = conv.slots.for_name
        if not name:
            return None
        if conv.person_id:
            return conv.person_id
        for p in await self.repos.people.list_for_owner(conv.user_id):
            if p.name.lower() == name.lower():
                return p.id
        person = await self.repos.people.upsert(Person(owner_user_id=conv.user_id, name=name))
        return person.id

    def _spec(
        self, conv: Conv, v: Vendor, *, book: bool, when_text: str | None, ceiling: int | None,
        delegation: Delegation | None,
    ) -> TaskSpec:
        sl = conv.slots
        services = ", ".join(sl.services) or "haircut"
        constraints = [] if book else ["mode: quote_only"]
        return TaskSpec(
            type=TaskType.BOOKING,
            goal=f"{'Book' if book else 'Get a price for'} {services} at {v.name}",
            business_name=v.name,
            business_phone=v.phone,
            category=conv.category or "salon",
            item=services,
            when_text=when_text,
            window_start=sl.when_start,
            window_end=sl.when_end,
            constraints=constraints,
            delegation=delegation or Delegation(),
            location_text=sl.location.address or sl.location.text,
            on_behalf_of=None,
        )

    async def place(
        self, conv: Conv, v: Vendor, *, now: datetime, task_id: str | None = None
    ) -> str:
        book = conv.mode == "book"
        delegation = None
        when = conv.slots.when_text
        if book:
            delegation = self._delegation(conv.slots.when_text, conv.slots.budget_inr, now)
        spec = self._spec(
            conv, v, book=book, when_text=when, ceiling=conv.slots.budget_inr, delegation=delegation
        )
        return await self._submit(conv, v, spec, delegation, task_id)

    async def place_booking(
        self, conv: Conv, v: Vendor, *, when_text: str, ceiling: int, now: datetime,
        task_id: str | None = None,
    ) -> str:
        delegation = self._delegation(when_text, ceiling, now)
        conv_book = conv.model_copy(update={"mode": "book"})
        spec = self._spec(
            conv_book, v, book=True, when_text=when_text, ceiling=ceiling, delegation=delegation
        )
        return await self._submit(conv_book, v, spec, delegation, task_id)

    @staticmethod
    def check_booking(when_text: str | None, ceiling: int | None, now: datetime) -> None:
        EngineVendorCalls._delegation(when_text, ceiling, now)

    @staticmethod
    def _delegation(when_text: str | None, ceiling: int | None, now: datetime) -> Delegation:
        if not when_text or not ceiling:
            raise PlaybookError(["booking needs a specific time and a price ceiling"], "salon")
        deleg, _ = book_now_delegation(
            when_text, None, int(ceiling), now, label="WhatsApp: this vendor, this time, this price"
        )
        return deleg

    async def _submit(
        self, conv: Conv, v: Vendor, spec: TaskSpec, delegation: Delegation | None,
        task_id: str | None = None,
    ) -> str:
        person_id = await self._person(conv)
        task = Task(
            **({"id": task_id} if task_id else {}),
            requester_user_id=conv.user_id,
            type=TaskType.BOOKING,
            spec=spec,
            delegation=delegation or Delegation(),
            max_attempts=1,  # the flow retries once itself, after the first pass
            role=ROLE_VENDOR_QUOTE,
            candidate=self.finder.candidate_for(v),
            created_at=self.c.clock.now(),
            updated_at=self.c.clock.now(),
        )
        task.beneficiary.person_id = person_id
        await self.engine.submit(task)
        return task.id

    async def cancel(self, task_id: str) -> None:
        with contextlib.suppress(Exception):
            await self.engine.cancel(task_id, by_user=False)

    async def report(self, task_id: str) -> CallReport:
        task = await self.repos.tasks.get(task_id)
        if task is None:
            return CallReport(finished=True, outcome=Outcome.FAILED)
        if task.status == TaskStatus.SCHEDULED and task.attempts == 0:
            return CallReport(finished=False, deferred=True)
        if not task.status.is_terminal:
            return CallReport(finished=False)
        calls = await self.repos.tasks.list_calls(task_id)
        last = calls[-1] if calls else None
        if last is None:
            summary = task.result.summary if task.result else ""
            if summary == PILOT_NO_REAL_CALLS:
                return CallReport(True, Outcome.BLOCKED)
            if "asked not to be called" in summary:
                return CallReport(True, Outcome.DNC)
            if task.status == TaskStatus.CANCELLED:
                return CallReport(True, Outcome.FAILED)
            return CallReport(True, Outcome.FAILED)
        return classify(last, task)


def classify(call: Any, task: Task) -> CallReport:
    pb = str(call.collected.get("outcome", "")).upper()
    price = next((q.amount_inr for q in call.quotes if q.amount_inr is not None), None)
    slots = [s for q in call.quotes for s in q.available_slots]
    o = call.outcome
    rep = CallReport(True, price_inr=price, slots=slots)
    if call.collected.get("wrong_number") == "yes" or pb == "WRONG_NUMBER":
        rep.outcome = Outcome.WRONG_NUMBER
    elif pb == "REFUSED" or call.collected.get("do_not_call"):
        rep.outcome = Outcome.DNC
    elif pb == "BOOKED" or (o == CallOutcome.SUCCESS and task.delegation.granted):
        rep.outcome = Outcome.BOOKED
    elif pb == "NO_SLOT":
        rep.outcome = Outcome.NO_SLOT
    elif o == CallOutcome.PENDING_APPROVAL or pb == "SLOT_OFFERED":
        ceiling = task.delegation.max_price_inr
        if task.delegation.granted and ceiling and price and price > ceiling:
            rep.outcome = Outcome.PRICE_TOO_HIGH
        elif task.delegation.granted:
            rep.outcome = Outcome.NO_SLOT
        else:
            rep.outcome = Outcome.QUOTE if price else Outcome.FAILED
    elif o in (CallOutcome.PARTIAL, CallOutcome.SUCCESS):
        rep.outcome = Outcome.QUOTE if price is not None else Outcome.DECLINED
        if price is None:
            rep.outcome = Outcome.QUOTE if pb == "QUOTE_COLLECTED" else Outcome.DECLINED
    elif o in (CallOutcome.NO_ANSWER, CallOutcome.BUSY, CallOutcome.VOICEMAIL):
        rep.outcome = Outcome.NO_ANSWER
    elif o == CallOutcome.DECLINED:
        rep.outcome = Outcome.DECLINED
    elif o == CallOutcome.CALLBACK_LATER:
        rep.outcome = Outcome.NO_ANSWER
    else:
        rep.outcome = Outcome.FAILED
    return rep
