# ruff: noqa: E501
"""The WhatsApp-facing handlers, end to end over the real stores (EXAMPLE rules only)."""

from __future__ import annotations

from friday.savings import copy
from friday.savings.wallet import UserCard
from tests.savings.helpers import rule

CARDS = "mere paas Example Bank Example Cashback Card aur Example Bank Example Travel Card hai"


async def say(commands, user_id, text):
    r = await commands.handle(user_id, text)
    assert r is not None, text
    return r


async def test_unrelated_messages_are_not_ours(commands, user_id):
    for t in ("kal subah 7 baje alarm", "salon book karo", "", "hello"):
        assert await commands.handle(user_id, t) is None


async def test_add_cards_confirms_back_and_stores_only_names(commands, srepos, user_id):
    r = await say(commands, user_id, CARDS)
    assert "Maine note kiya" in r.text and "Example Bank Example Cashback" in r.text
    assert "number" not in r.text.lower() or "naam" in r.text
    cards = await srepos.wallet.list(user_id)
    assert {c.card_key for c in cards} == {"example-bank/example-cashback", "example-bank/example-travel"}
    again = await say(commands, user_id, "mere paas Example Bank Example Cashback hai")
    assert "pehle se the" in again.text and len(await srepos.wallet.list(user_id)) == 2


async def test_card_number_is_refused_and_nothing_is_stored(commands, srepos, user_id):
    r = await say(commands, user_id, "mere paas card 4111 1111 1111 1111 hai")
    assert r.text == copy.SENSITIVE_REFUSAL
    r2 = await say(commands, user_id, "mere paas HDFC Regalia hai, cvv 123")
    assert r2.text == copy.SENSITIVE_REFUSAL
    assert await srepos.wallet.list(user_id) == []


async def test_which_card_full_flow(commands, srepos, user_id):
    r0 = await say(commands, user_id, "kaun sa card Zomato pe 640")
    assert r0.text == copy.NO_CARDS_FOR_QUESTION  # no wallet yet
    await say(commands, user_id, CARDS)
    r = await say(commands, user_id, "kaun sa card Zomato pe 640")
    assert "Example Bank Example Cashback use kijiye, Rs 32 cashback" in r.text
    assert "Wajah: Food delivery pe 5% milega, cap me Rs 300 bacha hai" in r.text
    assert "[EXAMPLE data" in r.text and copy.NEUTRALITY_FOOTER in r.text
    assert "Example Travel" in r.text  # the other card is listed with its own figure and reason
    assert [b.title for b in r.buttons] == ["Isse pay kiya", "Doosra card", "Nahi kharida"]
    assert all(len(b.title) <= 20 for b in r.buttons)


async def test_which_card_asks_when_unsure(commands, user_id):
    await say(commands, user_id, CARDS)
    assert (await say(commands, user_id, "kaun sa card use karun")).text == copy.ASK_AMOUNT
    assert "kis cheez" in (await say(commands, user_id, "kaun sa card, 640 ka kharch")).text
    assert (await say(commands, user_id, "kaun sa card Zomato 500 ya 700")).text == copy.ASK_WHICH_AMOUNT


async def test_card_without_verified_rules_is_said_so(commands, srepos, user_id):
    await say(commands, user_id, "mere paas HDFC Regalia hai")
    r = await say(commands, user_id, "kaun sa card petrol 2000")
    assert "verified rules mere paas abhi nahi" in r.text and "HDFC Bank Regalia" in r.text
    assert not r.buttons  # nothing was recommended, so nothing is logged


async def test_example_rows_never_produce_a_savings_figure(commands, srepos, user_id):
    """EXAMPLE rows are LOW confidence: even a confirmed use is logged but never counted."""
    await say(commands, user_id, CARDS)
    r = await say(commands, user_id, "kaun sa card Zomato pe 640")
    assert (await commands.handle_button(user_id, r.buttons[0].id)).text == copy.OUTCOME_USED
    s = await say(commands, user_id, "is mahine kitna bachaya")
    assert "koi figure nahi" in s.text or "nahi gini" in s.text
    assert "Rs 25" not in s.text


