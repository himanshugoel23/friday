# ruff: noqa: E501
"""Fakes for tests, the simulator and demos. Nothing here touches a network, a phone or a provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from friday.core.clock import Clock
from friday.core.models import TaskSpec
from friday.trips.ports import (
    FlightStatus,
    ProviderUnavailable,
    StatusQuery,
    TripMessage,
)


@dataclass
class Scripted:
    """One scripted provider answer. ``delay_minutes`` shifts the estimated departure."""

    status: str = "scheduled"
    delay_minutes: int = 0
    gate: str | None = None
    terminal: str | None = None
    age_minutes: int = 0  # how old the provider's data is
    fail: bool = False  # raise ProviderUnavailable


class FakeFlightStatus:
    """Scripts per flight/train number. Each call consumes the next script; the last one repeats."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.scripts: dict[str, list[Scripted]] = {}
        self.calls: list[StatusQuery] = []

    def script(self, number: str, *steps: Scripted) -> None:
        self.scripts[number] = list(steps)

    async def get_status(self, query: StatusQuery) -> FlightStatus:
        self.calls.append(query)
        steps = self.scripts.get(query.number)
        if not steps:
            return FlightStatus("unknown", self.clock.now())
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if step.fail:
            raise ProviderUnavailable("fake provider down")
        est = (
            query.scheduled_dep + timedelta(minutes=step.delay_minutes)
            if query.scheduled_dep is not None
            else None
        )
        return FlightStatus(
            status=step.status,
            fetched_at=self.clock.now() - timedelta(minutes=step.age_minutes),
            estimated_dep=est,
            gate=step.gate,
            terminal=step.terminal,
        )


@dataclass
class FakeTripSender:
    sent: list[tuple[str, TripMessage]] = field(default_factory=list)
    refuse: bool = False

    async def send(self, user_id: str, message: TripMessage) -> bool:
        if self.refuse:
            return False
        self.sent.append((user_id, message))
        return True

    def texts(self, user_id: str) -> list[str]:
        return [m.text for u, m in self.sent if u == user_id]


@dataclass
class FakeTripTaskPort:
    """Records the task specs a real engine would receive. Nothing is dialled."""

    created: list[tuple[str, TaskSpec, bool]] = field(default_factory=list)

    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        self.created.append((user_id, spec, approved))
        return f"faketask{len(self.created):03d}"
