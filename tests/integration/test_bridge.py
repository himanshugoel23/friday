"""The models bridge: W1 brief/outcome <-> W2 brief/result, in one place."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from friday.calls.interfaces import Callee
from friday.calls.models import (
    CallBrief,
    CalleeKind,
    Limits,
    NextAction,
    OutcomeStatus,
)
from friday.core.clock import FakeClock
from friday.integration import copy
from friday.integration.bridge import (
    STATUS_MAP,
    LiveEngineAdapter,
    LiveOpeningLineProvider,
    NoTelephony,
    dial_target,
    live_kind,
    live_language,
    to_live_brief,
    to_outcome,
)
from friday.integration.sim import PersonaTelephony
from friday.liveagent.contracts import (
    ApprovalRequest,
    CallLanguage,
    Commitment,
    LiveCallResult,
)
from friday.liveagent.contracts import CalleeKind as LiveKind
from friday.liveagent.contracts import CallOutcome as LiveOutcome
from friday.liveagent.contracts import OutcomeStatus as LiveStatus

NUMBER = "+919000000001"


def w1_brief(**kw) -> CallBrief:  # noqa: ANN003
    base = dict(
        request_id="r1", user_id="u1", callee_kind=CalleeKind.FAMILY_FRIEND, callee_name="Mummy",
        goal="main late hoon", must_say=["main late hoon"], relationship="mother",
        user_display_name="Rahul", language="hinglish", shareable_facts=["main late hoon"],
    )  # fmt: skip
    base.update(kw)
    return CallBrief(**base)


def callee(kind: CalleeKind = CalleeKind.FAMILY_FRIEND, seconds: int = 120) -> Callee:
    return Callee(name="Mummy", number=NUMBER, kind=kind, max_duration_s=seconds)


def result(status: LiveStatus, **kw) -> LiveCallResult:  # noqa: ANN003
    return LiveCallResult(outcome=LiveOutcome(status=status, summary="English words", **kw))


# ------------------------------------------------------------------------------- kinds
def test_every_live_status_has_a_w1_status():
    assert set(STATUS_MAP) == set(LiveStatus)


@pytest.mark.parametrize(
    ("kind", "rel", "expect"),
    [
        (CalleeKind.FAMILY_FRIEND, "mother", LiveKind.FAMILY_ELDER),
        (CalleeKind.FAMILY_FRIEND, "father", LiveKind.FAMILY_ELDER),
        (CalleeKind.FAMILY_FRIEND, "friend", LiveKind.FRIEND),
        (CalleeKind.FAMILY_FRIEND, None, LiveKind.FRIEND),
        (CalleeKind.PROVIDER, "plumber", LiveKind.PROVIDER),
        (CalleeKind.CUSTOMER_CARE, None, LiveKind.CUSTOMER_CARE),
        (CalleeKind.OFFICIAL, None, LiveKind.OFFICIAL),
        (CalleeKind.UNKNOWN, None, LiveKind.UNKNOWN),
        (CalleeKind.BUSINESS, None, LiveKind.BUSINESS),
        (CalleeKind.GROUP, None, LiveKind.UNKNOWN),
    ],
)
def test_kind_mapping(kind, rel, expect):
    assert live_kind(kind, rel) == expect


def test_language_mapping_falls_back_to_hinglish():
    assert live_language("en") == CallLanguage.EN
    assert live_language("hi") == CallLanguage.HI
    assert live_language("klingon") == CallLanguage.HINGLISH


# ------------------------------------------------------------------------------- brief
def test_brief_fields_carry_over_and_facts_become_dicts():
    b = w1_brief(
        must_not_say=["OTP"], private_facts=["salary 85000"],
        limits=Limits(max_price_inr=1500), tone="warm",
    )  # fmt: skip
    live = to_live_brief(b, callee=callee(seconds=90))
    assert live.user_name == "Rahul" and live.callee_name == "Mummy"
    assert live.relationship == LiveKind.FAMILY_ELDER and live.tone == "warm"
    assert live.limits.max_amount_inr == 1500 and live.limits.max_call_seconds == 90
    assert live.private_facts == {"private1": "salary 85000"}
    assert live.shareable_facts == {"fact1": "main late hoon"}
    assert live.must_not_say == ["OTP"]
    assert live.voicemail_allowed is False  # W1's brief has no voicemail consent yet


def test_a_promise_is_never_pre_approved_by_the_bridge():
    live = to_live_brief(w1_brief())
    assert live.limits.allowed_commitments == [] and live.limits.allowed_times == []


def test_inform_purpose_is_said_once_not_twice():
    live = to_live_brief(w1_brief())
    assert live.goal_spoken == "main late hoon" and live.must_say == []


def test_question_purpose_gets_a_fixed_lead_in_and_the_ask_list_carries_it():
    b = w1_brief(goal="fees ki last date", must_say=[], ask_list=["fees ki last date"])
    live = to_live_brief(b)
    assert live.ask_list == ["fees ki last date"]
    assert live.goal_spoken == copy.spoken("goal_spoken_ask", "hinglish")


def test_unnamed_user_gets_the_pending_neutral_word():
    live = to_live_brief(w1_brief(user_display_name=None))
    assert live.user_name == copy.spoken("unnamed_user", "hinglish")


def test_group_parent_has_no_callee_name():
    live = to_live_brief(w1_brief(callee_kind=CalleeKind.GROUP, callee_name="Raj, Neha"))
    assert live.callee_name is None


# ------------------------------------------------------------------------------- outcome
def test_completed_inform_has_a_delivered_line_and_no_english():
    out = to_outcome("r1", result(LiveStatus.COMPLETED), delivered=True)
    assert out.status == OutcomeStatus.COMPLETED
    assert out.summary == copy.line("summary_delivered", "hinglish")
    assert "English words" not in out.summary


def test_do_not_call_sets_the_opt_out_and_the_flag():
    out = to_outcome("r1", result(LiveStatus.DO_NOT_CALL))
    assert out.status == OutcomeStatus.OPTED_OUT and out.do_not_call_again is True


def test_wrong_number_distress_hostile_map_to_the_stop_statuses():
    assert to_outcome("r", result(LiveStatus.WRONG_NUMBER)).status == OutcomeStatus.WRONG_PERSON
    for st in (LiveStatus.DISTRESS, LiveStatus.HOSTILE):
        assert to_outcome("r", result(st)).status == OutcomeStatus.SAFETY_STOP


def test_voicemail_left_is_not_retried_but_no_message_is():
    left = to_outcome("r", result(LiveStatus.VOICEMAIL_LEFT))
    assert left.status == OutcomeStatus.PARTIAL and not left.status.is_retryable
    assert left.next_actions == [NextAction.CALL_AGAIN, NextAction.SEND_MESSAGE]
    assert to_outcome("r", result(LiveStatus.VOICEMAIL_NO_MESSAGE)).status.is_retryable


def test_commitments_and_approvals_travel_with_their_flags():
    o = LiveOutcome(
        status=LiveStatus.NEEDS_USER_APPROVAL,
        summary="x",
        commitments=[
            Commitment(kind="time", text="kal 10 baje", within_limits=True),
            Commitment(kind="visit", text="parso aayenge", within_limits=False),
        ],
        needs_user_approval=[ApprovalRequest(kind="payment", text="Rs 500 advance", reason="r")],
    )
    out = to_outcome("r", LiveCallResult(outcome=o))
    assert out.status == OutcomeStatus.PARTIAL
    assert [(c.text, c.needs_user_approval) for c in out.commitments] == [
        ("kal 10 baje", False),
        ("parso aayenge", True),
    ]
    assert out.needs_user_approval == ["Rs 500 advance"]


def test_answers_unanswered_health_and_callback_become_hinglish_summary():
    o = LiveOutcome(
        status=LiveStatus.PARTIAL,
        summary="x",
        answers={"dawai li?": "haan li"},
        callback_time="kal shaam 6 baje",
        next_actions=[
            "Still unanswered: kitne baje",
            "The callee mentioned a health problem ('sar dard')",
        ],
    )
    out = to_outcome("r", LiveCallResult(outcome=o))
    assert out.answers == {"dawai li?": "haan li"}
    assert (
        "kitne baje" in out.summary and "sehat" in out.summary and "kal shaam 6 baje" in out.summary
    )


# ------------------------------------------------------------------------------- the adapter
async def test_adapter_without_a_line_dials_nothing_and_fails_cleanly(caplog):
    caplog.set_level(logging.DEBUG, logger="friday")
    adapter = LiveEngineAdapter(None, clock=FakeClock())
    out = await adapter.run(w1_brief(), callee())
    assert out.status == OutcomeStatus.FAILED
    assert NUMBER[-10:] not in caplog.text and "9000000001" not in caplog.text


async def test_adapter_runs_the_w2_engine_against_a_persona():
    sim = PersonaTelephony({NUMBER: "friendly_elder"})
    adapter = LiveEngineAdapter(sim, clock=FakeClock())
    out = await adapter.run(w1_brief(), callee())
    assert out.status == OutcomeStatus.COMPLETED and out.duration_s > 0
    assert sim.dialled == [NUMBER]


def test_redirect_wins_and_the_allow_list_is_checked_against_the_target():
    core = SimpleNamespace(
        vendor_call_redirect_to="+919000000099",
        pilot_dial_blocked=lambda n: n != "+919000000099",
    )
    assert dial_target(core, NUMBER) == "+919000000099"
    blocked = SimpleNamespace(vendor_call_redirect_to=None, pilot_dial_blocked=lambda n: True)
    with pytest.raises(NoTelephony):
        dial_target(blocked, NUMBER)


async def test_adapter_dials_the_redirect_not_the_real_number():
    core = SimpleNamespace(
        vendor_call_redirect_to="+919000000099", pilot_dial_blocked=lambda n: False
    )
    sim = PersonaTelephony({"+919000000099": "friendly_elder"})
    adapter = LiveEngineAdapter(sim, core_settings=core, clock=FakeClock())
    out = await adapter.run(w1_brief(), callee())
    assert sim.dialled == ["+919000000099"] and out.status == OutcomeStatus.COMPLETED


# ------------------------------------------------------------------------------- opening line
@pytest.mark.parametrize("lang", ["hinglish", "en", "hi"])
@pytest.mark.parametrize(
    "kind",
    [CalleeKind.FAMILY_FRIEND, CalleeKind.PROVIDER, CalleeKind.CUSTOMER_CARE, CalleeKind.OFFICIAL],
)
async def test_the_approved_opening_is_what_the_line_hears_first(kind, lang):
    sim = PersonaTelephony({NUMBER: "friendly_elder"})
    brief = w1_brief(callee_kind=kind, language=lang, relationship="mother")
    opening = await LiveOpeningLineProvider().opening_line(brief, "Mummy")
    approved = brief.model_copy(update={"opening_line": opening})
    await LiveEngineAdapter(sim, clock=FakeClock()).run(approved, callee(kind))
    assert sim.lines[0].spoken[0][0] == opening
    assert "Rahul" in opening