async def test_outcome_buttons_feed_the_monthly_summary_once(commands, srepos, user_id):
    for r in (rule("Alpha", "food_delivery", 500, cap=30000), rule("Beta", "all", 100)):
        await srepos.rules.upsert(r)
    for name in ("Alpha", "Beta"):
        await srepos.wallet.upsert(UserCard(user_id=user_id, bank="Test Bank", card_name=name))
    r = await say(commands, user_id, "kaun sa card Zomato pe 640")
    assert "Test Bank Alpha use kijiye, Rs 32 cashback" in r.text and "EXAMPLE" not in r.text
    used = r.buttons[0].id
    assert used.startswith("led:")
    assert (await commands.handle_button(user_id, used)).text == copy.OUTCOME_USED
    assert (await commands.handle_button(user_id, used)).text == copy.OUTCOME_ALREADY
    # asking the very same question again does not create a second countable entry
    r_again = await say(commands, user_id, "kaun sa card Zomato pe 640")
    assert r_again.buttons == []  # already answered
    summ = await say(commands, user_id, "is mahine kitna bachaya")
    # Alpha 5% = Rs 32.00; Beta's base 1% = Rs 6.40; saved = Rs 25.60, counted once
    assert "Rs 25.60" in summ.text and "1 baar" in summ.text and "doosre best card" in summ.text
    caps = {c.card_name: c.caps_used for c in await srepos.wallet.list(user_id)}
    assert caps["Alpha"] == {"food_delivery": 3200} and caps["Beta"] == {}
    # the card's monthly cap is now partly used: asking for another order reflects it
    r2 = await say(commands, user_id, "kaun sa card Zomato pe 900")
    assert "cap me Rs 268 bacha hai" in r2.text


async def test_summary_with_nothing_confirmed_gives_no_number(commands, user_id):
    await say(commands, user_id, CARDS)
    await say(commands, user_id, "kaun sa card Zomato pe 640")  # asked, never confirmed
    s = await say(commands, user_id, "Friday ne kitna bachaya")
    assert "koi figure nahi" in s.text and "Rs" not in s.text.split("figure")[0]


async def test_remove_and_list_cards(commands, srepos, user_id):
    await say(commands, user_id, CARDS)
    assert "Example Cashback" in (await say(commands, user_id, "mere cards")).text
    r = await say(commands, user_id, "Example Bank Example Travel hata do")
    assert r.text.startswith("Hata diya: Example Bank Example Travel")
    assert [c.card_name for c in await srepos.wallet.list(user_id)] == ["Example Cashback"]
    nf = await say(commands, user_id, "Regalia hata do")
    assert "nahi mila" in nf.text
    await say(commands, user_id, "mere paas HDFC Regalia aur Axis Regalia hai")
    amb = await say(commands, user_id, "Regalia hata do")
    assert "ek se zyada" in amb.text


async def test_usual_card_is_set(commands, srepos, user_id):
    await say(commands, user_id, CARDS)
    r = await say(commands, user_id, "mera usual card Example Bank Example Travel hai")
    assert "usual card hai" in r.text
    flags = {c.card_name: c.usual for c in await srepos.wallet.list(user_id)}
    assert flags == {"Example Cashback": False, "Example Travel": True}


FORWARD = "BSES: Your electricity bill of Rs 1,240.50 is due on 25/10/2026. Pay at https://bill.test/pay/xyz"


async def test_bill_forward_is_parsed_confirmed_and_listed(commands, srepos, user_id):
    r = await say(commands, user_id, FORWARD)
    assert "Maine ye samjha: BSES (Bijli) bill, Rs 1,240.50, due 25 Oct" in r.text
    assert [b.title for b in r.buttons] == ["Sahi hai", "Galat hai"]
    assert (await srepos.bills.active_for_user(user_id)) == []  # unconfirmed: no reminders yet
    ok = await commands.handle_button(user_id, r.buttons[0].id)
    assert "yaad rakhungi" in ok.text and "https://bill.test/pay/xyz" in ok.text
    lst = await say(commands, user_id, "meri bills")
    assert "BSES (Bijli): Rs 1,240.50, due 25 Oct (6 din baad)" in lst.text


