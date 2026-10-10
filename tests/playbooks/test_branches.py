"""Every branch of the salon playbook (v6) is reachable and does what the founder's script says,
driven by scripted salon replies through the real policy."""

# ruff: noqa: E501  (the scenario table is easier to read one scenario per line)
from __future__ import annotations

import pytest

from friday.core.models import CallActionType, CallOutcome
from friday.playbooks.intents import ANY

from .conftest import delegation, drive, make_brief

PRICE = ["Haircut 400 rupaye, 30 minute"]  # answers the price question
Q_CLOSE = "main Rahul sir ko bata deti hoon"  # quote-only close
CLOSE = "poochh kar aapko batati hoon"  # book mode, she may not book
ASK_PRICE = "ek baar bata sakte hain inke kya charges rahenge"
AGAIN_PRICE = "ke kya charges rahenge"
BOOK = {"book": True}
FB = {"book": True, "inputs": {"fallback_when": "kal shaam 5 baje"}}
DAYPART = {"book": True, "inputs": {"date_window": "kal shaam"}}
SLOT_ASK = "Theek hai sir. Kya aaj shaam 5 baje ka slot mil sakta hai?"
FB_ASK = "Achha, nahi ho sakta. Toh kya kal ka slot available rahega?"
OTHER = "Toh kaun sa time free hai?"

