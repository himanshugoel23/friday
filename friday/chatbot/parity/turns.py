"""Items 7 and 8: one in-flight turn per user, strict reply order, and a status reply for slow tasks.

* ``TurnLocks``: an asyncio lock per user. A second message from the same user waits until the first
  turn has finished, so answers can never arrive after the next question.
* ``ReplyQueue``: replies are numbered when a turn starts and released strictly in that order.
* ``StatusWatcher``: if a task runs longer than 60 s, send one status reply with an ETA (once).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from friday.chatbot.parity import copy

STATUS_AFTER_S = 60.0


class TurnLocks:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, user_id: str) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    @asynccontextmanager
    async def turn(self, user_id: str):
        async with self.lock(user_id):
            yield

    def busy(self, user_id: str) -> bool:
        lk = self._locks.get(user_id)
        return bool(lk and lk.locked())


class ReplyQueue:
    """Release replies in ticket order even if they are produced out of order."""

    def __init__(self, send: Callable[[str, str], Awaitable[None]]) -> None:
        self._send = send
        self._next_ticket: dict[str, int] = {}
        self._next_release: dict[str, int] = {}
        self._held: dict[str, dict[int, str]] = {}

    def ticket(self, user_id: str) -> int:
        n = self._next_ticket.get(user_id, 0)
        self._next_ticket[user_id] = n + 1
        return n

    async def put(self, user_id: str, ticket: int, text: str) -> None:
        self._held.setdefault(user_id, {})[ticket] = text
        while (nxt := self._next_release.get(user_id, 0)) in self._held[user_id]:
            body = self._held[user_id].pop(nxt)
            self._next_release[user_id] = nxt + 1
            await self._send(user_id, body)


def format_eta(seconds: float | None, lang: str = "hinglish") -> str | None:
    if seconds is None or seconds <= 0:
        return None
    mins = max(1, round(seconds / 60))
    if lang == "hi":
        return f"{mins} मिनट"
    if lang == "en":
        return f"{mins} minute" if mins == 1 else f"{mins} minutes"
    return f"{mins} minute"


def status_text(eta_s: float | None, lang: str = "hinglish") -> str:
    eta = format_eta(eta_s, lang)
    if eta is None:
        return copy.line("status_unknown_eta", lang)
    return copy.line("status_working", lang, eta=eta)


async def run_with_status(
    work: Awaitable[object],
    send_status: Callable[[str], Awaitable[None]],
    *,
    eta_s: float | None = None,
    lang: str = "hinglish",
    after_s: float = STATUS_AFTER_S,
):
    """Await ``work``; if it is still running after ``after_s`` seconds, send ONE status reply."""
    task = asyncio.ensure_future(work)
    done, _ = await asyncio.wait({task}, timeout=after_s)
    if not done:
        await send_status(status_text(eta_s, lang))
    return await task
