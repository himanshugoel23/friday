# ruff: noqa: E501
from __future__ import annotations

import pytest

from friday.savings.categories import CATEGORY_KEYS, parse_purchase
from friday.savings.money import find_amounts, format_rate, format_rs, pct_of


def test_pct_of_rounds_half_up_to_the_paise():
    assert pct_of(64000, 500) == 3200
    assert pct_of(50, 100) == 1  # 0.5 paise -> 1 (half-up)
    assert pct_of(49, 100) == 0
    assert pct_of(999, 150) == 15  # 14.985
    assert pct_of(1, 5000) == 1  # 0.5 -> 1
    assert pct_of(3, 5000) == 2  # 1.5 -> 2
    assert pct_of(0, 2500) == 0


def test_pct_of_rejects_negative():
    with pytest.raises(ValueError):
        pct_of(-1, 100)


def test_format_rs_indian_grouping_and_paise():
    assert format_rs(0) == "Rs 0"
    assert format_rs(64000) == "Rs 640"
    assert format_rs(12_400_000) == "Rs 1,24,000"
    assert format_rs(3250) == "Rs 32.50"
    assert format_rs(105) == "Rs 1.05"
    assert format_rs(-500) == "-Rs 5"


def test_format_rate():
    assert [format_rate(x) for x in (500, 150, 125, 1, 2500)] == ["5", "1.5", "1.25", "0.01", "25"]


@pytest.mark.parametrize(
    "text, paise",
    [
        ("Zomato pe 640", [64000]),
        ("Rs. 1,240.50 due", [124050]),
        ("₹2k ka petrol", [200000]),
        ("1.5 lakh", [15_000_000]),
        ("2000 rupaye", [200000]),
        ("5 kg atta", []),  # not money
        ("call 9876543210", []),  # phone number
    ],
)
def test_find_amounts(text, paise):
    assert [h.paise for h in find_amounts(text)] == paise


@pytest.mark.parametrize(
    "text, amount, category, merchant",
    [
        ("Zomato pe 640", 64000, "food_delivery", "zomato"),
        ("swiggy 450 ka order", 45000, "food_delivery", "swiggy"),
        ("petrol 2000", 200000, "fuel", None),
        ("2000 ka diesel dalwana hai", 200000, "fuel", None),
        ("Amazon 12000 ka phone", 1_200_000, "electronics", "amazon"),
        ("Amazon pe 800 ka saman", 80000, "online_shopping", "amazon"),
        ("Blinkit 1,250", 125000, "grocery", "blinkit"),
        ("bigbasket se 3200 ki grocery", 320000, "grocery", "bigbasket"),
        ("Uber 350", 35000, "cab", "uber"),
        ("flight ticket 8500", 850000, "travel", None),
        ("bijli bill 1800", 180000, "bills_utilities", None),
        ("jio recharge 299", 29900, "mobile_recharge", None),
        ("house rent 25000", 2_500_000, "rent", None),
        ("netflix 649", 64900, "entertainment", "netflix"),
    ],
)
def test_parse_purchase_examples(text, amount, category, merchant):
    p = parse_purchase(text)
    assert p.complete, p
    assert (p.amount_paise, p.category, p.merchant) == (amount, category, merchant)


@pytest.mark.parametrize(
    "text, ask",
    [
        ("kuch kharidna hai", "amount"),
        ("Zomato pe kitna kharch hoga", "amount"),
        ("640 ka kharch hai", "category"),
        ("Zomato 500 ya 700", "which_amount"),
        ("restaurant ya hotel mein khana 900", "which_category"),
    ],
)
def test_parse_purchase_asks_when_unsure(text, ask):
    p = parse_purchase(text)
    assert p.ask == ask
    assert not p.complete


def test_every_keyword_and_merchant_category_is_a_known_key():
    from friday.savings.categories import KEYWORDS, MERCHANTS

    assert set(KEYWORDS) <= set(CATEGORY_KEYS)
    assert {c for c, _ in MERCHANTS.values()} <= set(CATEGORY_KEYS)
