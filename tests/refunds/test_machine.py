# ruff: noqa: E501
"""The state machine: every pair of states, the guards, and expected-vs-received."""

from __future__ import annotations

from datetime import date
from itertools import product

import pytest

from friday.refunds.machine import (
    ALLOWED,
    GuardFailed,
    IllegalTransition,
    amount_check,
    can_move,
    transition,
)
from friday.refunds.models import Basis, CloseReason, RefundCase, RefundState, Source

S = RefundState


def case_in(state: RefundState, **kw) -> RefundCase:
    return RefundCase(user_id="u1", state=state, vendor_name="Exampleair", **kw)


def full_args(src: RefundState, dst: RefundState) -> dict:
    """Everything a legal move could need, so only the table decides."""
    kw: dict = {"source": Source.USER, "basis": Basis.USER}
    if dst == S.PROMISED:
        kw |= {"promised_date": date(2026, 11, 20), "promised_amount_paise": 450000}
    if dst == S.RECEIVED:
        kw |= {"received_paise": 450000}
    if dst == S.CLOSED:
        kw["reason"] = CloseReason.DECLINED if src == S.SUSPECTED else CloseReason.USER_DROPPED
    return kw


@pytest.mark.parametrize(("src", "dst"), list(product(S, S)))
def test_every_pair_of_states(src, dst):
    c = case_in(src)
    if dst in ALLOWED[src]:
        out = transition(c, dst, **full_args(src, dst))
        assert out.state == dst and out.state_epoch == c.state_epoch + 1
        assert c.state == src  # the input is never mutated
    else:
        with pytest.raises(IllegalTransition):
            transition(c, dst, **full_args(src, dst))
    assert can_move(src, dst) == (dst in ALLOWED[src])


def test_closed_is_terminal_and_everything_else_can_close():
    assert ALLOWED[S.CLOSED] == frozenset()
    for s in S:
        if s != S.CLOSED:
            assert S.CLOSED in ALLOWED[s]


def test_only_the_user_opens_a_suspected_case():
    c = case_in(S.SUSPECTED)
    for src in (Source.SYSTEM, Source.TIMER, Source.TRIP, Source.CALL):
        with pytest.raises(GuardFailed):
            transition(c, S.OPENED, source=src)
    assert transition(c, S.OPENED, source=Source.USER).state == S.OPENED


def test_a_promise_needs_a_date_and_an_amount():
    c = case_in(S.REQUESTED)
    with pytest.raises(GuardFailed):
        transition(c, S.PROMISED, source=Source.USER, promised_date=date(2026, 11, 20))
    with pytest.raises(GuardFailed):
        transition(c, S.PROMISED, source=Source.USER, promised_amount_paise=100)
    out = transition(
        c, S.PROMISED, source=Source.USER, promised_date=date(2026, 11, 20), promised_amount_paise=450000
    )
    assert out.promised_date == date(2026, 11, 20) and out.promised_amount_paise == 450000


@pytest.mark.parametrize("src", [Source.SYSTEM, Source.TIMER])
def test_money_cannot_be_received_by_the_system_or_a_timer(src):
    with pytest.raises(GuardFailed):
        transition(case_in(S.PROMISED), S.RECEIVED, source=src, basis=Basis.PROOF, received_paise=100)


def test_received_needs_an_amount_and_a_basis():
    c = case_in(S.PROMISED)
    with pytest.raises(GuardFailed):
        transition(c, S.RECEIVED, source=Source.USER, basis=Basis.USER)
    with pytest.raises(GuardFailed):
        transition(c, S.RECEIVED, source=Source.USER, basis=Basis.USER, received_paise=0)
    with pytest.raises(GuardFailed):
        transition(c, S.RECEIVED, source=Source.USER, received_paise=100)
    out = transition(c, S.RECEIVED, source=Source.USER, basis=Basis.USER, received_paise=100)
    again = transition(out, S.RECEIVED, source=Source.USER, basis=Basis.USER, received_paise=50)
    assert again.amount_received_paise == 150  # instalments add up


def test_closing_needs_a_reason_and_the_user():
    c = case_in(S.REQUESTED)
    with pytest.raises(GuardFailed):
        transition(c, S.CLOSED, source=Source.USER)
    for src in (Source.SYSTEM, Source.TIMER, Source.CALL, Source.TRIP):
        with pytest.raises(GuardFailed):
            transition(c, S.CLOSED, source=src, reason=CloseReason.USER_DROPPED)


def test_closing_as_received_needs_money_and_a_basis():
    # never passed through RECEIVED: no amount, so it cannot close as received
    with pytest.raises(GuardFailed):
        transition(case_in(S.PROMISED), S.CLOSED, source=Source.USER, reason=CloseReason.RECEIVED, basis=Basis.USER)
    got = case_in(S.RECEIVED, amount_received_paise=450000)
    with pytest.raises(GuardFailed):
        transition(got, S.CLOSED, source=Source.USER, reason=CloseReason.RECEIVED)
    out = transition(got, S.CLOSED, source=Source.USER, reason=CloseReason.RECEIVED, basis=Basis.PROOF)
    assert out.closed_reason == CloseReason.RECEIVED and out.closed_basis == Basis.PROOF


def test_unconfirmed_lapse_is_only_for_a_suspicion():
    out = transition(case_in(S.SUSPECTED), S.CLOSED, source=Source.TIMER, reason=CloseReason.UNCONFIRMED)
    assert out.state == S.CLOSED
    with pytest.raises(GuardFailed):
        transition(case_in(S.OPENED), S.CLOSED, source=Source.TIMER, reason=CloseReason.UNCONFIRMED)
    with pytest.raises(GuardFailed):  # declined is for a suspicion only
        transition(case_in(S.OPENED), S.CLOSED, source=Source.USER, reason=CloseReason.DECLINED)


def test_amount_check():
    assert amount_check(450000, 450000).status == "exact"
    assert amount_check(450000, 449950).status == "exact"  # inside the Rs 1 tolerance
    short = amount_check(450000, 400000)
    assert (short.status, short.diff) == ("short", -50000)
    assert amount_check(450000, 460000).status == "over"
    assert amount_check(None, 460000).status == "unknown_expected"
    assert amount_check(450000, 449000, tolerance_paise=2000).status == "exact"
