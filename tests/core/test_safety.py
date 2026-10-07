from friday.core.models import AccountIdentifier, CallBrief, ContactTarget, TargetKind, TaskType
from friday.core.safety import check_keys, check_speech


def brief(**kw) -> CallBrief:
    return CallBrief(
        task_id="t",
        requester_user_id="u",
        task_type=TaskType.CUSTOMER_CARE,
        goal="Complaint about broadband outage",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Airtel", phone="+911800000000"),
        on_behalf_of="Rahul",
        **kw,
    )


def test_never_speaks_otp_pin_cvv():
    b = brief()
    assert not check_speech("Sure, the OTP is 482913", b).allowed
    assert not check_speech("His PIN is 4821", b).allowed
    assert not check_speech("CVV: 123", b).allowed


def test_long_numbers_need_approval():
    acct = AccountIdentifier(user_id="u", label="Airtel account", value="7012345678")
    assert not check_speech("The account number is 7012345678", brief()).allowed
    assert check_speech(
        "The account number is 70123 45678", brief(approved_identifiers=[acct])
    ).allowed


def test_money_times_and_short_numbers_ok():
    b = brief()
    assert check_speech("Can you do it for ₹150000 instead?", b).allowed
    assert check_speech("Budget is 250000 rupees", b).allowed
    assert check_speech("Is 6:30 pm on the 14th available for 2 people?", b).allowed
    assert check_speech("My ticket reference is 1234", b).allowed


def test_dtmf_rules():
    acct = AccountIdentifier(user_id="u", label="Airtel account", value="7012345678")
    assert check_keys("2", brief()).allowed
    assert check_keys("#", brief()).allowed
    assert not check_keys("7012345678#", brief()).allowed
    assert check_keys("7012345678#", brief(approved_identifiers=[acct])).allowed
    assert check_keys("SR123", brief(reference="123")).allowed is False


def test_postal_pin_code_is_not_a_secret():
    assert check_speech("Address hai Indiranagar, pin code 560038", brief()).allowed
    assert not check_speech("PIN code is 4821", brief()).allowed


def test_number_words_and_luhn():
    from friday.core.safety import luhn_valid, normalize_spoken_digits

    assert normalize_spoken_digits("double four, nine") == "44, 9"
    assert normalize_spoken_digits("char, aath, do") == "482"
    assert luhn_valid("4111 1111 1111 1111") and not luhn_valid("4111 1111 1111 1112")
    assert not check_speech(
        "Number is nine eight seven six five four three two one zero", brief()
    ).allowed
    assert not check_keys("4111111111111111", brief()).allowed


def test_key_buffer_resets_per_prompt():
    from friday.core.safety import KeyBuffer

    buf = KeyBuffer(brief())
    assert buf.check("1").allowed and buf.check("2").allowed
    assert not buf.check("3").allowed  # 1+2+3 -> "123" is an unapproved number
    buf.reset()
    assert buf.check("3").allowed


def test_check_commit_delegation_limits():  # SECURITY-27 helper
    from datetime import datetime

    from friday.core.clock import IST
    from friday.core.models import Delegation, UserAnswer
    from friday.core.safety import check_commit

    assert not check_commit(brief(), []).allowed
    assert check_commit(brief(), [UserAnswer(question_id="q", text="yes", approves=True)]).allowed
    assert check_commit(brief(approved_terms="Sat 6pm"), []).allowed
    d = Delegation(
        granted=True,
        max_price_inr=800,
        scope=["slot"],
        window_start=datetime(2026, 1, 6, 17, tzinfo=IST),
        window_end=datetime(2026, 1, 6, 19, tzinfo=IST),
    )
    b = brief(delegation=d)
    ok = check_commit(b, [], amount_inr=700, slot_at=datetime(2026, 1, 6, 18, tzinfo=IST),
                      decision="slot")  # fmt: skip
    assert ok.allowed
    assert not check_commit(
        b, [], amount_inr=900, slot_at=datetime(2026, 1, 6, 18, tzinfo=IST)
    ).allowed
    assert not check_commit(
        b, [], amount_inr=700, slot_at=datetime(2026, 1, 6, 20, tzinfo=IST)
    ).allowed
    assert not check_commit(b, [], amount_inr=700).allowed  # window set, slot unknown
    assert not check_commit(
        b, [], amount_inr=700, slot_at=datetime(2026, 1, 6, 18, tzinfo=IST), decision="venue"
    ).allowed
