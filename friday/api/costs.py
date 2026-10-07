"""Internal cost tracking + ops abuse limit. NOTHING here is ever shown to users.

* Per-user cost roll-ups (IST day / IST month) from the ``cost_entries`` ledger
  (calls are recorded by ``TaskRepo.save_call``; other legs via ``record``).
* Ops alert when a user's month total crosses ``cost_alert_inr_per_user_month``:
  a WARNING log (user id only) + ``CostAlert`` event + ``ops.cost_alert`` audit
  entry, at most once per user per IST month.
* Abuse rate-limit: OFF by default. Applies only when ops enables it globally
  (``abuse_rate_limit_enabled``) or for one user (``User.rate_limited``). A
  limited request is queued, never refused with "cap" wording.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.core.clock import UTC, Clock, at_ist, ist_day_bounds, to_ist
from friday.core.config import Settings
from friday.core.events import Event, EventBus
from friday.core.logging import get_logger
from friday.core.models import User
from friday.db.repositories import Repositories

log = get_logger(__name__)


class CostAlert(Event):
    user_id: str
    month_total_inr: float
    threshold_inr: float


def ist_month_bounds(dt: datetime) -> tuple[datetime, datetime]:
    local = to_ist(dt)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.astimezone(UTC), nxt.astimezone(UTC)


class CostTracker:
    def __init__(
        self, settings: Settings, clock: Clock, bus: EventBus, repos: Repositories
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.bus = bus
        self.repos = repos

    async def record(
        self, user_id: str, amount_inr: float, *, kind: str, task_id: str | None = None
    ) -> None:
        await self.repos.costs.record(user_id, amount_inr, kind=kind, task_id=task_id)
        await self.check(user_id)

    async def day_total(self, user_id: str) -> float:
        start, end = ist_day_bounds(self.clock.now())
        return await self.repos.costs.total_between(user_id, start, end)

    async def month_total(self, user_id: str) -> float:
        start, end = ist_month_bounds(self.clock.now())
        return await self.repos.costs.total_between(user_id, start, end)

    async def check(self, user_id: str) -> bool:
        """Raise the ops alert if the month threshold is crossed. True if alerted now."""
        threshold = self.settings.cost_alert_inr_per_user_month
        total = await self.month_total(user_id)
        if total < threshold:
            return False
        start, _ = ist_month_bounds(self.clock.now())
        for entry in await self.repos.audit.list_for_user(user_id, limit=500):
            if entry.action == "ops.cost_alert" and entry.at >= start:
                return False
        log.warning("ops cost alert: user %s month total above threshold", user_id)
        await self.repos.audit.log(
            "ops.cost_alert", user_id=user_id, actor="system", total_inr=round(total, 2)
        )
        await self.bus.publish(
            CostAlert(user_id=user_id, month_total_inr=total, threshold_inr=threshold)
        )
        return True


class AbuseLimiter:
    def __init__(self, settings: Settings, clock: Clock, repos: Repositories) -> None:
        self.settings = settings
        self.clock = clock
        self.repos = repos

    def applies_to(self, user: User) -> bool:
        return self.settings.abuse_rate_limit_enabled or user.rate_limited

    async def limited_until(self, user: User) -> datetime | None:
        """None if the user may start a task now; else when the queued task may run."""
        if not self.applies_to(user):
            return None
        start, end = ist_day_bounds(self.clock.now())
        created = await self.repos.tasks.list_created_between(user.id, start, end)
        if len(created) < self.settings.abuse_max_calls_per_day:
            return None
        h, m = (int(x) for x in self.settings.business_call_window_start.split(":"))
        return at_ist(to_ist(end).date(), h, m)