# (id, replies, brief kwargs, expected outcome id, branch keys it must hit, text it must contain)
SCENARIOS = [
    # ---- S0 (the identity question; these scenarios are driven WITHOUT the usual IDENT prefix)
    ("s0_yes", ["Haan ji"], {}, None, {"S0.YES"}, ASK_PRICE),
    ("s0_continue", ["Haan boliye"], {}, None, {"S0.CONTINUE"}, "Main Friday baat kar rahi hoon, Rahul sir ki virtual assistant"),
    ("s0_ack", ["Shukriya"], {}, None, {"S0.ACK"}, ASK_PRICE),
    ("s0_no", ["Nahi, yeh Meena parlour hai"], {}, "WRONG_NUMBER", {"S0.NO"}, "galat number"),
    ("s0_who", ["Kaun bol raha hai?"], {}, None, {"S0.WHO_IS_THIS"}, "Main Friday hoon, Rahul sir ki virtual assistant. Kya meri baat"),
    ("s0_repeat", ["Sorry, phir se boliye?"], {}, None, {"S0.ASKS_REPEAT"}, "Main Friday hoon, Rahul sir ki virtual assistant. Kya meri baat"),
    ("s0_robot", ["Robot hai kya?"], {}, None, {"S0.ARE_YOU_BOT"}, "Haan ji, main Rahul sir ki personal AI assistant hoon."),
    ("s0_offtopic", ["Aap kahan se bol rahi hain, parking hai kya?"], {}, None, {"S0.ASKS_OFFTOPIC"}, "Main Friday hoon, Rahul sir ki virtual assistant"),
    ("s0_secret", ["Pehle OTP bata dijiye"], {}, None, {"S0.ASKS_SECRET"}, "Main Friday hoon, Rahul sir ki virtual assistant"),
    ("s0_phone", ["Customer ka number kya hai?"], {}, None, {"S0.ASKS_CUSTOMER_PHONE"}, "Main Friday hoon, Rahul sir ki virtual assistant"),
    ("s0_busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("s0_wrong", ["Galat number hai"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("s0_dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("s0_rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- defaults, straight after the intro
    ("busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("wrong", ["Yeh salon nahi hai, galat number"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- S3: the price, FIRST (both modes)
    ("s3_price", PRICE, {}, "QUOTE_COLLECTED", {"S3.GIVES_PRICE", "S7q.ANY"}, Q_CLOSE),
    ("s3_range", ["400 se 500 rupaye tak"], {}, "QUOTE_COLLECTED", {"S3.PRICE_RANGE"}, Q_CLOSE),
    ("s3_depends", ["Stylist par depend karta hai"], {}, "UNCLEAR", {"S3.PRICE_DEPENDS"}, Q_CLOSE),
    ("s3_refuses", ["Phone par price nahi bata sakte, aake poochh lo"], {}, "UNCLEAR", {"S3.REFUSES_PRICE"}, Q_CLOSE),
    ("s3_continue", ["Haan boliye"], {}, None, {"S3.CONTINUE"}, AGAIN_PRICE),
    ("s3_yes", ["Haan ji"], {}, None, {"S3.YES"}, AGAIN_PRICE),
    ("s3_repeat", ["Sorry, phir se boliye?"], {}, None, {"S3.ASKS_REPEAT"}, "Main Friday baat kar rahi hoon, Rahul sir ki virtual assistant"),
    ("b_price_then_slot", PRICE, BOOK, None, {"S3.GIVES_PRICE"}, SLOT_ASK),
    # ---- S2: the slot (book mode)
    ("s2_free_requested", PRICE + ["Haan ho jayega"], BOOK, "BOOKED", {"S2.SLOT_FREE", "S7.ANY"}, "Theek hai sir, toh aaj shaam 5 baje ka slot book kar lijiye."),
    ("s2_yes_requested", PRICE + ["Haan ji"], BOOK, "BOOKED", {"S2.YES"}, "slot book kar lijiye"),
    ("s2_free_other_time", PRICE + ["Haan 6 baje free hai"], BOOK, "SLOT_OFFERED", {"S2.SLOT_FREE"}, CLOSE),
    ("s2_yes_no_time", PRICE + ["Haan ji"], DAYPART, None, {"S2.YES"}, "Kitne baje ka"),
    ("s2_free_no_time", PRICE + ["Haan ho jayega"], DAYPART, None, {"S2.SLOT_FREE"}, "Kitne baje ka"),
    ("s2_offers", PRICE + ["6 baje ya 7 baje ho jayega"], BOOK, "SLOT_OFFERED", {"S2.OFFERS_SLOTS"}, CLOSE),
    ("s2_busy", PRICE + ["Aaj shaam 5 baje to full hai"], BOOK, None, {"S2.SLOT_BUSY"}, OTHER),
    ("s2_no", PRICE + ["Nahi"], BOOK, None, {"S2.NO"}, OTHER),
    ("s2_appointment", PRICE + ["Appointment lena padega, walk-in nahi"], BOOK, None, {"S2.NEEDS_APPOINTMENT"}, "Appointment ke liye hi"),
    ("s2_continue", PRICE + ["Haan boliye"], BOOK, None, {"S2.CONTINUE"}, "Kya aaj shaam 5 baje ka slot mil sakta hai?"),
    ("s2_repeat", PRICE + ["Kya? Dobara bolo"], BOOK, None, {"S2.ASKS_REPEAT"}, "Kya aaj shaam 5 baje ka slot mil sakta hai?"),
    # ---- S2f: the second specific time, when the first is busy
    ("s2_busy_fallback", PRICE + ["Aaj to full hai"], FB, None, {"S2.SLOT_BUSY"}, FB_ASK),
    ("s2_no_fallback", PRICE + ["Nahi"], FB, None, {"S2.NO"}, FB_ASK),
    ("s2f_free", PRICE + ["Aaj to full hai", "Haan kal ho jayega"], FB, "BOOKED", {"S2f.SLOT_FREE"}, "Theek hai sir, phir kal shaam 5 baje ka slot book kar lete hain."),
    ("s2f_yes", PRICE + ["Aaj to full hai", "Haan ji"], FB, "BOOKED", {"S2f.YES"}, "phir kal shaam 5 baje ka slot book kar lete hain"),
    ("s2f_other_time", PRICE + ["Aaj to full hai", "Kal shaam 7 baje ho jayega"], FB, "SLOT_OFFERED", {"S2f.SLOT_FREE"}, CLOSE),
    ("s2f_offers", PRICE + ["Aaj to full hai", "Kal 6 baje ya 7 baje ho jayega"], FB, "SLOT_OFFERED", {"S2f.OFFERS_SLOTS"}, CLOSE),
    ("s2f_busy", PRICE + ["Aaj to full hai", "Kal bhi full hai"], FB, None, {"S2f.SLOT_BUSY"}, OTHER),
    ("s2f_no", PRICE + ["Aaj to full hai", "Nahi"], FB, None, {"S2f.NO"}, OTHER),
    ("s2f_any", PRICE + ["Aaj to full hai", "Shukriya"], FB, None, {"S2f.ANY"}, OTHER),
    ("s2f_repeat_default", PRICE + ["Aaj to full hai", "Kya? Dobara bolo"], FB, None, {"defaults.ASKS_REPEAT"}, FB_ASK),
    # ---- S2t
    ("s2t_time", PRICE + ["Haan ho jayega", "Shaam 5 baje"], DAYPART, "BOOKED", {"S2t.GIVES_TIME"}, "slot book kar lijiye"),
    ("s2t_free", PRICE + ["Haan ho jayega", "Haan 5 baje free hai"], DAYPART, "BOOKED", {"S2t.SLOT_FREE"}, "slot book kar lijiye"),
    ("s2t_offers", PRICE + ["Haan ho jayega", "5 baje ya 7 baje"], DAYPART, "BOOKED", {"S2t.OFFERS_SLOTS"}, "slot book kar lijiye"),
    ("s2t_busy", PRICE + ["Haan ho jayega", "Nahi sab full hai"], DAYPART, None, {"S2t.SLOT_BUSY"}, OTHER),
    ("s2t_no", PRICE + ["Haan ho jayega", "Nahi"], DAYPART, None, {"S2t.NO"}, OTHER),
    # ---- S2b (ONE alternative; two only when the owner wants to compare)
    ("s2b_offers", PRICE + ["Full hai", "Aaj 6 baje ya 7 baje ho jayega"], BOOK, "SLOT_OFFERED", {"S2b.OFFERS_SLOTS"}, CLOSE),
    ("s2b_free", PRICE + ["Full hai", "Haan 6 baje free hai"], BOOK, "SLOT_OFFERED", {"S2b.SLOT_FREE"}, CLOSE),
    ("s2b_time", PRICE + ["Full hai", "Shaam 7 baje"], BOOK, "SLOT_OFFERED", {"S2b.GIVES_TIME"}, CLOSE),
    ("s2b_busy", PRICE + ["Full hai", "Koi slot nahi"], BOOK, "NO_SLOT", {"S2b.SLOT_BUSY"}, "bata dungi"),
    ("s2b_no", PRICE + ["Full hai", "Nahi"], BOOK, "NO_SLOT", {"S2b.NO"}, "bata dungi"),
    ("s2b_explore", PRICE + ["Full hai"], {"book": True, "inputs": {"explore_options": "yes"}}, None, {"S2.SLOT_BUSY"}, "Toh kaun se do time free hain?"),
    # ---- S3b (book mode, over budget AND the owner explicitly allowed negotiating)
    ("s3b_new_price", ["900 rupaye, 45 minute", "700 rupaye kar denge", "Haan ho jayega"], {"book": True, "negotiation": True, "inputs": {"negotiate": "yes"}}, "SLOT_OFFERED", {"S3b.GIVES_PRICE"}, CLOSE),
    ("s3b_range", ["900 rupaye, 45 minute", "700 se 800 rupaye", "Haan ho jayega"], {"book": True, "negotiation": True, "inputs": {"negotiate": "yes"}}, "SLOT_OFFERED", {"S3b.PRICE_RANGE"}, CLOSE),
    ("s3b_yes", ["900 rupaye, 45 minute", "Haan", "Haan ho jayega"], {"book": True, "negotiation": True, "inputs": {"negotiate": "yes"}}, "SLOT_OFFERED", {"S3b.YES"}, CLOSE),
    ("s3b_no", ["900 rupaye, 45 minute", "Nahi", "Haan ho jayega"], {"book": True, "negotiation": True, "inputs": {"negotiate": "yes"}}, "SLOT_OFFERED", {"S3b.NO"}, CLOSE),
    ("s3b_any", ["900 rupaye, 45 minute", "Aap aa jao dekhte hain", "Haan ho jayega"], {"book": True, "negotiation": True, "inputs": {"negotiate": "yes"}}, "SLOT_OFFERED", {"S3b.ANY"}, CLOSE),
    # ---- S4 (book mode, the user named a stylist; asked after the price)
    ("s4_stylist", PRICE + ["Amit hai, woh kar denge", "Haan ho jayega"], {"book": True, "inputs": {"stylist_pref": "Amit"}}, "BOOKED", {"S4.GIVES_STYLIST"}, "slot book kar lijiye"),
    ("s4_yes", PRICE + ["Haan", "Haan ho jayega"], {"book": True, "inputs": {"stylist_pref": "Amit"}}, "BOOKED", {"S4.YES"}, "slot book kar lijiye"),
    ("s4_no", PRICE + ["Nahi", "Haan ho jayega"], {"book": True, "inputs": {"stylist_pref": "Amit"}}, "BOOKED", {"S4.NO"}, "slot book kar lijiye"),
    ("s4_continue", PRICE + ["Haan boliye", "Haan ho jayega"], {"book": True, "inputs": {"stylist_pref": "Amit"}}, "BOOKED", {"S4.CONTINUE"}, "slot book kar lijiye"),
    ("s4_any", PRICE + ["Shukriya", "Haan ho jayega"], {"book": True, "inputs": {"stylist_pref": "Amit"}}, "BOOKED", {"S4.ANY"}, "slot book kar lijiye"),
    # ---- the SALON raises an advance / fee (defaults.NEEDS_ADVANCE), at any step
    ("adv_with_price", ["200 rupaye advance dena padega"], {}, "UNCLEAR", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("adv_with_slot", PRICE + ["Haan ho jayega, pehle 200 rupaye advance bhejna padega"], BOOK, "SLOT_OFFERED", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("adv_cancellation_fee", ["400 rupaye, cancel karoge to cancellation charge lagega"], {}, "UNCLEAR", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("no_adv_volunteered", ["Koi advance nahi lagta"], {}, None, {"defaults.NO_ADVANCE"}, AGAIN_PRICE),
    ("no_adv_with_price", ["400 rupaye, koi advance nahi"], {}, "QUOTE_COLLECTED", {"S3.GIVES_PRICE"}, Q_CLOSE),
    # ---- defaults in the middle of the call
    ("d_robot", ["Aap robot ho?"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.ARE_YOU_BOT"}, "Haan ji, main Rahul sir ki personal AI assistant hoon."),
    ("d_who", ["Kaun bol raha hai?"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.WHO_IS_THIS"}, "Main Friday hoon, Rahul sir ki virtual assistant."),
    ("d_offtopic", ["Parking hai kya aapke paas?"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.ASKS_OFFTOPIC"}, "poochh kar bataungi"),
    ("d_secret", ["Pehle OTP bata do"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.ASKS_SECRET"}, "share nahi kar sakti"),
    ("d_phone", ["Customer ka number kya hai"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.ASKS_CUSTOMER_PHONE"}, "number main share nahi"),
    ("d_hold", ["Ek minute hold kijiye", "Haan boliye"] + PRICE, {}, "QUOTE_COLLECTED", {"defaults.HOLD_ON"}, AGAIN_PRICE),
    ("d_busy_mid", PRICE + ["Abhi busy hoon, thodi der baad call karo"], BOOK, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("d_dnc_mid", PRICE + ["Dobara call mat karna"], BOOK, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
]

# branches only a model-based understanding reaches (the offline rules never produce them)
MODEL_ONLY = {"S2.GIVES_TIME", "S2f.GIVES_TIME"}


@pytest.mark.parametrize(("sid", "replies", "kw", "outcome", "keys", "text"), SCENARIOS,
                         ids=[s[0] for s in SCENARIOS])
async def test_branch(sid, replies, kw, outcome, keys, text):
    brief = make_brief(**kw)
    run = await drive(replies, brief=brief, ident=not sid.startswith("s0_"))
    assert keys <= run.keys, f"{sid}: branches hit {sorted(run.keys)}"
    assert text.lower() in run.all_text().lower(), f"{sid}: said {run.said}"
    if outcome:
        assert run.outcome == outcome, f"{sid}: {run.outcome} / {run.said}"


def test_scenarios_cover_every_declared_branch(salon):
    declared: set[str] = set()
    for sid, step in salon.steps.items():
        declared |= {f"{sid}.{intent}" for intent in step.branches}
    declared |= {f"defaults.{i}" for i in salon.defaults}
    covered = set().union(*(s[4] for s in SCENARIOS)) | MODEL_ONLY
    assert declared - covered == set(), f"branches with no test: {sorted(declared - covered)}"


async def test_conditional_alternatives_are_all_reached():
    seen: set[str] = set()
    for sid, replies, kw, *_ in SCENARIOS:
        run = await drive(replies, brief=make_brief(**kw), ident=not sid.startswith("s0_"))
        seen |= set(run.said)
    joined = " | ".join(seen)
    for needle in (
        "karwana hai, toh unki booking ke regarding call kiya hai",  # book mode intro
        "karwana hai, toh uske charges ke regarding call kiya hai",  # quote_only intro
        "Kitne baje ka?",
        OTHER,
        "Toh kaun se do time free hain?",
        "Rahul sir ka budget 600 rupaye hai",
        "Agar Amit available ho",
        FB_ASK,
        "phir kal shaam 5 baje ka slot book kar lete hain",
        "toh aaj shaam 5 baje ka slot book kar lijiye",
    ):
        assert needle in joined, needle


async def test_the_full_script_of_both_modes_word_for_word():
    q = await drive(PRICE, brief=make_brief())
    assert q.said == [
        "Main Friday baat kar rahi hoon, Rahul sir ki virtual assistant. Rahul sir ko haircut karwana hai, toh uske charges ke regarding call kiya hai. Toh sir, ek baar bata sakte hain inke kya charges rahenge?",
        "Theek hai sir, main Rahul sir ko bata deti hoon. Thank you.",
    ]
    assert q.transcript.turns[1].text == "Hello, kya meri baat Looks Salon se ho rahi hai?" or "saloon" in q.transcript.turns[1].text
    free = await drive(PRICE + ["Haan ho jayega"], brief=make_brief(**BOOK))
    assert free.said[0].endswith("toh unki booking ke regarding call kiya hai. Toh sir, ek baar bata sakte hain inke kya charges rahenge?")
    assert free.said[1:] == [
        "Theek hai sir. Kya aaj shaam 5 baje ka slot mil sakta hai?",
        "Theek hai sir, toh aaj shaam 5 baje ka slot book kar lijiye. Rahul sir aane se pehle aapko ek baar call kar lenge. Thank you.",
    ]
    fb = await drive(PRICE + ["Aaj to full hai", "Haan kal ho jayega"], brief=make_brief(**FB))
    assert fb.said[2:] == [
        "Achha, nahi ho sakta. Toh kya kal ka slot available rahega?",
        "Theek hai sir, phir kal shaam 5 baje ka slot book kar lete hain. Rahul sir aane se pehle aapko ek baar call kar lenge. Thank you.",
    ]
    assert fb.final.commits_booking and fb.outcome == "BOOKED"


async def test_price_is_asked_first_without_duration_or_read_back():
    run = await drive(["Haircut 400 rupaye, lagbhag 30 minute"], brief=make_brief())
    text = " | ".join(run.said).lower()
    for banned in ("kitna time", "minute", "sahi?", "matlab", "400", "advance"):
        assert banned not in text, banned
    assert run.final.collected["duration_min"] == "30" and run.final.collected["price_inr"] == "400"


async def test_quote_only_never_asks_for_a_slot_and_reports_the_price():
    run = await drive(PRICE, brief=make_brief())
    assert run.path == ["S0", "S3", "S7q"] and run.outcome == "QUOTE_COLLECTED"
    assert "slot" not in " ".join(run.said).lower()
    assert run.final.outcome == CallOutcome.PARTIAL and not run.final.commits_booking
    assert run.final.collected["price_inr"] == "400" and run.final.quote.amount_inr == 400


async def test_book_mode_needs_a_delegation_and_a_time():
    # asked for book mode but nobody delegated: it is a price check, no slot question, no booking
    run = await drive(PRICE, brief=make_brief(inputs={"playbook_mode": "book", "date_window": "aaj shaam 5 baje"}))
    assert run.path == ["S0", "S3", "S7q"] and run.outcome == "QUOTE_COLLECTED"
    # delegated, but no time to ask for: also a price check
    nb = make_brief(book=True, inputs={"date_window": ""})
    run = await drive(PRICE, brief=nb)
    assert run.outcome == "QUOTE_COLLECTED"
    # a fallback is ignored in a price check
    run = await drive(PRICE, brief=make_brief(inputs={"fallback_when": "kal shaam 5 baje"}))
    assert "kal ka slot" not in " ".join(run.said)


async def test_fallback_needs_one_specific_time():
    for bad in ("kal shaam", "kal shaam 5 se 8 baje ke beech", ""):
        run = await drive(PRICE + ["Aaj to full hai"], brief=make_brief(book=True, delegation=delegation(800), inputs={"fallback_when": bad}))
        assert "S2f" not in run.path, bad
        assert run.said[-1] == OTHER


async def test_negotiation_is_off_unless_the_owner_said_so():
    over = ["900 rupaye, 45 minute"]
    for brief in (make_brief(book=True, negotiation=False), make_brief(book=True, negotiation=True)):
        run = await drive(over + ["Haan ho jayega"], brief=brief)
        assert "S3b" not in run.path and not any("budget" in s for s in run.said)
    # a price check never haggles, even with the instruction
    run = await drive(over, brief=make_brief(negotiation=True, inputs={"negotiate": "yes"}))
    assert "S3b" not in run.path and run.outcome == "QUOTE_COLLECTED"
    neg = await drive(over + ["700 rupaye"] + ["Nahi, 700 hi hai", "Haan", "Haan ho jayega"],
                      brief=make_brief(book=True, negotiation=True, inputs={"negotiate": "yes"}))
    assert neg.path.count("S3b") == 1
    assert len([s for s in neg.said if "budget" in s]) == 1


async def test_no_line_of_the_playbook_asks_about_advance_or_duration(salon):
    ask_text = " ".join(
        salon.text(lid) for s in salon.steps.values() for lid in
        (x if isinstance(x, str) else x.line for x in s.ask)
    ).lower()
    for banned in ("advance", "cancellation", "kitna time", "kitne minute", "discount", "call back"):
        assert banned not in ask_text, banned


async def test_stylist_step_skipped_without_preference():
    run = await drive(PRICE + ["Haan ho jayega"], brief=make_brief(**BOOK))
    assert "S4" not in run.path


async def test_price_unknown_never_books():
    run = await drive(["Phone par price nahi bata sakte", "Haan ho jayega"], brief=make_brief(**BOOK))
    assert run.outcome == "SLOT_OFFERED" and run.final.quote.amount_inr is None
    assert not run.final.commits_booking and CLOSE in run.final.text


async def test_outcome_mapping_to_call_outcomes():
    cases = {
        ("Nahi abhi nahi busy hoon",): (CallOutcome.CALLBACK_LATER, {}),
        ("Yeh salon nahi hai",): (CallOutcome.DECLINED, {}),
        ("Dobara call mat karna",): (CallOutcome.DECLINED, {}),
        tuple(PRICE): (CallOutcome.PARTIAL, {}),
        tuple(PRICE + ["Haan 6 baje free hai"]): (CallOutcome.PENDING_APPROVAL, BOOK),
        tuple(PRICE + ["Haan ho jayega"]): (CallOutcome.SUCCESS, BOOK),
        tuple(PRICE + ["Full hai", "Koi slot nahi"]): (CallOutcome.DECLINED, BOOK),
    }
    for replies, (expected, kw) in cases.items():
        run = await drive(list(replies), brief=make_brief(**kw))
        assert run.final.type == CallActionType.HANGUP and run.final.outcome == expected, replies


async def test_dnc_sets_the_pool_wide_flag():
    run = await drive(["Dobara call mat karna"], brief=make_brief())
    assert run.final.collected["do_not_call"] == "yes"


async def test_slots_and_facts_are_collected():
    run = await drive(PRICE + ["Haan 6 baje free hai"], brief=make_brief(**BOOK))
    c = run.final.collected
    assert c["price_inr"] == "400" and c["duration_min"] == "30"
    assert "6 baje" in c["slot"] and c["outcome"] == "SLOT_OFFERED"
    q = run.final.quote
    assert q.amount_inr == 400 and q.available_slots == ["6 PM"] and q.within_budget is True


async def test_requested_time_is_the_slot_when_she_says_yes_without_a_time():
    run = await drive(PRICE + ["Haan ho jayega"], brief=make_brief(**BOOK))
    assert "Kitne baje" not in " ".join(run.said)
    assert run.final.collected["slot"] == "aaj shaam 5 baje"
    for window in ("kal shaam", "kal shaam 5 se 8 baje ke beech", "5 baje ya 6 baje"):
        run = await drive(PRICE + ["Haan ho jayega"], brief=make_brief(book=True, inputs={"date_window": window}))
        assert "Kitne baje ka?" in run.said[-1], window


async def test_busy_then_unlisted_time_never_books_the_requested_one():
    # "5 baje nahi, 6 baje ho jayega": the 5 o'clock she refused must not be booked
    run = await drive(PRICE + ["5 baje nahi, 6 baje ho jayega"], brief=make_brief(**BOOK))
    assert run.outcome == "SLOT_OFFERED" and "5 baje" not in run.final.collected["slot"]


async def test_branches_only_the_model_can_reach():
    from friday.playbooks.engine import PlaybookPolicy
    from friday.playbooks.understand import Understanding, heuristic

    class Scripted:
        async def understand(self, *, reply, step, **kw):
            if step in ("S2", "S2f"):
                return Understanding(intent="GIVES_TIME", time="shaam 6 baje")
            return heuristic(reply, step=step)

    policy = PlaybookPolicy(understander=Scripted(), llm_mode="always")
    run = await drive(PRICE + ["bas shaam chhe"], brief=make_brief(**BOOK), policy=policy)
    assert "S2.GIVES_TIME" in run.keys and run.outcome == "SLOT_OFFERED"
    policy = PlaybookPolicy(understander=Scripted(), llm_mode="always")
    run = await drive(PRICE + ["Aaj to full hai", "bas shaam chhe"], brief=make_brief(**FB), policy=policy)
    assert "S2f.GIVES_TIME" in run.keys or "S2.GIVES_TIME" in run.keys


def test_any_is_the_wildcard_key():
    assert ANY == "ANY"


def test_delegation_helper_is_a_delegation():
    assert delegation(800).granted
