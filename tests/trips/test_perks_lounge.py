# ruff: noqa: E501
"""Card perks: the person-verified validator (same discipline as savings rules) and the lounge hint."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from friday.core.clock import IST
from friday.docunderstand.models import DocType
from friday.savings.wallet import UserCard
from friday.trips.builder import leg_from_fields
from friday.trips.lounge import lounge_hints
from friday.trips.models import TaskKind
from friday.trips.perks import (
    CardPerk,
    PerkKind,
    confidence,
    load_example_perks,
    load_perks,
    perks_from_csv,
    perks_to_csv,
    validate_perk,
)
from friday.trips.service import TripService
from friday.trips.store import MemoryPerkStore
from tests.trips.conftest import FLIGHT_OUT, INTL_OUT, make_doc

TODAY = date(2026, 11, 10)


def real_looking(**kw) -> CardPerk:
    """An INVENTED row that passes the validator (not a real offer: fake bank and card)."""
    base = {
        "bank": "Fictional Bank",
        "card_name": "Fictional Voyager",
        "perk": PerkKind.DOMESTIC_LOUNGE,
        "visits_per_period": 2,
        "period": "quarter",
        "source_url": "https://bank.test/voyager",
        "checked_on": date(2026, 11, 1),
        "verified_by": "A. Reviewer",
        "status": "served",
    }
    base.update(kw)
    return CardPerk(**base)


class Wallet:
    def __init__(self, *cards):
        self.cards = list(cards)

    async def list(self, user_id):
        return self.cards


def test_repo_ships_only_example_rows_and_the_validator_refuses_them():
    rows = load_example_perks()
    assert rows and all(r.is_example for r in rows)
    assert all("example.invalid" in r.source_url for r in rows)
    assert not load_perks(rows, TODAY).accepted
    assert all(
        any(i.code == "example_row" for i in r.issues) for r in load_perks(rows, TODAY).rejected
    )
    assert load_perks(
        rows, TODAY, allow_examples=True
    ).accepted  # dev flag only, and drafts stay out
    assert {r.perk for r in load_perks(rows, TODAY, allow_examples=True).accepted} == {
        PerkKind.DOMESTIC_LOUNGE,
        PerkKind.INTL_LOUNGE,
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ({"source_url": ""}, "missing_source"),
        ({"source_url": "not a link"}, "bad_source_url"),
        ({"checked_on": None}, "missing_checked_on"),
        ({"checked_on": date(2027, 1, 1)}, "future_checked_on"),
        ({"verified_by": "claude"}, "unverified"),
        ({"verified_by": None}, "unverified"),
        ({"verified_by": "AI"}, "unverified"),
        ({"status": "draft"}, "draft"),
        ({"valid_from": date(2026, 12, 1), "valid_to": date(2026, 11, 1)}, "bad_validity_window"),
    ],
)
def test_validator_rejects(change, code):
    assert any(i.code == code for i in validate_perk(real_looking(**change), TODAY))


def test_a_good_row_passes_and_duplicates_are_rejected():
    assert validate_perk(real_looking(), TODAY) == []
    res = load_perks([real_looking(), real_looking()], TODAY)
    assert len(res.accepted) == 1 and res.rejected[0].issues[0].code == "duplicate"


def test_confidence_follows_the_savings_staleness_thresholds():
    assert confidence(real_looking(checked_on=date(2026, 11, 1)), TODAY) == "high"
    assert confidence(real_looking(checked_on=date(2026, 9, 20)), TODAY) == "medium"
    assert confidence(real_looking(checked_on=date(2026, 6, 1)), TODAY) == "low"


def test_csv_roundtrip_and_unknown_column_is_refused():
    p = real_looking()
    again = perks_from_csv(perks_to_csv([p]))
    assert again[0].perk == p
    bad = perks_from_csv("bank,card_name,perk,commission\nX,Y,domestic_lounge,5\n")
    assert bad[0].perk is None and "commission" in bad[0].error


async def test_lounge_hint_for_a_matching_verified_card():
    leg = leg_from_fields(DocType.FLIGHT, FLIGHT_OUT).leg
    wallet = Wallet(UserCard(bank="Fictional Bank", card_name="Fictional Voyager"))
    hints = await lounge_hints("u", leg, wallet, MemoryPerkStore([real_looking()]), TODAY)
    assert len(hints) == 1 and hints[0].confidence == "high" and hints[0].airport == "DEL"


async def test_no_rule_means_no_hint_and_example_rows_are_never_served():
    leg = leg_from_fields(DocType.FLIGHT, FLIGHT_OUT).leg
    wallet = Wallet(
        UserCard(bank="Fictional Bank", card_name="Fictional Voyager"),
        UserCard(bank="Example Bank", card_name="Example Travel Card"),
    )
    assert await lounge_hints("u", leg, wallet, MemoryPerkStore([]), TODAY) == []
    assert await lounge_hints("u", leg, wallet, MemoryPerkStore(load_example_perks()), TODAY) == []
    assert await lounge_hints("u", leg, Wallet(), MemoryPerkStore([real_looking()]), TODAY) == []
    assert await lounge_hints("u", leg, None, MemoryPerkStore([real_looking()]), TODAY) == []


async def test_domestic_and_international_use_different_perks():
    wallet = Wallet(UserCard(bank="Fictional Bank", card_name="Fictional Voyager"))
    perks = MemoryPerkStore([real_looking(perk=PerkKind.INTL_LOUNGE)])
    dom = leg_from_fields(DocType.FLIGHT, FLIGHT_OUT).leg
    intl = leg_from_fields(DocType.FLIGHT, INTL_OUT).leg
    assert await lounge_hints("u", dom, wallet, perks, TODAY) == []
    assert len(await lounge_hints("u", intl, wallet, perks, TODAY)) == 1
    pp = MemoryPerkStore([real_looking(perk=PerkKind.PRIORITY_PASS)])
    assert len(await lounge_hints("u", dom, wallet, pp, TODAY)) == 1


async def test_expired_validity_window_is_not_served():
    leg = leg_from_fields(DocType.FLIGHT, FLIGHT_OUT).leg
    wallet = Wallet(UserCard(bank="Fictional Bank", card_name="Fictional Voyager"))
    perks = MemoryPerkStore([real_looking(valid_to=date(2026, 10, 1))])
    assert await lounge_hints("u", leg, wallet, perks, TODAY) == []


async def _lounge_message(tsettings, store, clock, docs, sender, alice, perks, wallet):
    svc = TripService(tsettings, store, clock, docs=docs, sender=sender, perks=perks, wallet=wallet)
    await docs.save(make_doc(alice.id, DocType.FLIGHT, FLIGHT_OUT))
    await svc.create_from_documents(alice.id)
    clock.set(
        datetime(2026, 11, 13, 8, 40, tzinfo=IST)
    )  # due 24 h before departure, after quiet hours
    out = await svc.run_user(alice.id)
    return [o for o in out if o.kind == TaskKind.LOUNGE.value], sender.texts(alice.id)


async def test_lounge_nudge_text_and_staleness(tsettings, store, clock, docs, sender, alice):
    old = real_looking(checked_on=date(2026, 9, 1))
    out, texts = await _lounge_message(
        tsettings,
        store,
        clock,
        docs,
        sender,
        alice,
        MemoryPerkStore([old]),
        Wallet(UserCard(bank="Fictional Bank", card_name="Fictional Voyager")),
    )
    msg = next(x for x in texts if "Fictional" in x)
    assert "ho sakta hai" in msg and "2026-09-01" in msg and "confirm" in msg
    assert "purana" in msg  # medium confidence is flagged
    assert not any(w in msg.lower() for w in ("upgrade", "apply", "new card", "offer"))


async def test_lounge_says_nothing_without_a_verified_rule(
    tsettings, store, clock, docs, sender, alice
):
    out, texts = await _lounge_message(
        tsettings,
        store,
        clock,
        docs,
        sender,
        alice,
        MemoryPerkStore(load_example_perks()),
        Wallet(UserCard(bank="Example Bank", card_name="Example Travel Card")),
    )
    assert not any("lounge" in x.lower() for x in texts)
    assert out and out[0].action == "skipped"
