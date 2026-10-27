"""Fakes for tests, the simulator and demos. Nothing here touches a network or a phone."""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.core.models import TaskSpec
from friday.refunds.ports import RefundMessage


@dataclass
class FakeRefundSender:
    sent: list[tuple[str, RefundMessage]] = field(default_factory=list)
    refuse: bool = False

    async def send(self, user_id: str, message: RefundMessage) -> bool:
        if self.refuse:
            return False
        self.sent.append((user_id, message))
        return True

    def texts(self, user_id: str) -> list[str]:
        return [m.text for u, m in self.sent if u == user_id]


@dataclass
class FakeRefundTaskPort:
    """Records the task specs a real engine would receive. Nothing is dialled."""

    created: list[tuple[str, TaskSpec, bool]] = field(default_factory=list)

    async def create_task(self, user_id: str, spec: TaskSpec, *, approved: bool = False) -> str:
        self.created.append((user_id, spec, approved))
        return f"faketask{len(self.created):03d}"
