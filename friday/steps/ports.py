# ruff: noqa: E501
"""Ports of the step runner. The runner depends only on these, so every test runs on fakes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from friday.steps.types import PlanState, StepRequest, StepResult


class StepWorker(Protocol):
    """Runs the INSIDE of one step with the browser agent loop (policy layer on every action)."""

    async def run(self, req: StepRequest) -> StepResult: ...
    async def reply(self, run_id: str, text: str) -> StepResult: ...
    async def cancel(self, run_id: str) -> None: ...


class UserPort(Protocol):
    async def saved_area(self, user_id: str) -> str:
        """The area/pincode of a saved Home or PG place, or ''."""
        ...

    async def area_from_reply(self, user_id: str, text: str) -> str:
        """'PG' / 'Home' (saved place) or 'Koramangala 560034' -> the area, saved as a place. '' when nothing usable."""
        ...

    async def phone_tail(self, user_id: str) -> str:
        """Last two digits of the user's own number (never the whole number)."""
        ...


class OtpPort(Protocol):
    def arm(self, user_id: str, site: str, key: str) -> bool:
        """Arm the guarded 'login code typed in chat' path for this user, site and key. False when saved logins / codes are not available."""
        ...

    def ready(self, key: str) -> bool:
        """A code for this key is waiting (not consumed)."""
        ...

    def wipe(self, key: str) -> None: ...


class Suggestion(Protocol):
    lines: list[str]
    pick: str
    reason: str


class Suggester(Protocol):
    async def suggest(self, *, user_id: str, category: str, area: str, lang: str, own: list[dict[str, str]]) -> Suggestion | None: ...


Say = Callable[[str, str], Awaitable[None]]
Fallback = Callable[[PlanState], Awaitable[None]]
