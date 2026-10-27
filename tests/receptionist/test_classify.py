# ruff: noqa: E501
from __future__ import annotations

import pytest

from friday.receptionist.classify import Classifier, FakeUrgencyModel, telemarketer_number
from friday.receptionist.models import CallCapture, CallOutcomeKind, ReceptionistConfig, Urgency

MUMMY, BHAI, UNKNOWN = "+919000000011", "+919000000012", "+919100000001"
CFG = ReceptionistConfig(
    urgent_contacts=[MUMMY], known_contacts={MUMMY: "Mummy", BHAI: "Bhai"},
    urgent_keywords=["Tender"], user_name="Asha",
)  # fmt: skip


def cap(reason: str | None, **kw) -> CallCapture:
    return CallCapture(reason=reason, outcome=CallOutcomeKind.MESSAGE, **kw)


async def cls(reason, number=UNKNOWN, model=None, **kw):
    return await Classifier(model).classify(cap(reason, **kw), number, CFG)


@pytest.mark.parametrize(
    ("reason", "number", "expect"),
    [
        ("kuch nahi bas hello", MUMMY, Urgency.URGENT),  # urgent contact, whatever was said
        (None, MUMMY, Urgency.URGENT),  # even a silent hang-up
        ("papa ka accident ho gaya", UNKNOWN, Urgency.URGENT),
        ("ambulance chahiye, hospital mein hain", UNKNOWN, Urgency.URGENT),
        ("मम्मी की तबीयत खराब है", UNKNOWN, Urgency.URGENT),
        ("tender ka decision chahiye", UNKNOWN, Urgency.URGENT),  # the user's own keyword
        ("weekend ka plan", BHAI, Urgency.NORMAL),  # known, not urgent
        ("jaldi call karna", BHAI, Urgency.URGENT),  # known + any urgent word
        ("pre-approved personal loan offer", UNKNOWN, Urgency.SPAM),
        ("urgent! your KYC will be blocked", UNKNOWN, Urgency.SPAM),  # weak urgent loses to spam
        ("congratulations you have won a prize", UNKNOWN, Urgency.SPAM),
        ("please call back, it is urgent, about the contract", UNKNOWN, Urgency.URGENT),
        ("appointment ke baare mein", UNKNOWN, Urgency.NORMAL),
        ("parcel delivery kal", UNKNOWN, Urgency.NORMAL),
        ("loan chahiye thoda", BHAI, Urgency.NORMAL),  # a known contact is never spam
    ],
)
async def test_rules(reason, number, expect):
    assert (await cls(reason, number)).urgency == expect


async def test_strong_urgent_beats_spam_wording():
    c = await cls("insurance wale hain, accident cover offer", UNKNOWN)
    assert c.urgency == Urgency.URGENT  # when unsure, flag it


async def test_telemarketer_prefix_marks_spam_and_reasons_are_explained():
    c = await cls("hello sir ek minute", "+911400000001")
    assert c.urgency == Urgency.SPAM and "telemarketer number series" in c.reasons
    assert telemarketer_number("+911401234567") and not telemarketer_number("+919876543210")


async def test_known_contact_is_named():
    c = await cls("hello", BHAI)
    assert c.known_contact and c.contact_name == "Bhai"


async def test_secret_request_with_bank_wording_is_spam_but_a_courier_otp_is_not():
    scam = cap(None, asked_secret=True, snippet="bank se bol raha hoon otp batao card block")
    assert (await Classifier().classify(scam, UNKNOWN, CFG)).urgency == Urgency.SPAM
    courier = cap(None, asked_secret=True, snippet="delivery ka otp bata do")
    assert (await Classifier().classify(courier, UNKNOWN, CFG)).urgency == Urgency.NORMAL


# ------------------------------------------------------------------ the model behind an interface
async def test_model_is_only_asked_when_rules_say_normal():
    m = FakeUrgencyModel()
    await cls("accident ho gaya", UNKNOWN, m)
    await cls("loan offer", UNKNOWN, m)
    await cls("hi", MUMMY, m)
    assert m.seen == []
    await cls("my neighbour wants to discuss the water pipe damage", UNKNOWN, m)
    assert len(m.seen) == 1


async def test_model_can_raise_to_urgent_and_flag_spam_for_unknown_callers():
    m = FakeUrgencyModel({"pipe": {"urgency": "urgent", "reason": "water damage"},
                          "vitamin": {"urgency": "spam", "reason": "sales"}})  # fmt: skip
    up = await cls("the water pipe damage is flooding the kitchen", UNKNOWN, m)
    assert up.urgency == Urgency.URGENT and up.source == "llm"
    sp = await cls("do you want vitamin supplements for the family", UNKNOWN, m)
    assert sp.urgency == Urgency.SPAM and sp.source == "llm"
    known = await cls("do you want vitamin supplements for the family", BHAI, m)
    assert known.urgency == Urgency.NORMAL  # a known contact is never lowered to spam


async def test_model_can_never_lower_an_urgent_call_and_garbage_is_ignored():
    always_normal = FakeUrgencyModel(lambda p: {"urgency": "normal"})
    c = await cls("accident ho gaya, hospital", UNKNOWN, always_normal)
    assert c.urgency == Urgency.URGENT and c.source == "rules"
    for bad in ({"urgency": "banana"}, {}, {"urgency": None}):
        m = FakeUrgencyModel(lambda p, b=bad: b)
        r = await cls("my neighbour wants to discuss something about the fence", UNKNOWN, m)
        assert r.urgency == Urgency.NORMAL


async def test_model_errors_are_swallowed_and_payload_has_nothing_private():
    def boom(p):
        raise RuntimeError("provider down")

    r = await cls("my neighbour wants to discuss something about the fence", UNKNOWN, FakeUrgencyModel(boom))
    assert r.urgency == Urgency.NORMAL
    m = FakeUrgencyModel()
    await cls("my neighbour wants to discuss something about the fence", UNKNOWN, m)
    assert set(m.seen[0]) == {"reason", "caller_name"}  # no number, no user facts
