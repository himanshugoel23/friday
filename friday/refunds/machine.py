# ruff: noqa: E501
"""The refund state machine: a table of allowed transitions plus the guards that make the two
dangerous moves (money received, case closed) impossible without proof or the user's word.

Same pattern as ``friday/tasks/states.py``. Pure functions: no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from friday.refunds.models import Basis, CloseReason, RefundCase, RefundState, Source

S = RefundState

ALLOWED: dict[RefundState, frozenset[RefundState]] = {
    S.SUSPECTED: frozenset({S.OPENED, S.CLOSED}),
    S.OPENED: frozenset({S.REQUESTED, S.VENDOR_ACKNOWLEDGED, S.PROMISED, S.RECEIVED, S.REJECTED, S.ESCALATED, S.CLOSED}),
    S.REQUESTED: frozenset({S.VENDOR_ACKNOWLEDGED, S.PROMISED, S.RECEIVED, S.REJECTED, S.ESCALATED, S.CLOSED}),
    S.VENDOR_ACKNOWLEDGED: frozenset({S.PROMISED, S.RECEIVED, S.REJECTED, S.ESCALATED, S.CLOSED}),
    S.PROMISED: frozenset({S.PROMISED, S.RECEIVED, S.REJECTED, S.ESCALATED, S.CLOSED}),  # re-promise
    S.RECEIVED: frozenset({S.RECEIVED, S.ESCALATED, S.CLOSED}),  # short: more may come, chase, accept
    S.REJECTED: frozenset({S.ESCALATED, S.CLOSED}),
    S.ESCALATED: frozenset({S.PROMISED, S.RECEIVED, S.REJECTED, S.CLOSED}),
    S.CLOSED: frozenset(),
}  # fmt: skip


class IllegalTransition(ValueError):
    """The move is not in ``ALLOWED``."""


class GuardFailed(ValueError):
    """The move is allowed, but its condition is not met (no proof, no date, no user word...)."""


@dataclass(frozen=True)
class AmountCheck:
    status: str  # "exact" | "short" | "over" | "unknown_expected"
    expected: int | None
    received: int
    diff: int = 0  # received - expected (negative when short)


def amount_check(expected: int | None, received: int, tolerance_paise: int = 100) -> AmountCheck:
    """Expected vs received. A difference within the tolerance (rounding, gateway fee) is exact."""
    if expected is None:
        return AmountCheck("unknown_expected", None, received)
    diff = received - expected
    if abs(diff) <= tolerance_paise:
        return AmountCheck("exact", expected, received, diff)
    return AmountCheck("short" if diff < 0 else "over", expected, received, diff)


def can_move(src: RefundState, dst: RefundState) -> bool:
    return dst in ALLOWED[src]


def transition(
    case: RefundCase,
    to: RefundState,
    *,
    source: Source,
    basis: Basis | None = None,
    reason: CloseReason | None = None,
    promised_date: date | None = None,
    promised_amount_paise: int | None = None,
    received_paise: int | None = None,
) -> RefundCase:
    """Return the case moved to ``to`` (a copy). Raises ``IllegalTransition`` / ``GuardFailed``.

    Guards:
    * SUSPECTED -> OPENED only by the user (Friday proposes, the user confirms).
    * PROMISED needs a date AND an amount (from the vendor's words or the user).
    * RECEIVED needs an amount and a basis: the user's word or proof. Friday cannot see the bank,
      so the system and a timer can never move money to received.
    * CLOSED needs a reason; a received closure needs the basis; any close other than the
      unconfirmed-suspicion drop needs the user (the system never closes a real case by itself).
    """
    if to not in ALLOWED[case.state]:
        raise IllegalTransition(f"{case.state.value} -> {to.value}")
    out = case.model_copy(deep=True)
    if case.state == S.SUSPECTED and to == S.OPENED and source != Source.USER:
        raise GuardFailed("only the user can open a suspected case")
    if to == S.PROMISED:
        if promised_date is None or promised_amount_paise is None:
            raise GuardFailed("a promise needs a date and an amount")
        out.promised_date, out.promised_amount_paise = promised_date, promised_amount_paise
    if to == S.RECEIVED:
        if received_paise is None or received_paise <= 0:
            raise GuardFailed("received needs an amount")
        if basis is None or source in (Source.SYSTEM, Source.TIMER):
            raise GuardFailed("received needs the user's word or proof")
        out.amount_received_paise = (out.amount_received_paise or 0) + received_paise
    if to == S.CLOSED:
        if reason is None:
            raise GuardFailed("closing needs a reason")
        if reason == CloseReason.UNCONFIRMED:
            if case.state != S.SUSPECTED:
                raise GuardFailed("only a suspected case can lapse unconfirmed")
        elif source != Source.USER:
            raise GuardFailed("only the user closes a case")
        if reason == CloseReason.RECEIVED:
            if basis is None or not out.amount_received_paise:
                raise GuardFailed("closing as received needs proof or the user's word")
            out.closed_basis = basis
        if reason == CloseReason.DECLINED and case.state != S.SUSPECTED:
            raise GuardFailed("declined is for a suspected case")
        out.closed_reason = reason
    out.state = to
    out.state_epoch = case.state_epoch + 1
    return out
