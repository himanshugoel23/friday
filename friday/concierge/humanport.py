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
