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
