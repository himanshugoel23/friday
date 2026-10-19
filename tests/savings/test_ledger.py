# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from friday.savings import copy
from friday.savings.calculator import best_card
from friday.savings.savings_ledger import BaselineKind, Outcome, SavingsLedger
from tests.savings.helpers import TODAY, card, rule


@pytest.fixture
def ledger(srepos, sclock):
    return SavingsLedger(srepos.ledger, sclock)


def ranking(spend=64000, cat="food_delivery", merchant="zomato", age=5, usual=None):
    wallet = [card("Alpha", user_id="u"), card("Beta", user_id="u")]
    if usual:
        wallet = [c.model_copy(update={"usual": c.card_name == usual}) for c in wallet]
    rules = [rule("Alpha", rate_bp=500, age_days=age), rule("Beta", rate_bp=300)]
    return best_card(spend, cat, wallet, rules, TODAY, merchant), wallet


async def test_recommendation_is_logged_but_not_counted_until_confirmed(ledger, user_id):
    r, w = ranking()
    e = await ledger.record_recommendation(user_id, r, w)
    assert e and e.outcome == Outcome.PENDING and not e.counted
    s = await ledger.monthly_summary(user_id)
    assert (s.saved_paise, s.counted, s.logged, s.awaiting_answer) == (0, 0, 1, 1)
    assert "koi figure nahi" in copy.monthly_summary(s)  # says nothing was confirmed, no number


async def test_confirmed_use_counts_against_the_next_best_card(ledger, user_id):
    r, w = ranking()  # Alpha 3200, Beta 1920
    e = await ledger.record_recommendation(user_id, r, w)
    assert e.baseline_kind == BaselineKind.NEXT_BEST and e.baseline_reward_paise == 1920
    done, changed = await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert changed and done.saved_paise == 3200 - 1920 == 1280 and done.counted
    s = await ledger.monthly_summary(user_id)
    assert (s.saved_paise, s.counted) == (1280, 1)
    text_ = copy.monthly_summary(s)
    assert "Rs 12.80" in text_ and "1 baar" in text_ and "doosre best card" in text_  # counterfactual stated


async def test_usual_card_is_the_baseline_when_set(ledger, user_id):
    r, w = ranking(usual="Beta")
    e = await ledger.record_recommendation(user_id, r, w)
    assert e.baseline_kind == BaselineKind.USUAL_CARD and e.baseline_card_key.endswith("/beta")
    done, _ = await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert done.saved_paise == 1280
    assert "usual card" in copy.monthly_summary(await ledger.monthly_summary(user_id))


async def test_recommending_the_usual_card_saves_nothing(ledger, user_id):
    r, w = ranking(usual="Alpha")
    e = await ledger.record_recommendation(user_id, r, w)
    assert e.baseline_kind == BaselineKind.USUAL_CARD
    assert e.baseline_reward_paise == e.recommended_reward_paise
    done, _ = await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert done.saved_paise == 0


async def test_single_card_wallet_has_no_counterfactual_so_saves_nothing(ledger, user_id):
    only = [card("Alpha", user_id="u")]
    r = best_card(64000, "food_delivery", only, [rule("Alpha")], TODAY)
    e = await ledger.record_recommendation(user_id, r, only)
    done, _ = await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert e.baseline_kind == BaselineKind.NONE and done.saved_paise == 0


async def test_other_card_or_skipped_never_counts(ledger, user_id):
    r, w = ranking()
    e = await ledger.record_recommendation(user_id, r, w)
    done, _ = await ledger.report_outcome(user_id, e.id, Outcome.USED_OTHER, "x/y")
    assert done.saved_paise == 0 and not done.counted
    r2, w2 = ranking(spend=10000)
    e2 = await ledger.record_recommendation(user_id, r2, w2)
    await ledger.report_outcome(user_id, e2.id, Outcome.SKIPPED)
    s = await ledger.monthly_summary(user_id)
    assert s.saved_paise == 0 and s.counted == 0 and s.logged == 2


async def test_no_double_counting(ledger, user_id):
    r, w = ranking()
    e1 = await ledger.record_recommendation(user_id, r, w)
    e2 = await ledger.record_recommendation(user_id, r, w)  # same purchase asked again today
    assert e1.id == e2.id
    a, changed_a = await ledger.report_outcome(user_id, e1.id, Outcome.USED_RECOMMENDED)
    b, changed_b = await ledger.report_outcome(user_id, e1.id, Outcome.USED_RECOMMENDED)  # double tap
    assert changed_a and not changed_b and a.saved_paise == b.saved_paise
    # an answer cannot be flipped afterwards either
    c, changed_c = await ledger.report_outcome(user_id, e1.id, Outcome.USED_OTHER)
    assert not changed_c and c.outcome == Outcome.USED_RECOMMENDED
    s = await ledger.monthly_summary(user_id)
    assert (s.saved_paise, s.counted, s.logged) == (1280, 1, 1)


async def test_different_purchase_is_a_new_entry(ledger, user_id):
    r, w = ranking(spend=64000)
    r2, _ = ranking(spend=70000)
    e1 = await ledger.record_recommendation(user_id, r, w)
    e2 = await ledger.record_recommendation(user_id, r2, w)
    assert e1.id != e2.id


async def test_low_confidence_recommendations_are_logged_not_counted(ledger, user_id):
    wallet = [card("Alpha", user_id="u"), card("Beta", user_id="u")]
    rules = [rule("Alpha", rate_bp=2500, age_days=120), rule("Beta", rate_bp=300)]  # Alpha: very stale
    r = best_card(64000, "food_delivery", wallet, rules, TODAY)
    assert r.top.card_name == "Alpha" and r.top.confidence <= 300
    e = await ledger.record_recommendation(user_id, r, wallet)
    done, _ = await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert done.saved_paise > 0 and not done.counted
    s = await ledger.monthly_summary(user_id)
    assert (s.saved_paise, s.counted, s.low_confidence_not_counted) == (0, 0, 1)


async def test_nothing_ranked_means_nothing_logged(ledger, user_id):
    r = best_card(64000, "food_delivery", [card("Alpha", user_id="u")], [], TODAY)
    assert await ledger.record_recommendation(user_id, r, []) is None


async def test_months_are_separate_and_users_are_separate(ledger, user_id, other_user_id, sclock):
    r, w = ranking()
    e = await ledger.record_recommendation(user_id, r, w)
    await ledger.report_outcome(user_id, e.id, Outcome.USED_RECOMMENDED)
    assert (await ledger.monthly_summary(other_user_id)).saved_paise == 0
    assert await ledger.report_outcome(other_user_id, e.id, Outcome.USED_RECOMMENDED) == (None, False)
    sclock.advance(40 * 86400)
    assert (await ledger.monthly_summary(user_id)).saved_paise == 0  # a new month starts at zero
    assert (await ledger.monthly_summary(user_id, "2026-10")).saved_paise == 1280


async def test_ledger_is_encrypted_at_rest(ledger, srepos, sdb, user_id):
    r, w = ranking()
    await ledger.record_recommendation(user_id, r, w)
    async with sdb.engine.connect() as conn:
        raw = repr((await conn.execute(text("SELECT * FROM savings_ledger"))).all())
    assert "food_delivery" not in raw and "zomato" not in raw and "alpha" not in raw and "64000" not in raw


