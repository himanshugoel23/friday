"""Small interfaces refund tracking depends on. Each has a fake in ``friday/refunds/fakes.py``.

* ``RefundSender``: delivers a message (text + buttons) to the user's 1:1 chat.
* ``RefundTaskPort``: starts a vendor follow-up as a Friday task AFTER the user approved the
  proposal. The production adapter wraps ``TaskEngine.create_task`` with ``approved=False``, so the
  engine asks again and ``CallGate`` rules apply; it refuses while the call lines are PENDING.
* ``NumberSource``: where a vendor number may come from. Every number Friday ever proposes to call
  is returned by a source that read it from the user's own documents, a task record, proof the user
  supplied, a person-verified vendor record, or the user's own message. Nothing is looked up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from friday.core.models import TaskSpec
from friday.refunds import copy
from friday.refunds.copy import BUTTON_PREFIX

SOURCES = ("user", "document", "task", "evidence", "vendor_record")


class LinesPending(RuntimeError):
    """The vendor-call questions are still PENDING founder approval: no real call may start."""


@dataclass(frozen=True)
class Button:
    id: str
    label: str


@dataclass
class RefundMessage:
    text: str
    buttons: list[Button] = field(default_factory=list)
    case_id: str | None = None
    dedupe_key: str | None = None


class RefundSender(Protocol):
    async def send(self, user_id: str, message: RefundMessage) -> bool:
        """True if the message was handed to the channel."""
        ...


class RefundTaskPort(Protocol):
    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        """Returns the id of the created Friday task."""
        ...


class EngineRefundTaskPort:
    """Adapter over ``friday.tasks.engine.TaskEngine``. Refuses while the call lines are PENDING
    (hear-before-change): the founder hears the audio first, then a reviewed commit flips
    ``copy.CALL_LINE_STATUS``."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        if copy.CALL_LINE_STATUS != "APPROVED":
            raise LinesPending("refund follow-up call lines are PENDING_FOUNDER_APPROVAL")
        task = await self.engine.create_task(user_id, spec, approved=approved)
        return str(task.id)


@dataclass(frozen=True)
class KnownNumber:
    number: str  # as held; the resolver canonicalises and drops what cannot be dialled
    source: str  # one of SOURCES
    label: str = ""  # the name it was filed under (for the user: "Hotel Example Palms")


class NumberSource(Protocol):
    async def numbers_for(self, user_id: str, vendor_name: str) -> list[KnownNumber]:
        """Numbers held for THIS user whose owner matches ``vendor_name``. Never a lookup."""
        ...


_WORD = re.compile(r"[a-z0-9]+")


def name_match(vendor: str, candidate: str) -> bool:
    """Loose, conservative name match used by the adapters. Every word (3+ letters) of the vendor
    must be a word of the candidate; or the joined vendor name (5+ letters) occurs in the joined
    candidate. 'Air' does not match 'Exampleair'; 'Exampleair' matches 'Exampleair Pvt Ltd'."""
    v = _WORD.findall((vendor or "").lower())
    c = _WORD.findall((candidate or "").lower())
    if not v or not c:
        return False
    words = [w for w in v if len(w) >= 3 and not w.isdigit()]
    if words and all(w in c for w in words):
        return True
    vj, cj = "".join(v), "".join(c)
    return len(vj) >= 5 and vj in cj


def button_id(case_id: str, action: str) -> str:
    return f"{BUTTON_PREFIX}{case_id}:{action}"
