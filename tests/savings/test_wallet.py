# ruff: noqa: E501
from __future__ import annotations

import pytest
from sqlalchemy import text

from friday.savings.wallet import (
    SensitiveDataError,
    UserCard,
    ensure_not_sensitive,
    looks_sensitive,
    match_cards,
    parse_wallet_message,
)
from tests.savings.helpers import TODAY


def names(intent):
    return [(c.bank, c.card_name) for c in intent.cards]


def test_hinglish_add_two_cards():
    i = parse_wallet_message("mere paas HDFC Regalia aur SBI Cashback hai")
    assert i.kind == "add"
    assert names(i) == [("HDFC Bank", "Regalia"), ("SBI Card", "Cashback")]


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("I have Axis Magnus and ICICI Amazon Pay", [("Axis Bank", "Magnus"), ("ICICI Bank", "Amazon Pay")]),
        ("mere paas Axis Bank Ace credit card hai", [("Axis Bank", "Ace")]),
        ("mere paas HDFC Regalia, SBI Cashback & Kotak Myntra", [
            ("HDFC Bank", "Regalia"), ("SBI Card", "Cashback"), ("Kotak Mahindra Bank", "Myntra")]),
        ("my cards are IDFC First Wealth visa", [("IDFC FIRST Bank", "Wealth")]),
        ("add card HSBC Premier", [("HSBC", "Premier")]),
        ("mere paas Example Bank Alpha hai", [("Example Bank", "Alpha")]),
    ],
)
def test_add_examples(msg, expected):
    i = parse_wallet_message(msg)
    assert i.kind == "add" and names(i) == expected, i


def test_network_is_picked_out_of_the_name():
    i = parse_wallet_message("mere paas HDFC Regalia Visa hai")
    assert i.cards[0].network == "visa" and i.cards[0].card_name == "Regalia"


def test_card_without_a_name_is_asked_about():
    i = parse_wallet_message("mere paas HDFC credit card hai")
    assert i.kind == "add" and not i.cards and i.unclear == ["HDFC credit card"]


def test_unknown_bank_is_kept_but_marked():
    i = parse_wallet_message("mere paas Tinybank Gold hai")
    assert names(i) == [("Tinybank", "Gold")] and not i.cards[0].bank_known


def test_remove_and_list_and_none():
    r = parse_wallet_message("SBI Cashback hata do")
    assert r.kind == "remove" and names(r) == [("SBI Card", "Cashback")]
    assert parse_wallet_message("remove HDFC Regalia from my cards").kind == "remove"
    assert parse_wallet_message("mere cards").kind == "list"
    assert parse_wallet_message("my cards").kind == "list"
    assert parse_wallet_message("kal ka mausam kaisa hai").kind == "none"
    assert parse_wallet_message("Zomato pe 640").kind == "none"


@pytest.mark.parametrize(
    "msg",
    [
        "mere paas card 4111 1111 1111 1111 hai",
        "mera card number 4111111111111111",
        "card 4111-1111-1111-1111",
        "HDFC Regalia cvv 123",
        "mere paas HDFC Regalia hai, otp 482913",
        "expiry 12/28 cvv 456",
    ],
)
def test_card_numbers_and_secrets_are_refused(msg):
    assert looks_sensitive(msg)
    i = parse_wallet_message(msg)
    assert i.kind == "none" and i.sensitive and not i.cards


@pytest.mark.parametrize("msg", ["mere paas HDFC Regalia hai", "Zomato pe 640", "petrol 2000"])
def test_normal_messages_are_not_sensitive(msg):
    assert looks_sensitive(msg) is None


def test_model_refuses_card_number_looking_names():
    for bad in ("4111 1111 1111 1111", "Regalia 12345", "cvv 123"):
        with pytest.raises((SensitiveDataError, ValueError)):
            UserCard(user_id="u", bank="HDFC Bank", card_name=bad)
    with pytest.raises(ValueError):
        UserCard(user_id="u", bank="4111111111111111", card_name="Regalia")
    with pytest.raises(SensitiveDataError):
        ensure_not_sensitive("4111111111111111")


