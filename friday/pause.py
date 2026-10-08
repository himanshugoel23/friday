"""Kill switch: stop every outbound call and proactive message, keep answering inbound.

    uv run friday pause            # switch ON  (stops new calls / nudges within ~1 s)
    uv run friday pause --status
    uv run friday pause --resume   # switch OFF

The flag is ON when EITHER
* ``FRIDAY_PAUSED=true`` (environment; needs a restart to change), OR
* the flag file ``FRIDAY_PAUSE_FILE`` exists (default ``./var/PAUSED``; every container of the
  stack mounts the same volume, so ``friday pause`` takes effect everywhere at once with no
  restart - the guards below re-check the file on every call).

What is blocked while paused (installed by ``install_pause_guard`` in ``friday serve`` and
``friday worker``; no other package is modified - instance methods are wrapped):
* ``telephony.place_call``               -> raises ``PausedError`` (no new call is dialled);
* job kinds ``call.place``, ``task.scheduled``, ``nudge.evaluate``, ``nudge.send`` are not
  claimed from the queue (they wait harmlessly and run after ``--resume``);
* ``proactive.tick``                      -> no nudges are created or sent;
* ``task_engine.submit``                  -> a NEW task is cancelled + polite notice.
Still working: inbound webhooks, replies to users, PIN/consent flows, calls already in progress
(they finish normally), inbound calls from businesses.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from friday.core.config import Settings
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger

log = get_logger(__name__)

NOTICE = (
    "Friday is taking a short break right now, so I can't make calls or start new tasks. "
    "I've noted your message and we'll be back soon. Thank you for your patience."
)
BLOCKED_JOB_KINDS: tuple[str, ...] = (
    "call.place",
    "task.scheduled",
    "nudge.evaluate",
    "nudge.send",
)


class PausedError(ProviderError):
    def __init__(self) -> None:
        super().__init__("friday", "paused by the operator kill switch (friday pause)")


def pause_file(settings: Settings) -> Path:
    return Path(settings.pause_file)


def is_paused(settings: Settings) -> bool:
    return bool(settings.paused) or pause_file(settings).exists()


def pause_status(settings: Settings) -> str:
    if settings.paused:
        return "PAUSED (FRIDAY_PAUSED=true in the environment; edit the env file and restart)"
    if pause_file(settings).exists():
        return f"PAUSED (flag file {pause_file(settings)})"
    return "RUNNING"


def set_paused(settings: Settings, on: bool) -> None:
    path = pause_file(settings)
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("paused\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _wrap(obj: Any, name: str, make: Any) -> bool:
    """Replace ``obj.name`` with ``make(original)`` on the instance. False if impossible."""
    original = getattr(obj, name, None)
    if original is None:
        return False
    try:
        setattr(obj, name, make(original))
    except (AttributeError, TypeError):  # slots / frozen: skip, never crash startup
        return False
    return True


def install_pause_guard(c: Any) -> list[str]:
    """Wrap the outbound paths of the components this process has. Returns what was guarded."""
    settings: Settings = c.settings
    guarded: list[str] = []
    wanted = set(c.role_components())  # only what this process' roles actually run

    def component(name: str) -> Any:
        if name not in wanted:
            return None
        try:
            return c.get(name)
        except Exception:  # noqa: BLE001 - a role that lacks a component simply has no guard
            return None

    tel = component("telephony")
    if tel is not None:

        def place_guard(orig: Any) -> Any:
            async def place_call(request: Any, *a: Any, **k: Any) -> Any:
                if is_paused(settings):
                    log.warning("kill switch: refusing to place a call")
                    raise PausedError
                return await orig(request, *a, **k)

            return place_call

        if _wrap(tel, "place_call", place_guard):
            guarded.append("telephony.place_call")

    queue = component("job_queue")
    if queue is not None:

        def claim_guard(orig: Any) -> Any:
            async def claim(
                worker_id: str, *, kinds: Sequence[str] | None = None, **k: Any
            ) -> Any:
                if kinds is not None and is_paused(settings):
                    kinds = [x for x in kinds if x not in BLOCKED_JOB_KINDS]
                    if not kinds:
                        return []
                return await orig(worker_id, kinds=kinds, **k)

            return claim

        if _wrap(queue, "claim", claim_guard):
            guarded.append("job_queue.claim")

    proactive = component("proactive")
    if proactive is not None:

        def tick_guard(orig: Any) -> Any:
            async def tick(*a: Any, **k: Any) -> Any:
                return [] if is_paused(settings) else await orig(*a, **k)

            return tick

        if _wrap(proactive, "tick", tick_guard):
            guarded.append("proactive.tick")

    engine = component("task_engine")
    if engine is not None:

        def submit_guard(orig: Any) -> Any:
            async def submit(task: Any, *a: Any, **k: Any) -> Any:
                if not is_paused(settings):
                    return await orig(task, *a, **k)
                saved = await engine.tasks.add(task)
                await engine.cancel(saved.id, by_user=False)
                await engine.outbox.to_user(saved.requester_user_id, NOTICE, task_id=saved.id)
                log.warning("kill switch: new task cancelled with a polite notice")
                return saved

            return submit

        if _wrap(engine, "submit", submit_guard):
            guarded.append("task_engine.submit")
    log.info("pause guard installed: %s", ", ".join(guarded) or "nothing")
    return guarded

