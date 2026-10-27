# ruff: noqa: E501
"""Item 8: a status reply (with ETA) when a task runs longer than 60 s.

One in-flight turn per user and ordered replies (item 7) already exist in InboundPipeline.handle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from friday.chatbot.parity import copy

STATUS_AFTER_S = 60.0


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
