# ruff: noqa: E501
"""Migration 0008, "delete everything" (DataPurger) and the rules CLI."""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import create_engine, inspect, text

from friday.core.models import User, UserStatus
from friday.db import migrate
from friday.savings import cli as scli
from friday.savings.bills import Bill
from friday.savings.rules import rules_to_csv
from friday.savings.savings_ledger import Outcome, SavingsLedger
from friday.savings.wallet import UserCard
from tests.savings.helpers import TODAY, card, rule

TABLES = {"wallet_cards", "card_rules", "bills", "savings_ledger"}


def test_migration_0008_creates_and_drops_the_tables(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    migrate.upgrade(url)
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    assert set(inspect(eng).get_table_names()) >= TABLES
    cols = {c["name"] for c in inspect(eng).get_columns("card_rules")}
    assert not {c for c in cols if any(w in c for w in ("commission", "revenue", "affiliate"))}
    wallet_cols = {c["name"] for c in inspect(eng).get_columns("wallet_cards")}
    assert not {c for c in wallet_cols if any(w in c for w in ("number", "cvv", "expiry", "otp", "pin"))}
    migrate.downgrade(url)
    assert not TABLES & set(inspect(eng).get_table_names())
    eng.dispose()


async def _count(db, table: str, user_id: str) -> int:
    async with db.engine.connect() as conn:
        return (await conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE user_id = :u"), {"u": user_id})).scalar_one()  # noqa: S608


async def test_delete_everything_removes_wallet_bills_and_ledger(srepos, repos, sdb, sclock, user_id, other_user_id):
    from friday.savings.calculator import best_card

    ledger = SavingsLedger(srepos.ledger, sclock)
    for uid in (user_id, other_user_id):
        await srepos.wallet.upsert(UserCard(user_id=uid, bank="Test Bank", card_name="Alpha"))
        await srepos.bills.save(Bill(user_id=uid, biller="BSES", due_date=date(2026, 10, 25), confirmed=True))
        w = [card("Alpha", user_id=uid), card("Beta", user_id=uid)]
        r = best_card(64000, "food_delivery", w, [rule("Alpha"), rule("Beta", rate_bp=300)], TODAY)
        e = await ledger.record_recommendation(uid, r, w)
        await ledger.report_outcome(uid, e.id, Outcome.USED_RECOMMENDED)
    for t in ("wallet_cards", "bills", "savings_ledger"):
        assert await _count(sdb, t, user_id) == 1

    counts = await repos.purger.purge_user(user_id)
    assert counts["wallet_cards"] == counts["bills"] == counts["savings_ledger"] == 1
    for t in ("wallet_cards", "bills", "savings_ledger"):
        assert await _count(sdb, t, user_id) == 0
        assert await _count(sdb, t, other_user_id) == 1  # nobody else's data is touched
    assert await srepos.wallet.list(user_id) == []
    assert (await ledger.monthly_summary(user_id)).logged == 0


async def test_user_delete_cascades(srepos, repos, sdb, user_id):
    await srepos.wallet.upsert(UserCard(user_id=user_id, bank="Test Bank", card_name="Alpha"))
    async with sdb.engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    assert await _count(sdb, "wallet_cards", user_id) == 0


# ------------------------------------------------------------------ CLI


def ns(**kw) -> argparse.Namespace:
    base = {"dry_run": False, "allow_examples": False, "scope": None, "checked_on": None,
            "source": None, "unverified": False, "stale": False}
    return argparse.Namespace(**{**base, **kw})


def test_cli_parser_shape():
    p = argparse.ArgumentParser()
    scli.add_parser(p.add_subparsers(dest="cmd"))
    a = p.parse_args(["savings", "rules", "verify", "x/y", "--by", "Asha"])
    assert (a.cmd, a.savings_cmd, a.rules_cmd, a.card_key, a.by) == (
        "savings", "rules", "verify", "x/y", "Asha"
    )
    assert p.parse_args(["savings", "rules", "import", "f.csv", "--dry-run"]).dry_run


async def test_cli_import_verify_list_flow(sdb, srepos, tmp_path):
    lines: list[str] = []
    out = lines.append
    draft = rule("Gamma", "fuel", 100, verified_by=None, source="https://bank.test/gamma")
    f = tmp_path / "rules.csv"
    f.write_text(rules_to_csv([draft]), encoding="utf-8")

    # dry run stores nothing
    assert await scli.run_rules(ns(rules_cmd="import", file=str(f), dry_run=True), sdb, today=TODAY, out=out) == 0
    assert await srepos.rules.all() == []
    # real import: stored as a DRAFT and never served
    assert await scli.run_rules(ns(rules_cmd="import", file=str(f)), sdb, today=TODAY, out=out) == 0
    assert "DRAFT" in "\n".join(lines)
    assert len(await srepos.rules.all()) == 1 and await srepos.rules.verified(TODAY) == []

    # a bot cannot verify; a person can
    assert await scli.run_rules(ns(rules_cmd="verify", card_key=draft.card_key, by="claude"), sdb, today=TODAY, out=out) == 1
    assert await srepos.rules.verified(TODAY) == []
    assert await scli.run_rules(ns(rules_cmd="verify", card_key=draft.card_key, by="Asha Rao", checked_on="2026-10-18"), sdb, today=TODAY, out=out) == 0
    served = await srepos.rules.verified(TODAY)
    assert [r.verified_by for r in served] == ["Asha Rao"] and served[0].checked_on == date(2026, 10, 18)

    # a future check date cannot be recorded
    assert await scli.run_rules(ns(rules_cmd="verify", card_key=draft.card_key, by="Asha Rao", checked_on="2026-12-01"), sdb, today=TODAY, out=out) == 1

    lines.clear()
    assert await scli.run_rules(ns(rules_cmd="list"), sdb, today=TODAY, out=out) == 0
    assert lines[0].startswith("served") and "Asha Rao" in lines[0]
    # a month later the same row is flagged stale
    lines.clear()
    await scli.run_rules(ns(rules_cmd="list", stale=True), sdb, today=date(2026, 12, 1), out=out)
    assert lines[0].startswith("stale")

    # export round trip
    dest = tmp_path / "out.csv"
    assert await scli.run_rules(ns(rules_cmd="export", file=str(dest)), sdb, today=TODAY, out=out) == 0
    assert "Gamma" in dest.read_text()


async def test_cli_refuses_examples_and_bad_rows(sdb, srepos, tmp_path):
    from friday.savings.rules import load_example_rules

    lines: list[str] = []
    f = tmp_path / "ex.csv"
    f.write_text(rules_to_csv(load_example_rules()), encoding="utf-8")
    assert await scli.run_rules(ns(rules_cmd="import", file=str(f)), sdb, today=TODAY, out=lines.append) == 1
    assert any("example_row" in x for x in lines) and await srepos.rules.all() == []
    # only with the dev flag
    assert await scli.run_rules(ns(rules_cmd="import", file=str(f), allow_examples=True), sdb, today=TODAY, out=lines.append) == 0
    assert len(await srepos.rules.all()) == len(load_example_rules())

    bad = tmp_path / "bad.csv"
    bad.write_text("bank,card_name,category,reward_type,rate_bp,commission_bp\nA,B,fuel,cashback,100,5\n")
    assert await scli.run_rules(ns(rules_cmd="import", file=str(bad)), sdb, today=TODAY, out=lines.append) == 1
    assert any("commission_bp" in x for x in lines)


async def test_repo_serves_examples_only_when_configured(sdb, sclock):
    from friday.savings.config import SavingsConfig
    from friday.savings.rules import load_example_rules
    from friday.savings.store import RulesRepo

    prod = RulesRepo(sdb, sclock, SavingsConfig(allow_example_rules=False))
    dev = RulesRepo(sdb, sclock, SavingsConfig(allow_example_rules=True))
    for r in load_example_rules():
        await prod.upsert(r)
    assert await prod.verified(TODAY) == []
    assert len(await dev.verified(TODAY)) == len(load_example_rules())
    assert User and UserStatus  # imported for the cascade test fixtures
