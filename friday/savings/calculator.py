"""Which of MY cards for this spend? Pure, deterministic, no model, no I/O.

    ranking = best_card(64_000, "food_delivery", wallet, rules, today, merchant="zomato")
    ranking.options[0].reward_paise, ranking.options[0].reason

Rules of the engine (tested, see tests/savings):
* Every rupee figure comes from the verified rules table and integer arithmetic (half-up to the
  paise). The language model never computes or invents one.
* Ordering depends ONLY on the reward and the confidence (``rank_key``); no field exists, here or in
  the rules table, for revenue, commission or a referral, so none can influence the answer.
* Stale or unverified rules lower the confidence and add "confirm on your card app".
* A card with no usable rule for this spend is listed as UNKNOWN, never as Rs 0.
* Every option carries a one-clause reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum

from friday.savings import copy
from friday.savings.config import DEFAULT_CONFIG, SavingsConfig
from friday.savings.money import pct_of
from friday.savings.rules import CardRule, RewardType, freshness, is_active, is_example
from friday.savings.wallet import UserCard


class Confidence(IntEnum):
    """Permille weight used in ranking: expected reward = reward x confidence."""

    LOW = 300
    MEDIUM = 700
    HIGH = 1000

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Option:
    card_key: str
    bank: str
    card_name: str
    reward_paise: int
    reward_type: str
    rate_bp: int
    confidence: Confidence
    reason: str  # one clause, never empty
    cap_remaining_paise: int | None = None  # None = no monthly cap
    cap_hit: bool = False
    exclusion: str | None = None  # the exclusion that removed the reward, if any
    stale: bool = False
    unverified: bool = False
    example: bool = False
    confirm_on_app: bool = False
    rule_scope: str = ""
    source_url: str = ""
    checked_on: date | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("every recommendation needs a reason clause")

    @property
    def display(self) -> str:
        return f"{self.bank} {self.card_name}"


@dataclass(frozen=True)
class UnknownCard:
    """A wallet card the rules table cannot answer for (no verified row for this spend)."""

    card_key: str
    display: str
    why: str  # "no_rules" | "no_rule_for_category"


@dataclass(frozen=True)
class Ranking:
    spend_paise: int
    category: str
    merchant: str | None
    options: tuple[Option, ...]
    unknown: tuple[UnknownCard, ...] = field(default_factory=tuple)

    @property
    def top(self) -> Option | None:
        return self.options[0] if self.options else None

    @property
    def nothing_earned(self) -> bool:
        return bool(self.options) and all(o.reward_paise == 0 for o in self.options)


def rank_key(reward_paise: int, confidence: int, card_key: str) -> tuple[int, int, int, str]:
    """The ONLY ordering rule. Inputs: reward, confidence, and the card key as a stable
    tie-break. Nothing else is visible here, by construction."""
    return (-(reward_paise * int(confidence)), -reward_paise, -int(confidence), card_key)


def rank_options(options: list[Option]) -> list[Option]:
    return sorted(options, key=lambda o: rank_key(o.reward_paise, o.confidence, o.card_key))


# ------------------------------------------------------------------ one rule


def cap_key(rule: CardRule) -> str:
    """Key of this rule's monthly cap inside ``UserCard.caps_used``."""
    return f"{rule.category}@{','.join(rule.merchants)}" if rule.merchants else rule.category


def _applies(rule: CardRule, category: str, merchant: str | None) -> bool:
    if rule.merchants and (merchant is None or merchant.lower() not in rule.merchants):
        return False
    return rule.category in (category, "all")


def _specificity(rule: CardRule) -> int:
    return (2 if rule.merchants else 0) + (1 if rule.category != "all" else 0)


def _exclusion(rule: CardRule, category: str, merchant: str | None) -> str | None:
    if category in rule.exclusions:
        return category
    if merchant and merchant.lower() in rule.exclusions:
        return merchant.lower()
    return None


def _confidence(rule: CardRule, today: date, config: SavingsConfig, unverified: bool) -> Confidence:
    fresh = freshness(rule, today, config)
    level = Confidence.HIGH
    if fresh == "stale":
        level = Confidence.MEDIUM
    if fresh in {"very_stale", "unknown"} or unverified or is_example(rule):
        level = Confidence.LOW
    if rule.reward_type == RewardType.POINTS:
        level = min(level, Confidence.MEDIUM)  # the rupee value of a point is an estimate
    return level