def test_card_has_no_field_for_numbers_or_secrets():
    fields = set(UserCard.model_fields)
    assert not {f for f in fields if any(w in f for w in ("number", "cvv", "expiry", "otp", "pin", "login"))}
    with pytest.raises(ValueError):
        UserCard(user_id="u", bank="HDFC Bank", card_name="Regalia", cvv="123")  # type: ignore[call-arg]


def test_match_cards():
    cards = [
        UserCard(user_id="u", bank="HDFC Bank", card_name="Regalia"),
        UserCard(user_id="u", bank="SBI Card", card_name="Cashback"),
        UserCard(user_id="u", bank="Axis Bank", card_name="Cashback"),
    ]
    assert [c.bank for c in match_cards(cards, "sbi cashback")] == ["SBI Card"]
    assert len(match_cards(cards, "cashback")) == 2
    assert match_cards(cards, "regalia")[0].bank == "HDFC Bank"
    assert match_cards(cards, "card") == []


def test_caps_are_per_month():
    c = UserCard(user_id="u", bank="HDFC Bank", card_name="Regalia").with_cap_used("fuel", 500, TODAY)
    assert c.caps_used_on(TODAY) == {"fuel": 500}
    assert c.with_cap_used("fuel", 100, TODAY).caps_used_on(TODAY) == {"fuel": 600}
    from datetime import timedelta

    assert c.caps_used_on(TODAY + timedelta(days=30)) == {}


# ------------------------------------------------------------------ at rest


async def _raw(db, table: str) -> str:
    async with db.engine.connect() as conn:
        return repr((await conn.execute(text(f"SELECT * FROM {table}"))).all())  # noqa: S608


async def test_wallet_is_encrypted_at_rest_and_round_trips(srepos, sdb, user_id):
    card = UserCard(
        user_id=user_id, bank="HDFC Bank", card_name="Regalia", network="visa", billing_day=12,
        monthly_spend_so_far_paise=1234500, points_balance=777, caps_used={"fuel": 4242},
        caps_month="2026-10",
    )
    await srepos.wallet.upsert(card)
    raw = await _raw(sdb, "wallet_cards")
    for secret in ("Regalia", "HDFC", "visa", "1234500", "4242", "777"):
        assert secret not in raw, secret
    assert "v1:" in raw  # AES-GCM envelope
    got = (await srepos.wallet.list(user_id))[0]
    assert (got.bank, got.card_name, got.network, got.billing_day) == ("HDFC Bank", "Regalia", "visa", 12)
    assert got.monthly_spend_so_far_paise == 1234500 and got.points_balance == 777
    assert got.caps_used == {"fuel": 4242} and got.card_key == "hdfc-bank/regalia"


async def test_wallet_is_per_user_and_unique_per_card(srepos, user_id, other_user_id):
    a = UserCard(user_id=user_id, bank="HDFC Bank", card_name="Regalia")
    await srepos.wallet.upsert(a)
    await srepos.wallet.upsert(a.model_copy(update={"billing_day": 5}))  # same card: update
    await srepos.wallet.upsert(UserCard(user_id=other_user_id, bank="HDFC Bank", card_name="Regalia"))
    mine = await srepos.wallet.list(user_id)
    assert len(mine) == 1 and mine[0].billing_day == 5
    assert len(await srepos.wallet.list(other_user_id)) == 1
    assert await srepos.wallet.get_by_key(other_user_id, "hdfc-bank/regalia") is not None
    assert await srepos.wallet.remove(user_id, "hdfc-bank/regalia")
    assert not await srepos.wallet.remove(user_id, "hdfc-bank/regalia")
    assert len(await srepos.wallet.list(other_user_id)) == 1
