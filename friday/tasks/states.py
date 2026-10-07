"""Task state machine (docs/ARCHITECTURE.md §4) as data. The engine refuses any
transition not listed here."""

from __future__ import annotations

from friday.core.models import TaskStatus as S

ALLOWED: dict[S, frozenset[S]] = {
    S.CREATED: frozenset({S.PLANNING, S.SCHEDULED, S.CANCELLED}),
    S.PLANNING: frozenset(
        {
            S.NEEDS_INFO,
            S.AWAITING_APPROVAL,
            S.DISCOVERING,
            S.SCHEDULED,
            S.CALLING,
            S.CONFIRMATION_CALLBACK,
            S.COMPLETED,
            S.FAILED,
            S.CANCELLED,
        }
    ),
    S.NEEDS_INFO: frozenset({S.PLANNING, S.CANCELLED}),
    S.DISCOVERING: frozenset({S.AWAITING_APPROVAL, S.WAITING_CHILDREN, S.FAILED, S.CANCELLED}),
    S.AWAITING_APPROVAL: frozenset(
        {S.CALLING, S.SCHEDULED, S.WAITING_CHILDREN, S.CONFIRMATION_CALLBACK, S.CANCELLED}
    ),
    S.WAITING_CHILDREN: frozenset({S.AWAITING_CHOICE, S.COMPLETED, S.FAILED, S.CANCELLED}),
    S.AWAITING_CHOICE: frozenset({S.WAITING_CHILDREN, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.CALLING, S.CONFIRMATION_CALLBACK, S.COMPLETED, S.CANCELLED}),
    S.CALLING: frozenset(
        {S.AWAITING_USER, S.COMPLETED, S.FAILED, S.SCHEDULED, S.AWAITING_APPROVAL, S.CANCELLED}
    ),
    S.AWAITING_USER: frozenset({S.CALLING, S.CONFIRMATION_CALLBACK, S.CANCELLED}),
    S.CONFIRMATION_CALLBACK: frozenset(
        {S.AWAITING_USER, S.COMPLETED, S.FAILED, S.SCHEDULED, S.AWAITING_APPROVAL, S.CANCELLED}
    ),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
}

ACTIVE_CALL = frozenset({S.CALLING, S.CONFIRMATION_CALLBACK, S.AWAITING_USER})


class InvalidTransition(RuntimeError):
    def __init__(self, old: S, new: S) -> None:
        super().__init__(f"illegal task transition {old} -> {new}")
        self.old, self.new = old, new


def check(old: S, new: S) -> None:
    if old != new and new not in ALLOWED[old]:
        raise InvalidTransition(old, new)


def all_transitions() -> set[tuple[S, S]]:
    return {(a, b) for a, targets in ALLOWED.items() for b in targets}