async def test_bill_buttons_paid_snooze_notmine(commands, srepos, user_id, sclock):
    r = await say(commands, user_id, FORWARD)
    bill_id = r.buttons[0].id.split(":")[1]
    await commands.handle_button(user_id, r.buttons[0].id)

    sn = await commands.handle_button(user_id, f"bill:{bill_id}:snooze")
    assert "kal subah 9 baje" in sn.text
    b = await srepos.bills.get(user_id, bill_id)
    assert b.status.value == "snoozed" and b.snoozed_until.hour in (3, 4)  # 9:00 IST = 03:30 UTC
    assert "[snoozed]" in (await say(commands, user_id, "meri bills")).text

    paid = await commands.handle_button(user_id, f"bill:{bill_id}:paid")
    assert "paid mark" in paid.text
    assert (await say(commands, user_id, "meri bills")).text == copy.BILLS_NONE

    # "Not mine" on a second bill removes it
    r2 = await say(commands, user_id, "Tata Power bill Rs 900 due 28/10/2026")
    nm = await commands.handle_button(user_id, r2.buttons[1].id)
    assert nm.text == copy.BILL_DISMISSED
    assert await srepos.bills.active_for_user(user_id) == []


async def test_bill_buttons_cannot_touch_another_users_bill(commands, srepos, user_id, other_user_id):
    r = await say(commands, user_id, FORWARD)
    bill_id = r.buttons[0].id.split(":")[1]
    res = await commands.handle_button(other_user_id, f"bill:{bill_id}:paid")
    assert res.text == copy.BILL_UNKNOWN
    assert (await srepos.bills.get(user_id, bill_id)).status.value == "pending"


async def test_bill_without_due_date_asks(commands, srepos, user_id):
    r = await say(commands, user_id, "electricity bill hai Rs 800 bharna hai")
    assert "due date" in r.text and not r.buttons
    assert await srepos.bills.list_for_user(user_id, confirmed_only=False) == []


async def test_bill_forward_with_card_number_never_stores_it(commands, srepos, user_id):
    r = await say(commands, user_id, "credit card 4111 1111 1111 1111 total amount due Rs 900 due 05/11/2026")
    assert r.buttons
    stored = await srepos.bills.list_for_user(user_id, confirmed_only=False)
    assert "4111" not in stored[0].model_dump_json()


async def test_unknown_buttons_are_ignored(commands, user_id):
    assert await commands.handle_button(user_id, "n:abc:yes") is None
    assert await commands.handle_button(user_id, "bill:x:explode") is None
    assert (await commands.handle_button(user_id, "led:nope:used")).text == copy.OUTCOME_UNKNOWN


def test_all_copy_is_marked_pending_founder_approval():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "PENDING_FOUNDER_APPROVAL" in (copy.__doc__ or "")


def test_no_user_facing_strings_outside_copy_py():
    """The handlers and logic modules hold no Hinglish sentences; the text lives in copy.py."""
    import ast
    import inspect
    import re

    from friday.savings import bills, calculator, commands, savings_ledger

    marker = re.compile(r"\b(hai|kijiye|nahi|milega|dobara|bacha|aapne|aapka)\b", re.I)
    for mod in (calculator, commands, savings_ledger, bills):
        tree = ast.parse(inspect.getsource(mod))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
        found = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
        ]
        # patterns that MATCH user words (kaun sa, hata do ...) are input, not output text
        offenders = [
            s for s in found if len(s) >= 12 and marker.search(s) and "\\" not in s and "(?" not in s
            and "|" not in s
        ]
        assert not offenders, (mod.__name__, offenders[:3])


async def test_wallet_user_card_model_is_what_the_store_returns(srepos, user_id):
    await srepos.wallet.upsert(UserCard(user_id=user_id, bank="Example Bank", card_name="Z"))
    assert isinstance((await srepos.wallet.list(user_id))[0], UserCard)
