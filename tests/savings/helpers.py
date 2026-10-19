"""Builders shared by the savings tests. Everything here is FAKE (Example Bank, example.invalid)."""

from __future__ import annotations

from datetime import date, timedelta

from friday.savings.rules import CardRule
from friday.savings.wallet import UserCard

TODAY = date(2026, 10, 19)
BANK = "Test Bank"


def rule(
    card: str = "Alpha",
    category: str = "food_delivery",
    rate_bp: int = 500,
    *,
    bank: str = BANK,
    cap: int | None = None,
    txn: int | None = None,
    min_spend: int = 0,
    excl: tuple[str, ...] = (),
    merchants: tuple[str, ...] = (),
    rtype: str = "cashback",
    age_days: int | None = 5,
    verified_by: str | None = "Test Person",
    valid_from: date | None = None,
    valid_to: date | None = None,
    source: str = "https://bank.test/page",
) -> CardRule:
    return CardRule(
        bank=bank,
        card_name=card,
        category=category,
        reward_type=rtype,
        rate_bp=rate_bp,
        monthly_cap_paise=cap,
        per_txn_cap_paise=txn,
        min_spend_paise=min_spend,
        exclusions=list(excl),
        merchants=list(merchants),
        source_url=source,
        checked_on=None if age_days is None else TODAY - timedelta(days=age_days),
        verified_by=verified_by,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def card(name: str = "Alpha", *, bank: str = BANK, user_id: str = "u1", **kw) -> UserCard:
    return UserCard(user_id=user_id, bank=bank, card_name=name, **kw)
