# ruff: noqa: E501
from __future__ import annotations

import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from friday.savings.calculator import Confidence, best_card, cap_key, rank_key
from tests.savings.helpers import TODAY, card, rule


def top(spend, category, wallet, rules, merchant=None, **kw):
    return best_card(spend, category, wallet, rules, TODAY, merchant, **kw)


def test_basic_ranking_and_reason_clause():
    rules = [rule("Alpha", rate_bp=500, cap=30000), rule("Beta", rate_bp=300)]
    r = top(64000, "food_delivery", [card("Alpha"), card("Beta")], rules, "zomato")
    assert [o.card_name for o in r.options] == ["Alpha", "Beta"]
    a, b = r.options
    assert (a.reward_paise, b.reward_paise) == (3200, 1920)
    assert a.reason == "Food delivery pe 5% milega, cap me Rs 300 bacha hai"
    assert b.reason == "Food delivery pe 3% milega"
    assert a.cap_remaining_paise == 30000 and b.cap_remaining_paise is None
    assert a.confidence == Confidence.HIGH and not a.confirm_on_app


def test_monthly_cap_remaining_limits_the_reward():
    rules = [rule("Alpha", rate_bp=500, cap=30000)]
    w = [card("Alpha").with_cap_used("food_delivery", 29000, TODAY)]
    o = top(64000, "food_delivery", w, rules).options[0]
    assert o.reward_paise == 1000 and o.cap_hit and o.cap_remaining_paise == 1000
    assert "cap me Rs 10 bacha hai" in o.reason


def test_cap_exhausted_gives_zero_and_says_so():
    rules = [rule("Alpha", cap=30000)]
    w = [card("Alpha").with_cap_used("food_delivery", 30000, TODAY)]
    o = top(64000, "food_delivery", w, rules).options[0]
    assert o.reward_paise == 0 and o.cap_remaining_paise == 0
    assert "cap" in o.reason and "poora" in o.reason


def test_caps_reset_in_a_new_month():
    w = card("Alpha").with_cap_used("food_delivery", 30000, TODAY)
    next_month = TODAY + timedelta(days=20)
    r = best_card(64000, "food_delivery", [w], [rule("Alpha", cap=30000)], next_month)
    assert r.options[0].reward_paise == 3200


def test_per_txn_cap():
    o = top(1_000_000, "food_delivery", [card()], [rule(txn=5000)]).options[0]
    assert o.reward_paise == 5000 and o.cap_hit
    assert "ek payment pe Rs 50 tak hi" in o.reason


def test_min_spend():
    rules = [rule(min_spend=50000)]
    assert top(49999, "food_delivery", [card()], rules).options[0].reward_paise == 0
    assert top(50000, "food_delivery", [card()], rules).options[0].reward_paise == 2500
    assert "reward nahi milta" in top(100, "food_delivery", [card()], rules).options[0].reason


def test_exclusion_by_category_and_merchant():
    base = rule("Alpha", "all", 100, excl=("fuel", "zomato"))
    fuel = top(200000, "fuel", [card()], [base]).options[0]
    assert fuel.reward_paise == 0 and fuel.exclusion == "fuel"
    assert fuel.reason == "Petrol/diesel pe is card pe reward nahi milta"
    z = top(64000, "food_delivery", [card()], [base], "zomato").options[0]
    assert z.reward_paise == 0 and z.exclusion == "zomato"
    ok = top(64000, "food_delivery", [card()], [base], "swiggy").options[0]
    assert ok.reward_paise == 640 and ok.exclusion is None


def test_specific_rule_beats_base_when_it_pays_more_and_base_when_it_pays_more():
    rules = [rule("Alpha", "all", 100), rule("Alpha", "grocery", 400, cap=1000)]
    c = [card("Alpha")]
    assert top(100000, "grocery", c, rules).options[0].reward_paise == 1000  # cap-limited 4%
    big = top(10_000_000, "grocery", c, rules).options[0]
    assert big.reward_paise == 100000 and big.rule_scope == "all"  # cap hit, base 1% pays more


