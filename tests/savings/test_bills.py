# ruff: noqa: E501
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from friday.core.clock import IST
from friday.core.config import Settings
from friday.core.models import NudgeKind, Urgency
from friday.proactive.guardrails import evaluate
from friday.savings import bills as B
from friday.savings.bills import BillKind, BillStatus, bill_reminders, parse_bill_text
from friday.savings.config import SavingsConfig
from tests.savings.helpers import TODAY


def ist(d: int, h: int, m: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, d, h, m, tzinfo=IST)


# ------------------------------------------------------------------ parsing


@pytest.mark.parametrize(
    "msg, kind, biller, amount, due",
    [
        ("BSES: Your electricity bill of Rs 1,240.50 is due on 25/10/2026. Pay now.",
         BillKind.ELECTRICITY, "BSES", 124050, date(2026, 10, 25)),
        ("Bijli bill 1240 rupaye, last date 25 Oct", BillKind.ELECTRICITY, "Bijli", 124000, date(2026, 10, 25)),
        ("Dear customer, your Tata Power bill amount Rs. 3,850 is payable by 02-Nov-2026",
         BillKind.ELECTRICITY, "Tata Power", 385000, date(2026, 11, 2)),
        ("IGL piped gas bill: Rs 640 due date 30/10/26", BillKind.GAS, "IGL", 64000, date(2026, 10, 30)),
        ("Delhi Jal Board water bill Rs 920, pay before 5 November 2026",
         BillKind.WATER, "Delhi Jal Board", 92000, date(2026, 11, 5)),
        ("JioFiber broadband bill: Rs 999 due on 1st Nov", BillKind.BROADBAND, "JioFiber", 99900, date(2026, 11, 1)),
        ("Jio: Your plan expires on 28 Oct 2026. Recharge with Rs 299 to continue.",
         BillKind.MOBILE, "Jio", 29900, date(2026, 10, 28)),
        ("Tata Play balance is low. Recharge Rs 450 before 24/10/2026.",
         BillKind.DTH, "Tata Play", 45000, date(2026, 10, 24)),
        ("bijli ka bill 1,850 rupaye hai, 27 tarikh tak bharna hai",
         BillKind.ELECTRICITY, "Bijli", 185000, date(2026, 10, 27)),
        ("Electricity bill due Oct 30, 2026 amount due Rs 2100", BillKind.ELECTRICITY, "Bijli", 210000, date(2026, 10, 30)),
    ],
)
def test_parse_examples(msg, kind, biller, amount, due):
    p = parse_bill_text(msg, TODAY)
    assert (p.kind, p.biller, p.amount_paise, p.due_date) == (kind, biller, amount, due), p
    assert p.usable and not p.missing


def test_credit_card_statement_total_and_minimum():
    p = parse_bill_text(
        "Your HDFC Bank credit card statement. Card ending 1234. Total Amount Due: Rs 12,500.00 "
        "Minimum Amount Due: Rs 625.00. Payment Due Date: 05-Nov-2026",
        TODAY,
    )
    assert p.kind == BillKind.CREDIT_CARD and p.biller == "HDFC Bank credit card"
    assert (p.amount_paise, p.min_due_paise, p.due_date) == (1_250_000, 62500, date(2026, 11, 5))


def test_missing_pieces_are_reported_not_guessed():
    p = parse_bill_text("Your electricity bill is Rs 800", TODAY)
    assert p.due_date is None and p.missing == ["due_date"] and not p.usable
    q = parse_bill_text("Water bill due on 28/10/2026", TODAY)
    assert q.amount_paise is None and q.missing == ["amount"] and q.usable
    r = parse_bill_text("kuch bhi 3 dates: 1/11/2026 aur 5/11/2026", TODAY)
    assert r.due_date is None  # two unlabelled dates: do not pick one


def test_implausible_dates_ignored():
    assert parse_bill_text("bill due 25/10/1999 Rs 500", TODAY).due_date is None


def test_a_long_account_number_is_never_taken_as_the_amount():
    p = parse_bill_text("BSES bill CA no 100234567890 amount Rs 700 due 25/10/2026", TODAY)
    assert p.amount_paise == 70000


