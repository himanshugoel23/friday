"""Kill switch: ``friday pause`` (flag file / FRIDAY_PAUSED) and per-task abort close sessions now.

``PauseWatcher`` polls the same flag ``friday.pause.is_paused`` reads (every second by default) and
calls ``manager.kill_all``; ``SessionManager.open`` also refuses to start while paused. Wire it in
``friday serve`` with ``watcher = PauseWatcher(manager, pause_probe(settings)); watcher.start()``.
Per-task abort: ``await manager.kill_task(task_id)`` (or ``kill_user`` / ``kill_all``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from friday.connectors.session.manager import SessionManager


def pause_probe(core_settings: Any) -> Callable[[], bool]:
    from friday.pause import is_paused

    return lambda: is_paused(core_settings)


class PauseWatcher:
    def __init__(self, manager: SessionManager, paused: Callable[[], bool],
                 interval: float = 1.0) -> None:
        self.mgr, self._paused, self._interval = manager, paused, interval
        self._task: asyncio.Task[None] | None = None

    async def check_once(self) -> int:
        """Paused: kill and latch. No longer paused: lift only the latch THIS watcher set (a latch
        from a manual ``kill_all`` stays until an operator calls ``revive``)."""
        if self._paused():
            return await self.mgr.kill_all("paused")
        if self.mgr.latched == "paused":
            self.mgr.revive()
        return 0

    async def _run(self) -> None:
        while True:
            await self.check_once()
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        t, self._task = self._task, None
        if t:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