def test_merchant_rule_applies_only_to_that_merchant():
    rules = [rule("Alpha", "online_shopping", 1000, merchants=("amazon",))]
    assert top(100000, "online_shopping", [card()], rules, "amazon").options
    r = top(100000, "online_shopping", [card()], rules, "flipkart")
    assert not r.options and r.unknown[0].why == "no_rule_for_category"


def test_multiple_categories_use_only_the_matching_rule():
    rules = [rule("Alpha", "food_delivery", 500), rule("Alpha", "fuel", 100)]
    assert top(10000, "food_delivery", [card()], rules).options[0].reward_paise == 500
    assert top(10000, "fuel", [card()], rules).options[0].reward_paise == 100


def test_zero_spend():
    r = top(0, "food_delivery", [card("Alpha"), card("Beta")], [rule("Alpha"), rule("Beta", rate_bp=100)])
    assert all(o.reward_paise == 0 for o in r.options) and r.nothing_earned
    assert all(o.reason for o in r.options)


def test_negative_spend_is_an_error():
    with pytest.raises(ValueError):
        top(-1, "fuel", [card()], [rule()])


def test_cards_without_rules_are_unknown_not_zero():
    r = top(64000, "food_delivery", [card("Alpha"), card("Gamma")], [rule("Alpha")])
    assert [o.card_name for o in r.options] == ["Alpha"]
    assert [u.display for u in r.unknown] == ["Test Bank Gamma"] and r.unknown[0].why == "no_rules"


def test_duplicate_wallet_cards_counted_once():
    r = top(64000, "food_delivery", [card("Alpha"), card("Alpha Credit Card")], [rule("Alpha")])
    assert len(r.options) == 1


def test_stale_rule_lowers_confidence_and_asks_to_confirm():
    o = top(64000, "food_delivery", [card()], [rule(age_days=45)]).options[0]
    assert o.confidence == Confidence.MEDIUM and o.stale and o.confirm_on_app
    o2 = top(64000, "food_delivery", [card()], [rule(age_days=120)]).options[0]
    assert o2.confidence == Confidence.LOW and o2.stale
    assert top(64000, "food_delivery", [card()], [rule(age_days=30)]).options[0].confidence == (
        Confidence.HIGH
    )


def test_unverified_rule_ignored_by_default_and_low_confidence_when_included():
    rules = [rule(verified_by=None)]
    assert not top(64000, "food_delivery", [card()], rules).options
    o = top(64000, "food_delivery", [card()], rules, include_unverified=True).options[0]
    assert o.unverified and o.confidence == Confidence.LOW and o.confirm_on_app


def test_expired_and_future_rules_ignored():
    assert not top(1000, "fuel", [card()], [rule(category="fuel", valid_to=TODAY - timedelta(days=1))]).options
    assert not top(1000, "fuel", [card()], [rule(category="fuel", valid_from=TODAY + timedelta(days=1))]).options


def test_points_are_never_high_confidence():
    o = top(64000, "food_delivery", [card()], [rule(rtype="points")]).options[0]
    assert o.confidence == Confidence.MEDIUM and "points" in o.reason


def test_example_rows_are_flagged():
    ex = rule(bank="Example Bank", source="https://example.invalid/x", verified_by="EXAMPLE_NOT_REAL")
    o = top(64000, "food_delivery", [card(bank="Example Bank")], [ex]).options[0]
    assert o.example and o.confidence == Confidence.LOW


def test_ranking_weighs_reward_by_confidence():
    # Rs 10 from a 100-day-old rule (LOW) loses to Rs 6 from a fresh rule (HIGH)
    rules = [rule("Alpha", rate_bp=1000, age_days=100), rule("Beta", rate_bp=600)]
    r = top(10000, "food_delivery", [card("Alpha"), card("Beta")], rules)
    assert [o.card_name for o in r.options] == ["Beta", "Alpha"]
    # equal reward: higher confidence first, then card key
    rules = [rule("Alpha", age_days=45), rule("Beta")]
    r = top(10000, "food_delivery", [card("Alpha"), card("Beta")], rules)
    assert [o.card_name for o in r.options] == ["Beta", "Alpha"]


