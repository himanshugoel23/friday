"""Wiring: record an episode when a main task ends (event bus)."""

from __future__ import annotations

from typing import Any

from friday.core.events import TaskStatusChanged
from friday.core.logging import get_logger
from friday.core.models import TaskStatus
from friday.memory.service import MemoryService

log = get_logger(__name__)

_OUTCOME = {
    TaskStatus.COMPLETED: "done", TaskStatus.FAILED: "could not complete",
    TaskStatus.CANCELLED: "cancelled",
}


def attach_episodes(bus: Any, repos: Any, clock: Any) -> MemoryService:
    """Subscribe to task status changes. One line per finished MAIN task (child calls are skipped);
    never raises into the engine."""
    svc = MemoryService(repos, clock)

    async def on_status(ev: TaskStatusChanged) -> None:
        if ev.new not in _OUTCOME:
            return
        try:
            task = await repos.tasks.get(ev.task_id)
            if task is None or task.parent_task_id is not None:
                return
            who = task.target.name if task.target else task.spec.business_name
            await svc.record_episode(ev.user_id, task.id, task.spec.goal, _OUTCOME[ev.new], who)
        except Exception:  # noqa: BLE001 - memory must never break a task
            log.exception("memory: episode not recorded")

    bus.subscribe(TaskStatusChanged, on_status)
    return svc
