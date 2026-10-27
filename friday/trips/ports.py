"""Small interfaces the trip timeline depends on. Each has a fake in ``friday/trips/fakes.py``.

* ``FlightStatusPort``: flight / train status. The PROVIDER IS NOT CHOSEN (HANDOFF, decision 8):
  nothing real implements this port yet, and nothing real may be called.
* ``TripTaskPort``: starts a Friday task from a proposal the user approved. The production adapter
  wraps ``TaskEngine.create_task`` (see ``EngineTaskPort``); the call itself still goes through the
  existing approval and ``CallGate`` flow.
* ``TripSender``: delivers a trip message to the user's 1:1 chat (text + buttons).
* ``WalletReader``: the user's cards by bank and card name only (``savings.wallet``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from friday.core.models import TaskSpec
from friday.savings.wallet import UserCard


class ProviderUnavailable(RuntimeError):
    """The status provider failed (timeout, quota, outage). The watch backs off and stays quiet."""


@dataclass(frozen=True)
class StatusQuery:
    mode: str  # "flight" | "train"
    number: str
    on_date: date  # local date of the scheduled departure
    origin: str | None = None
    scheduled_dep: datetime | None = None  # from the document (UTC)


@dataclass(frozen=True)
class FlightStatus:
    status: str  # "scheduled" | "delayed" | "cancelled" | "departed" | "landed" | "unknown"
    fetched_at: datetime  # when the PROVIDER saw it (so a stale answer can be labelled)
    estimated_dep: datetime | None = None
    gate: str | None = None
    terminal: str | None = None
    provider: str = "fake"


class FlightStatusPort(Protocol):
    async def get_status(self, query: StatusQuery) -> FlightStatus: ...


class TripTaskPort(Protocol):
    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        """Returns the id of the created Friday task."""
        ...


class EngineTaskPort:
    """Adapter over ``friday.tasks.engine.TaskEngine``. The user already approved the PROPOSAL;
    the engine then asks again before it dials (``approved=False``)."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        task = await self.engine.create_task(user_id, spec, approved=approved)
        return str(task.id)


@dataclass(frozen=True)
class Button:
    id: str
    label: str


@dataclass
class TripMessage:
    """One outbound message of a trip thread: the text already carries the ``[trip]`` prefix."""

    text: str
    buttons: list[Button] = field(default_factory=list)
    trip_id: str | None = None
    dedupe_key: str | None = None


class TripSender(Protocol):
    async def send(self, user_id: str, message: TripMessage) -> bool:
        """True if the message was handed to the channel."""
        ...


class WalletReader(Protocol):
    async def list(self, user_id: str) -> list[UserCard]: ...
