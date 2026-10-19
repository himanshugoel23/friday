# ruff: noqa: E501
from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from friday.savings.config import SavingsConfig
from friday.savings.rules import (
    EXAMPLE_VERIFIER,
    CardRule,
    freshness,
    is_active,
    load_example_rules,
    load_rules,
    make_card_key,
    rules_from_csv,
    rules_to_csv,
    validate_rule,
)
from tests.savings.helpers import TODAY, rule


def codes(r, **kw):
    return {i.code for i in validate_rule(r, TODAY, **kw)}


def test_valid_row_has_no_issues():
    assert codes(rule(source="https://bank.test/offers")) == set()


def test_missing_or_bad_source_rejected():
    assert "missing_source" in codes(rule(source=""))
    assert "bad_source_url" in codes(rule(source="not a link"))
    assert "bad_source_url" in codes(rule(source="ftp://bank.test/x"))


def test_future_and_missing_check_date_rejected():
    r = rule()
    assert "future_checked_on" in codes(r.model_copy(update={"checked_on": TODAY + timedelta(days=1)}))
    assert "missing_checked_on" in codes(rule(age_days=None))


@pytest.mark.parametrize("who", [None, "", "  ", "claude", "AI", "bot", "auto", "TBD"])
def test_unverified_rows_rejected(who):
    assert "unverified" in codes(rule(verified_by=who))


def test_draft_allowed_when_verification_not_required():
    assert "unverified" not in codes(rule(verified_by=None), require_verified=False)


@pytest.mark.parametrize("bp", [0, 2501, 99999])
def test_rate_out_of_range(bp):
    assert "rate_out_of_range" in codes(rule(rate_bp=bp))


def test_discount_has_a_wider_but_still_bounded_range():
    assert "rate_out_of_range" not in codes(rule(rtype="discount", rate_bp=4000))
    assert "rate_out_of_range" in codes(rule(rtype="discount", rate_bp=6000))


def test_bad_window_and_negative_money():
    r = rule(valid_from=TODAY, valid_to=TODAY - timedelta(days=1))
    assert "bad_validity_window" in codes(r)
    with pytest.raises(ValidationError):
        rule(cap=-1)


def test_unknown_category_rejected_by_the_model():
    with pytest.raises(ValidationError):
        rule(category="crypto_gains")


def test_example_rows_never_pass_unless_allowed():
    ex = load_example_rules()
    assert ex and all(r.is_example for r in ex)
    assert all(r.verified_by == EXAMPLE_VERIFIER for r in ex)
    assert all("example.invalid" in r.source_url and r.bank == "Example Bank" for r in ex)
    assert all("EXAMPLE" in r.notes for r in ex)
    assert "example_row" in codes(ex[0])
    assert "example_row" not in codes(ex[0], allow_examples=True)
    assert load_rules(ex, TODAY).accepted == []
    assert len(load_rules(ex, TODAY, allow_examples=True).accepted) == len(ex)


def test_loader_refuses_unverified_and_duplicates():
    good = rule(source="https://bank.test/a")
    draft = rule("Beta", verified_by=None, source="https://bank.test/b")
    dup = rule(source="https://bank.test/a")
    res = load_rules([good, draft, dup], TODAY)
    assert [r.card_name for r in res.accepted] == ["Alpha"]
    reasons = {c.code for rej in res.rejected for c in rej.issues}
    assert {"unverified", "duplicate"} <= reasons


def test_staleness_levels_and_config():
    cfg = SavingsConfig()
    assert freshness(rule(age_days=30), TODAY, cfg) == "fresh"
    assert freshness(rule(age_days=31), TODAY, cfg) == "stale"
    assert freshness(rule(age_days=91), TODAY, cfg) == "very_stale"
    assert freshness(rule(age_days=None), TODAY, cfg) == "unknown"
    assert freshness(rule(age_days=40), TODAY, SavingsConfig(stale_after_days=60)) == "fresh"


def test_validity_window():
    r = rule(valid_from=TODAY - timedelta(days=1), valid_to=TODAY + timedelta(days=1))
    assert is_active(r, TODAY)
    assert not is_active(r, TODAY + timedelta(days=2))
    assert not is_active(r, TODAY - timedelta(days=2))
    assert is_active(rule(), TODAY)


def test_card_key_ignores_filler_words():
    assert make_card_key("HDFC Bank", "Regalia") == "hdfc-bank/regalia"
    assert make_card_key("HDFC Bank", "Regalia Credit Card") == "hdfc-bank/regalia"
    assert make_card_key("Example Bank", "Example Cashback Card") == "example-bank/example-cashback"


def test_csv_round_trip_and_errors():
    rows = load_example_rules()
    again = rules_from_csv(rules_to_csv(rows))
    assert [r.rule for r in again] == rows
    bad = rules_from_csv(
        "bank,card_name,category,reward_type,rate_bp,source_url\n"
        "Test Bank,Gamma,nonsense,cashback,100,https://bank.test/x\n"
        "Test Bank,Gamma,fuel,cashback,abc,https://bank.test/x\n"
        "Test Bank,Gamma,fuel,cashback,100,https://bank.test/x\n"
    )
    assert [bool(r.rule) for r in bad] == [False, False, True]
    assert all(r.error for r in bad[:2])


def test_a_commission_column_cannot_exist():
    res = rules_from_csv("bank,card_name,category,reward_type,rate_bp,commission_bp\nA,B,fuel,cashback,100,5\n")
    assert len(res) == 1 and res[0].rule is None and "commission_bp" in (res[0].error or "")
    with pytest.raises(ValidationError):
        CardRule(bank="A", card_name="B", category="fuel", reward_type="cashback", rate_bp=100,
                 commission_bp=5)  # type: ignore[call-arg]