def test_card_number_in_a_credit_card_forward_is_not_kept():
    p = parse_bill_text("credit card 4111 1111 1111 1111 total amount due Rs 900 due 05/11/2026", TODAY)
    bill = B.bill_from_parse("u", p, B.BillSource.FORWARDED)
    assert "4111" not in bill.model_dump_json()


def test_cvv_or_otp_in_a_forward_is_refused():
    p = parse_bill_text("electricity bill Rs 500 due 25/10/2026 otp 123456", TODAY)
    assert p.sensitive == "secret_word" and not p.usable


# ------------------------------------------------------------------ pay links


def test_pay_links_only_from_user_or_known_billers():
    assert B.known_pay_link("BSES") is None  # the table is empty: nothing invented
    assert B.choose_pay_link("BSES") == (None, None)
    assert B.choose_pay_link("BSES", user_supplied="https://bill.test/pay") == (
        "https://bill.test/pay", "user")
    assert B.choose_pay_link("BSES", forwarded="https://bill.test/f") == ("https://bill.test/f", "forwarded")
    assert B.choose_pay_link("BSES", user_supplied="http://insecure.test", forwarded=None) == (None, None)


def test_known_biller_link_used_when_present(monkeypatch):
    monkeypatch.setitem(B.KNOWN_BILLER_LINKS, "bses", "https://bill.test/bses")
    assert B.choose_pay_link("BSES") == ("https://bill.test/bses", "biller_known")
    assert B.choose_pay_link("BSES", user_supplied="https://mine.test/x")[1] == "user"


@pytest.mark.parametrize(
    "url",
    ["http://a.test/x", "https://localhost/x", "https://127.0.0.1/x", "https://u:p@a.test/x",
     "javascript:alert(1)", "upi://pay?pa=x@y", "https://a.test/ x", "https://a.test/" + "x" * 600, ""],
)
def test_bad_links_rejected(url):
    assert not B.valid_pay_link(url)


# ------------------------------------------------------------------ reminders


def cands(bills, now):
    return bill_reminders("u1", bills, now)


def test_three_stages_and_one_at_a_time(make_bill):
    b = make_bill("u1")  # due 25 Oct
    assert cands([b], ist(21, 12)) == []
    c = cands([b], ist(22, 9, 30))
    assert [x.dedupe_key for x in c] == [f"bill:{b.id}:d3"]
    assert [x.dedupe_key for x in cands([b], ist(23, 12))] == [f"bill:{b.id}:d3"]
    assert [x.dedupe_key for x in cands([b], ist(24, 9, 5))] == [f"bill:{b.id}:d1"]
    assert [x.dedupe_key for x in cands([b], ist(25, 9, 5))] == [f"bill:{b.id}:d0"]
    assert [x.dedupe_key for x in cands([b], ist(25, 23, 0))] == [f"bill:{b.id}:d0"]
    assert cands([b], ist(26, 9)) == []


def test_bill_added_late_gets_only_the_current_stage(make_bill):
    b = make_bill("u1")
    assert [x.data["stage"] for x in cands([b], ist(24, 12))] == ["d1"]


def test_candidate_shape_reason_and_buttons(make_bill):
    b = make_bill("u1", pay_link="https://bill.test/pay", pay_link_source="user")
    c = cands([b], ist(24, 10))[0]
    assert c.kind == NudgeKind.DATE_BASED and c.urgency == Urgency.NORMAL
    assert c.reason.startswith("aapne BSES ka bill add kiya tha") and "kal" in c.reason
    assert c.data["bill_id"] == b.id and c.data["expires_at"] > c.due_at
    assert "Rs 1,240" in c.data["text"] and "https://bill.test/pay" in c.data["text"]
    assert "Friday pay nahi karti" in c.data["text"]
    parsed = [B.parse_bill_button(x["id"]) for x in c.data["buttons"]]
    assert parsed == [(b.id, "paid"), (b.id, "snooze"), (b.id, "notmine")]
    assert all(len(x["title"]) <= 20 for x in c.data["buttons"])