def test_rank_key_is_a_pure_function_of_reward_confidence_and_key():
    assert rank_key(100, 1000, "b") < rank_key(100, 700, "a")
    assert rank_key(100, 1000, "a") < rank_key(100, 1000, "b")


# ---------------------------------------------------------------- randomized properties
# (no extra dependency: a seeded random generator replays the same 600 cases every run)

CATS = ["food_delivery", "grocery", "fuel", "travel", "online_shopping", "bills_utilities"]


def _half_up(spend: int, bp: int) -> int:
    return int((Decimal(spend) * bp / Decimal(10000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _random_rule(rng: random.Random, name: str, category: str):
    return rule(
        name,
        category,
        rng.randint(1, 2500),
        cap=rng.choice([None, 0, 1, 500, 30000, 10**7]),
        txn=rng.choice([None, 1, 5000, 10**7]),
        min_spend=rng.choice([0, 0, 100, 50000]),
        excl=tuple(rng.sample(CATS, rng.randint(0, 2))),
        age_days=rng.choice([0, 10, 30, 31, 60, 91, 400]),
        rtype=rng.choice(["cashback", "points", "discount"]) if rng.random() < 0.3 else "cashback",
    )


def test_property_reward_respects_caps_rounding_and_bounds():
    rng = random.Random(20261019)
    for _ in range(600):
        category = rng.choice(CATS)
        r = _random_rule(rng, "Alpha", category)
        used = rng.choice([0, 0, 100, 29999, 30000, 10**8])
        w = card("Alpha").with_cap_used(cap_key(r), used, TODAY)
        spend = rng.choice([0, 1, 3, 49, 50, 999, 64000, rng.randint(0, 5_000_000)])
        out = best_card(spend, category, [w], [r], TODAY)
        assert len(out.options) == 1
        o = out.options[0]
        # never negative, never more than the spend, every option explains itself
        assert 0 <= o.reward_paise <= spend
        assert o.reason.strip()
        excluded = category in r.exclusions
        if excluded or spend < r.min_spend_paise or spend == 0:
            assert o.reward_paise == 0
            continue
        uncapped = _half_up(spend, r.rate_bp)  # exact half-up reference
        cap_left = None if r.monthly_cap_paise is None else max(0, r.monthly_cap_paise - used)
        bound = min(
            uncapped,
            r.per_txn_cap_paise if r.per_txn_cap_paise is not None else uncapped,
            cap_left if cap_left is not None else uncapped,
        )
        assert o.reward_paise == bound
        assert o.cap_remaining_paise == cap_left
        if cap_left is not None:
            assert o.reward_paise <= cap_left


def test_property_reward_is_monotonic_in_spend_without_caps():
    rng = random.Random(7)
    for _ in range(100):
        r = rule("Alpha", "fuel", rng.randint(1, 2500))
        prev = -1
        for spend in sorted(rng.randint(0, 10**7) for _ in range(8)):
            reward = best_card(spend, "fuel", [card("Alpha")], [r], TODAY).options[0].reward_paise
            assert reward >= prev
            prev = reward


def test_property_options_always_sorted_and_deterministic():
    rng = random.Random(99)
    for _ in range(200):
        names = ["Alpha", "Beta", "Gamma", "Delta"]
        rng.shuffle(names)
        rules = [_random_rule(rng, n, "grocery") for n in names]
        wallet = [card(n) for n in names]
        spend = rng.randint(0, 10**6)
        a = best_card(spend, "grocery", wallet, rules, TODAY)
        b = best_card(spend, "grocery", list(reversed(wallet)), list(reversed(rules)), TODAY)
        assert [o.card_key for o in a.options] == [o.card_key for o in b.options]
        keys = [rank_key(o.reward_paise, o.confidence, o.card_key) for o in a.options]
        assert keys == sorted(keys)


def test_property_stale_never_raises_confidence():
    rng = random.Random(5)
    for _ in range(100):
        age = rng.randint(0, 200)
        fresh = best_card(10000, "fuel", [card()], [rule(category="fuel", age_days=0)], TODAY)
        aged = best_card(10000, "fuel", [card()], [rule(category="fuel", age_days=age)], TODAY)
        assert aged.options[0].confidence <= fresh.options[0].confidence