def evaluate_rule(
    rule: CardRule,
    card: UserCard,
    spend_paise: int,
    category: str,
    merchant: str | None,
    today: date,
    config: SavingsConfig = DEFAULT_CONFIG,
) -> Option:
    """Reward of ONE rule for ONE payment. Half-up to the paise; caps and exclusions applied."""
    unverified = not (rule.verified_by or "").strip()
    conf = _confidence(rule, today, config, unverified)
    fresh = freshness(rule, today, config)
    used = card.caps_used_on(today).get(cap_key(rule), 0)
    cap_left = None if rule.monthly_cap_paise is None else max(0, rule.monthly_cap_paise - used)
    excl = _exclusion(rule, category, merchant)

    reward = 0
    cap_hit = False
    min_unmet = rule.min_spend_paise > 0 and spend_paise < rule.min_spend_paise
    if not excl and not min_unmet and spend_paise > 0:
        reward = pct_of(spend_paise, rule.rate_bp)
        if rule.per_txn_cap_paise is not None and reward > rule.per_txn_cap_paise:
            reward, cap_hit = rule.per_txn_cap_paise, True
        if cap_left is not None and reward > cap_left:
            reward, cap_hit = cap_left, True

    reason = copy.reason_clause(
        category=category,
        rate_bp=rule.rate_bp,
        reward_type=rule.reward_type.value,
        reward_paise=reward,
        cap_left_paise=cap_left,
        cap_hit=cap_hit,
        per_txn_cap_paise=rule.per_txn_cap_paise,
        exclusion=excl,
        min_spend_paise=rule.min_spend_paise if min_unmet else None,
        zero_spend=spend_paise == 0,
    )
    return Option(
        card_key=card.card_key,
        bank=card.bank,
        card_name=card.card_name,
        reward_paise=reward,
        reward_type=rule.reward_type.value,
        rate_bp=rule.rate_bp,
        confidence=conf,
        reason=reason,
        cap_remaining_paise=cap_left,
        cap_hit=cap_hit,
        exclusion=excl,
        stale=fresh in {"stale", "very_stale"},
        unverified=unverified,
        example=is_example(rule),
        confirm_on_app=fresh != "fresh" or unverified,
        rule_scope=rule.scope,
        source_url=rule.source_url,
        checked_on=rule.checked_on,
    )


# ------------------------------------------------------------------ the question


def best_card(
    spend_paise: int,
    category: str,
    wallet: list[UserCard],
    rules: list[CardRule],
    today: date,
    merchant: str | None = None,
    *,
    include_unverified: bool = False,
    config: SavingsConfig = DEFAULT_CONFIG,
) -> Ranking:
    """Rank the user's own cards for one payment.

    ``rules`` is expected to come from the loader (verified rows only). Rows that slip through
    unverified are ignored unless ``include_unverified`` is set, and then carry LOW confidence.
    Expired rows (outside valid_from..valid_to) are ignored.
    """
    if spend_paise < 0:
        raise ValueError("spend must be >= 0")
    merchant = merchant.lower() if merchant else None
    by_card: dict[str, list[CardRule]] = {}
    for r in rules:
        if not is_active(r, today):
            continue
        if not include_unverified and not (r.verified_by or "").strip():
            continue
        by_card.setdefault(r.card_key, []).append(r)

    options: list[Option] = []
    unknown: list[UnknownCard] = []
    seen: set[str] = set()
    for card in wallet:
        if card.card_key in seen:
            continue
        seen.add(card.card_key)
        card_rules = by_card.get(card.card_key, [])
        if not card_rules:
            unknown.append(UnknownCard(card.card_key, card.display, "no_rules"))
            continue
        usable = [r for r in card_rules if _applies(r, category, merchant)]
        if not usable:
            unknown.append(UnknownCard(card.card_key, card.display, "no_rule_for_category"))
            continue
        best: tuple[Option, CardRule] | None = None
        for r in sorted(usable, key=lambda r: (-_specificity(r), r.scope)):
            opt = evaluate_rule(r, card, spend_paise, category, merchant, today, config)
            if best is None or opt.reward_paise > best[0].reward_paise:
                best = (opt, r)
        assert best is not None
        options.append(best[0])
    return Ranking(
        spend_paise=spend_paise,
        category=category,
        merchant=merchant,
        options=tuple(rank_options(options)),
        unknown=tuple(unknown),
    )
