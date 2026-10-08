"""Local contracts the task/proactive engines need beyond ``friday.core.interfaces``.

Core has no ``Notifier`` Protocol and its repository Protocols are minimal, so the
extra methods we use are declared here (structural typing, nothing imported from
``friday.db`` / ``friday.channels``). Every extra is OPTIONAL at runtime: engines
call them through ``opt()``/``call_opt()`` and degrade gracefully when the bundle
lacks them. Proposed for core in docs/CORE_CHANGES.md.

Repository bundle attribute names follow B-1 (``c.repos.tasks``, ``.users``,
``.profiles``, ``.autonomy``, ``.people``, ``.places``, ``.businesses``, ``.facts``,
``.identifiers``, ``.nudges``, ``.consents``, ``.audit``, ``.costs``, ``.messages``).
"""

from __future__ import annotations

import inspect
from datetime import date, datetime
from typing import Any, Protocol

from friday.core.interfaces import Notifier as _CoreNotifier
from friday.core.logging import get_logger
from friday.core.models import (
    AutonomySetting,
    ConversationTurn,
    HotelBooking,
    MidCallQuestion,
    Nudge,
    NudgeFeedback,
    NudgeKind,
    Profile,
    User,
    UserAnswer,
)

log = get_logger(__name__)


Notifier = _CoreNotifier  # merged into core (Stage 3)


class ProfileStore(Protocol):
    async def get(self, user_id: str) -> Profile | None: ...


class AutonomyStore(Protocol):
    async def list_for_user(self, user_id: str) -> list[AutonomySetting]: ...
    async def upsert(self, setting: AutonomySetting) -> AutonomySetting: ...


class UserLister(Protocol):
    async def list_active(self) -> list[User]: ...


class QuestionStore(Protocol):  # extra methods on the task repository
    async def add_question(self, question: MidCallQuestion) -> MidCallQuestion: ...
    async def get_question(self, question_id: str) -> MidCallQuestion | None: ...
    async def answer_question(self, answer: UserAnswer) -> bool: ...
    async def save_hotel_booking(self, booking: HotelBooking, *, user_id: str) -> HotelBooking: ...


class NudgeHistory(Protocol):  # extra methods on the nudge repository
    async def get(self, nudge_id: str) -> Nudge | None: ...
    async def list_for_user(
        self, user_id: str, *, kind: NudgeKind | None = None, status: Any = None, limit: int = 50
    ) -> list[Nudge]: ...
    async def list_scheduled_due(self, now: datetime) -> list[Nudge]: ...
    async def list_sent_unanswered_before(self, cutoff: datetime) -> list[Nudge]: ...
    async def add_feedback(self, feedback: NudgeFeedback) -> NudgeFeedback: ...


class MessageHistory(Protocol):
    async def recent_turns(self, user_id: str, *, limit: int = 20) -> list[ConversationTurn]: ...


class FactsDue(Protocol):
    async def list_due_between(self, start: date, end: date) -> list[Any]: ...


# ------------------------------------------------------------------ helpers

_ALIASES: dict[str, tuple[str, ...]] = {
    "profiles": ("profiles", "profile"),
    "autonomy": ("autonomy", "autonomy_settings"),
    "costs": ("costs", "cost"),
    "audit": ("audit", "audit_log"),
}


def repo(repos: Any, name: str) -> Any:
    """``repos.<name>`` (or a known alias) or None."""
    if repos is None:
        return None
    for attr in _ALIASES.get(name, (name,)):
        value = getattr(repos, attr, None)
        if value is not None:
            return value
    return None


async def call_opt(obj: Any, method: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    """Await ``obj.method(*args, **kwargs)`` if it exists; ``default`` otherwise or on error.
    Optional extras must never break the main flow."""
    fn = getattr(obj, method, None) if obj is not None else None
    if fn is None:
        return default
    try:
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:  # noqa: BLE001 - optional extra
        log.warning("optional %s.%s failed: %r", type(obj).__name__, method, e)
        return default
