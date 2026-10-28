# ruff: noqa: E501
"""Slow-response UX: ONE short 'on it' line when work takes longer than ``after_s`` (default 8 s).

The work is never cancelled by the acknowledgement; the result is delivered by the caller as the
normal follow-up message. Never more than one acknowledgement per call.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

ACK_AFTER_S = 8.0


async def run_with_ack(
    work: Awaitable[T],
    send_ack: Callable[[], Awaitable[None]],
    *,
    after_s: float = ACK_AFTER_S,
) -> T:
    task = asyncio.ensure_future(work)
    try:
        done, _ = await asyncio.wait({task}, timeout=after_s)
        if not done:
            with contextlib.suppress(Exception):  # a failed ack must not lose the result
                await send_ack()
        return await task
    except asyncio.CancelledError:
        task.cancel()
        raise
