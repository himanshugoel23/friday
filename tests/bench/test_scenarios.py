"""The shipped scenario file validates and holds no personal data."""

from __future__ import annotations

import re

import pytest

from friday.bench import scenarios as S


def test_shipped_file_validates():
    scs = S.load()
    assert len(scs) >= 30
    ids = [s.id for s in scs]
    assert len(ids) == len(set(ids))
    required = {
        "gmail_check", "subscriptions_list", "cancel_netflix", "order_pizza", "cab_fare_compare", "train_seats",
        "hotel_inr", "insurance_quotes", "haircut_booking", "cake_moms_birthday", "interview_tomorrow", "fever_advice",
        "chest_pain", "landlord_deposit", "fake_fuel_bill", "what_do_you_remember", "tell_a_joke", "cricket_score",
        "percent_math", "reply_in_hindi", "call_salon_price", "atta_price_quick_commerce", "where_is_my_order",
        "alarm_on_phone", "text_my_mom",
    }
    assert required <= set(ids)
    assert {s.expected_today for s in scs} == set(S.EXPECTED)
    assert any(len(s.messages) > 1 for s in scs)  # multi-turn is covered


def test_no_phone_numbers_or_emails_in_file():
    text = S.DEFAULT_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\+?\d{10,}", text)
    assert not re.search(r"[\w.]+@[\w.]+\.\w+", text)


def test_parse_rejects_bad_input():
    good = {"id": "a", "category": "c", "capability": "web", "messages": ["hi"], "expected_today": "works", "rules": ["not_flat_refusal"]}
    assert S.parse({"scenarios": [good]})[0].id == "a"
    for patch in (
        {"id": ""}, {"capability": "teleport"}, {"expected_today": "maybe"}, {"messages": []}, {"rules": ["nope"]},
        {"rules": []}, {"user": "klingon"},
    ):
        with pytest.raises(S.ScenarioError):
            S.parse({"scenarios": [{**good, **patch}]})
    with pytest.raises(S.ScenarioError):
        S.parse({"scenarios": [good, good]})  # duplicate id
    with pytest.raises(S.ScenarioError):
        S.parse({})
