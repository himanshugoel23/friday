# ruff: noqa: E501
"""The one small interface between the AI emergency flow (friday/robin) and the human desk.

``friday/robin/alerts.py`` asks ``human_joined(incident_id)`` before each re-ring/nudge step; the desk registers the answer when it is
mounted. With nothing registered (desk off) the answer is always False, so Robin behaves exactly as before. Never raises.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

_CHECKER: Callable[[str], Awaitable[bool]] | None = None


def register_human_joined(fn: Callable[[str], Awaitable[bool]] | None) -> None:
    global _CHECKER
    _CHECKER = fn


async def human_joined(incident_id: str) -> bool:
    fn = _CHECKER
    if fn is None:
        return False
    try:
        return bool(await fn(incident_id))
    except Exception:  # noqa: BLE001 - the AI ladder must never break because the desk lookup failed
        return False


# ---------------------------------------------------------------------------- T19: AI -> desk handoff and desk tick
# The desk registers ``DeskService.receive`` and ``DeskService.tick`` when it is mounted (concierge/wiring.py). With nothing registered
# (desk off, or its ports not wired) both are no-ops, so Robin behaves exactly as before. Neither can raise into the AI ladder.
HANDOFF_TIMEOUT_S = 5.0

_HANDOFF: Callable[[object], Awaitable[object]] | None = None
_TICK: Callable[[], Awaitable[int]] | None = None


def register_handoff(fn: Callable[[object], Awaitable[object]] | None) -> None:
    global _HANDOFF
    _HANDOFF = fn


def register_tick(fn: Callable[[], Awaitable[int]] | None) -> None:
    global _TICK
    _TICK = fn


def handoff_enabled() -> bool:
    return _HANDOFF is not None


async def hand_off(card: object) -> bool:
    """Give the desk the one-screen card. True when the desk took it. Never raises and never waits longer than ``HANDOFF_TIMEOUT_S``."""
    fn = _HANDOFF
    if fn is None:
        return False
    import asyncio

    try:
        await asyncio.wait_for(fn(card), HANDOFF_TIMEOUT_S)
        return True
    except Exception:  # noqa: BLE001 - includes timeout; the AI ladder carries on alone
        return False


async def desk_tick() -> int:
    fn = _TICK
    if fn is None:
        return 0
    try:
        return int(await fn() or 0)
    except Exception:  # noqa: BLE001
        return 0
