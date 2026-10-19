# ruff: noqa: E501
"""Neutrality (B11): ranking takes no revenue input, and every recommendation explains itself."""

from __future__ import annotations

import ast
import inspect
import random
from pathlib import Path

import pytest

from friday.savings import calculator, rules
from friday.savings.calculator import (
    Confidence,
    Option,
    best_card,
    evaluate_rule,
    rank_key,
    rank_options,
)
from friday.savings.wallet import UserCard
from tests.savings.helpers import TODAY, card, rule

BANNED = (
    "revenue", "commission", "affiliate", "payout", "referral", "sponsor", "kickback",
    "partner", "bidding", "fee_to", "monetis", "monetiz", "ad_spend", "promoted",
)


def _bad(name: str) -> bool:
    low = name.lower()
    return any(b in low for b in BANNED)


@pytest.mark.parametrize("fn", [best_card, evaluate_rule, rank_key, rank_options])
def test_ranking_functions_take_no_revenue_like_input(fn):
    params = inspect.signature(fn).parameters
    assert not [p for p in params if _bad(p)], params


def test_models_have_no_revenue_like_field():
    for model in (rules.CardRule, UserCard):
        assert not [f for f in model.model_fields if _bad(f)], model
    assert not [f for f in Option.__dataclass_fields__ if _bad(f)]


def test_calculator_and_rules_source_never_mention_such_a_name():
    """Walk the syntax tree of the engine's code: no identifier, argument or attribute may be
    revenue-like (docstrings and comments are not identifiers, so they are free to explain)."""
    for module in (calculator, rules):
        tree = ast.parse(Path(inspect.getsourcefile(module)).read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.arg) or isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
        assert not [n for n in names if _bad(n)], (module.__name__, [n for n in names if _bad(n)])


def test_a_revenue_field_cannot_be_smuggled_into_a_rule():
    for extra in ("commission_bp", "affiliate_url", "revenue_share", "sponsored"):
        with pytest.raises(ValueError):
            rules.CardRule(bank="A", card_name="B", category="fuel", reward_type="cashback",
                           rate_bp=100, **{extra: 1})


def test_ordering_depends_only_on_reward_and_confidence():
    """Two worlds whose cards differ in everything EXCEPT reward and confidence (bank, names,
    sources, notes, caps, rule scope) are ordered the same way."""
    rng = random.Random(42)
    for _ in range(100):
        n = rng.randint(2, 6)
        rewards = [rng.randint(0, 5000) for _ in range(n)]
        confs = [rng.choice(list(Confidence)) for _ in range(n)]

        def build(tag: str, rewards=rewards, confs=confs, n=n):
            opts = []
            for i in range(n):
                opts.append(
                    Option(
                        card_key=f"k{i:02d}",
                        bank=f"{tag}-bank-{rng.random()}",
                        card_name=f"{tag}-{rng.random()}",
                        reward_paise=rewards[i],
                        reward_type=rng.choice(["cashback", "points", "discount"]),
                        rate_bp=rng.randint(1, 2500),
                        confidence=confs[i],
                        reason=f"{tag} reason {rng.random()}",
                        source_url=f"https://{tag}.test/{rng.random()}",
                        cap_remaining_paise=rng.choice([None, 0, 5]),
                    )
                )
            rng.shuffle(opts)
            return opts

        a = [o.card_key for o in rank_options(build("a"))]
        b = [o.card_key for o in rank_options(build("b"))]
        assert a == b
        expected = sorted(
            range(n), key=lambda i: (-(rewards[i] * int(confs[i])), -rewards[i], -int(confs[i]), f"k{i:02d}")
        )
        assert a == [f"k{i:02d}" for i in expected]


def test_the_cashier_cannot_be_bought_changing_unrelated_rule_fields_keeps_order():
    base = [rule("Alpha", rate_bp=500), rule("Beta", rate_bp=300)]
    wallet = [card("Alpha"), card("Beta")]
    before = [o.card_key for o in best_card(64000, "food_delivery", wallet, base, TODAY).options]
    changed = [
        r.model_copy(update={"notes": "partner promo", "source_url": "https://other.test/zzz"})
        for r in base
    ]
    after = [o.card_key for o in best_card(64000, "food_delivery", wallet, changed, TODAY).options]
    assert before == after


def test_every_option_has_an_explanation_clause():
    with pytest.raises(ValueError):
        Option(card_key="k", bank="b", card_name="n", reward_paise=1, reward_type="cashback",
               rate_bp=1, confidence=Confidence.HIGH, reason="   ")
    rng = random.Random(3)
    for _ in range(200):
        cat = rng.choice(["food_delivery", "fuel", "grocery"])
        r = rule("Alpha", cat, rng.randint(1, 2500), cap=rng.choice([None, 0, 100]),
                 min_spend=rng.choice([0, 10**6]), excl=rng.choice([(), (cat,)]))
        out = best_card(rng.randint(0, 10**6), cat, [card("Alpha")], [r], TODAY)
        assert all(o.reason.strip() for o in out.options)