def test_only_confirmed_unpaid_bills_of_that_user_remind(make_bill):
    now = ist(24, 10)
    assert cands([make_bill("u1", confirmed=False)], now) == []
    assert cands([make_bill("u1", status=BillStatus.PAID)], now) == []
    assert cands([make_bill("u1", status=BillStatus.DISMISSED)], now) == []
    assert cands([make_bill("u2")], now) == []
    assert len(cands([make_bill("u1")], now)) == 1


def test_snooze_is_silent_until_it_ends_then_reminds_once(make_bill):
    until = ist(23, 9)
    b = make_bill("u1", status=BillStatus.SNOOZED, snoozed_until=until)
    assert cands([b], ist(22, 12)) == []
    c = cands([b], ist(23, 9, 10))
    assert len(c) == 1 and c[0].dedupe_key.startswith(f"bill:{b.id}:snooze")
    assert cands([b], ist(26, 12)) == []  # past the due day: no endless nagging


def test_custom_reminder_days(make_bill):
    cfg = SavingsConfig(bill_reminder_days=(7, 0))
    b = make_bill("u1")
    assert [x.data["stage"] for x in bill_reminders("u1", [b], ist(19, 12), cfg)] == ["d7"]


def test_engine_guardrails_apply_quiet_hours_and_cap(make_bill):
    s = Settings(_env_file=None, mode="simulator", env="test")
    b = make_bill("u1")
    d3 = cands([b], ist(22, 9, 30))[0]
    ok = evaluate(d3, now=ist(22, 9, 30), settings=s)
    assert ok.action == "send"
    # over the daily cap -> a line of the morning digest, not a 4th message
    over = evaluate(d3, now=ist(22, 9, 30), settings=s, sent_today=s.proactive_daily_cap)
    assert over.action == "digest" and over.send_at is not None
    # quiet hours: the due-day reminder would be stale by morning, so it is dropped, not sent at night
    d0 = cands([b], ist(25, 22, 30))[0]
    q = evaluate(d0, now=ist(25, 22, 30), settings=s)
    assert q.action == "suppress"
    # an earlier stage in quiet hours waits for the morning
    late = bill_reminders("u1", [make_bill("u1", due_date=date(2026, 10, 30))], ist(27, 22, 30))[0]
    assert evaluate(late, now=ist(27, 22, 30), settings=s).action == "schedule"


async def test_proactive_engine_accepts_and_dedupes_a_bill_candidate(container, make_bill):
    """End to end through the real ProactiveEngine.process: stored once, never twice."""
    from friday.core.models import User, UserStatus

    c = container
    u = await c.repos.users.add(User(phone="+919800000111", status=UserStatus.ACTIVE))
    c.clock.set(ist(24, 10)) if hasattr(c.clock, "set") else c.clock.advance(0)
    now = c.clock.now()
    b = make_bill(u.id, due_date=(now + timedelta(days=1)).date())
    cand = bill_reminders(u.id, [b], now)
    assert cand
    first = await c.proactive.process(cand[0])
    assert first is not None and first.dedupe_key == cand[0].dedupe_key
    assert await c.proactive.process(cand[0]) is None  # same dedupe key: one nudge per stage


# ------------------------------------------------------------------ storage


async def test_bills_encrypted_at_rest_scoped_by_user(srepos, sdb, user_id, other_user_id, make_bill):
    b = make_bill(user_id, biller="Secret Biller", pay_link="https://bill.test/secret-path")
    await srepos.bills.save(b)
    async with sdb.engine.connect() as conn:
        raw = repr((await conn.execute(text("SELECT * FROM bills"))).all())
    assert "Secret Biller" not in raw and "secret-path" not in raw and "124000" not in raw
    got = await srepos.bills.get(user_id, b.id)
    assert got and got.biller == "Secret Biller" and got.amount_paise == 124000
    assert await srepos.bills.get(other_user_id, b.id) is None
    with pytest.raises(PermissionError):
        await srepos.bills.save(b.model_copy(update={"user_id": other_user_id}))
    assert [x.id for x in await srepos.bills.active_for_user(user_id)] == [b.id]
    b.status = BillStatus.PAID
    await srepos.bills.save(b)
    assert await srepos.bills.active_for_user(user_id) == []
