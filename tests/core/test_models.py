from datetime import date, datetime

import pytest
from pydantic import ValidationError

from friday.core.clock import IST, to_ist
from friday.core.models import (
    AccountIdentifier,
    Beneficiary,
    BusinessHours,
    CallBrief,
    CallOutcome,
    ContactTarget,
    Language,
    MidCallQuestion,
    OpeningPeriod,
    Quote,
    ReplyButton,
    Speaker,
    StayRequest,
    TargetKind,
    Task,
    TaskSpec,
    TaskStatus,
    TaskType,
    Transcript,
    UserAnswer,
    disclosure_line,
    normalize_phone,
    parse_button_id,
    question_button_id,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("98765 43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("whatsapp:+14155550100", "+14155550100"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_task_roundtrip_json():
    spec = TaskSpec(
        type=TaskType.BOOKING, goal="Haircut tomorrow 6pm", business_phone="+919800000001"
    )
    task = Task(requester_user_id="u1", type=TaskType.BOOKING, spec=spec)
    again = Task.model_validate_json(task.model_dump_json())
    assert again == task
    assert again.beneficiary.is_self
    assert spec.is_ready_to_call
    assert not TaskStatus.CALLING.is_terminal and TaskStatus.COMPLETED.is_terminal
    assert CallOutcome.BUSY.is_retryable and not CallOutcome.SUCCESS.is_retryable


def test_button_ids_and_limits():
    bid = question_button_id("q123", 1)
    assert parse_button_id(bid) == ("q", "q123", "1")
    assert parse_button_id("random") is None
    with pytest.raises(ValidationError):
        ReplyButton(id="x", title="this title is far too long")
    with pytest.raises(ValidationError):
        MidCallQuestion(task_id="t", text="?", options=["a", "b", "c", "d"])


def test_disclosure_and_languages():
    assert "AI assistant" in disclosure_line("Rahul", Language.EN)
    assert "Rahul" in disclosure_line("Rahul", Language.TA)  # falls back to Hinglish
    assert Language.HINGLISH.bcp47 == "hi-IN" and Language.TA.bcp47 == "ta-IN"


def _brief(**kw) -> CallBrief:
    return CallBrief(
        task_id="t",
        requester_user_id="u",
        task_type=TaskType.BOOKING,
        goal="Book",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks", phone="+919800000001"),
        on_behalf_of="Rahul",
        **kw,
    )


def test_brief_can_commit_only_with_approval():
    b = _brief()
    assert not b.can_commit([])
    assert not b.can_commit([UserAnswer(question_id="q", text="6pm")])
    assert b.can_commit([UserAnswer(question_id="q", text="yes", approves=True)])
    assert _brief(approved_terms="Sat 6pm, ₹400").can_commit([])
    assert "Rahul" in b.disclosure()


def test_business_hours():
    hours = BusinessHours(
        periods=[
            OpeningPeriod(weekday=0, open="10:00", close="13:00"),
            OpeningPeriod(weekday=0, open="14:00", close="20:00"),
        ]
    )
    mon_lunch = datetime(2026, 1, 5, 13, 30, tzinfo=IST)  # Monday
    assert hours.is_open(mon_lunch) is False
    assert to_ist(hours.next_open(mon_lunch)) == datetime(2026, 1, 5, 14, 0, tzinfo=IST)
    mon_night = datetime(2026, 1, 5, 21, 0, tzinfo=IST)
    assert to_ist(hours.next_open(mon_night)) == datetime(2026, 1, 12, 10, 0, tzinfo=IST)
    assert BusinessHours().is_open(mon_lunch) is None


def test_quote_negotiated_and_stay_nights():
    q = Quote(business_name="X", price_text="₹1500", amount_inr=1500, original_amount_inr=1800)
    assert q.negotiated
    stay = StayRequest(destination="Udaipur", check_in=date(2026, 2, 1), check_out=date(2026, 2, 3))
    assert stay.nights == 2


def test_identifiers_refuse_secrets():
    ident = AccountIdentifier(user_id="u", label="Airtel account number", value="1234567890")
    assert ident.masked.endswith("7890") and "1234" not in ident.masked
    with pytest.raises(ValidationError):
        AccountIdentifier(user_id="u", label="HDFC netbanking password", value="x")
    with pytest.raises(ValidationError):
        AccountIdentifier(user_id="u", label="card CVV", value="123")


def test_transcript_helpers():
    t = Transcript()
    t.add(Speaker.FRIDAY, "Hi")
    t.add(Speaker.CALLEE, "Haan boliye", language=Language.HI)
    assert t.last(Speaker.CALLEE).language == Language.HI
    assert t.render() == "FRIDAY: Hi\nCALLEE: Haan boliye"
    assert Beneficiary(person_id="p1").is_self is False
