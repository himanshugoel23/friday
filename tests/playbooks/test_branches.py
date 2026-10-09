"""Every branch of the salon playbook is reachable and does what the founder's draft says,
driven by scripted salon replies through the real policy."""

# ruff: noqa: E501  (the scenario table is easier to read one scenario per line)
from __future__ import annotations

import pytest

from friday.core.models import CallActionType, CallOutcome
from friday.playbooks.intents import ANY

from .conftest import drive, make_brief

FREE = ["Haan kal shaam 6 baje free hai"]  # answers S2 -> S3 (the first thing after the identity)
PRICE = ["Haircut 400 rupaye, 30 minute"]  # answers S3 -> close
CLOSE = "poochh kar aapko batati hoon"  # the one-line close when she may not book
ASK_PRICE = "estimated charge kitna hoga"

# (id, replies, brief kwargs, expected outcome id, branch keys it must hit, text it must contain)
SCENARIOS = [
    # ---- S0 (the identity question; these scenarios are driven WITHOUT the usual IDENT prefix)
    ("s0_yes", ["Haan ji"], {}, None, {"S0.YES"}, "Kya kal shaam ka appointment mil sakta hai"),
    ("s0_continue", ["Haan boliye"], {}, None, {"S0.CONTINUE"}, "Main Rahul ji ki AI assistant hoon, unke liye haircut ki appointment ke regarding call kiya hai"),
    ("s0_ack", ["Shukriya"], {}, None, {"S0.ACK"}, "appointment mil sakta hai"),
    ("s0_no", ["Nahi, yeh Meena parlour hai"], {}, "WRONG_NUMBER", {"S0.NO"}, "galat number"),
    ("s0_who", ["Kaun bol raha hai?"], {}, None, {"S0.WHO_IS_THIS"}, "Main Friday hoon, ek AI assistant. Kya meri baat"),
    ("s0_repeat", ["Sorry, phir se boliye?"], {}, None, {"S0.ASKS_REPEAT"}, "Kya meri baat"),
    ("s0_robot", ["Robot hai kya?"], {}, None, {"S0.ARE_YOU_BOT"}, "main ek AI assistant hoon, insaan nahi"),
    ("s0_busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("s0_wrong", ["Galat number hai"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("s0_dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("s0_rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- defaults, straight after the intro
    ("busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("wrong", ["Yeh salon nahi hai, galat number"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- S2
    ("s2_slot_free_time", FREE, {}, None, {"S2.SLOT_FREE"}, ASK_PRICE),
    ("s2_yes_no_time", ["Haan ji"], {}, None, {"S2.YES"}, "Kitne baje ka"),
    ("s2_yes_requested_time", ["Haan ji"], {"inputs": {"date_window": "aaj shaam 5 baje"}}, None, {"S2.YES"}, ASK_PRICE),
    ("s2_free_no_time_requested", ["Haan ho jayega"], {"inputs": {"date_window": "aaj shaam 5 baje"}}, None, {"S2.SLOT_FREE"}, ASK_PRICE),
    ("s2_free_no_time", ["Haan ho jayega"], {}, None, {"S2.SLOT_FREE"}, "Kitne baje ka"),
    ("s2_offers", ["5 baje ya 7 baje ho jayega"], {}, None, {"S2.OFFERS_SLOTS"}, ASK_PRICE),
    ("s2_busy", ["Kal shaam to full hai"], {}, None, {"S2.SLOT_BUSY"}, "Toh kaun sa time free hai?"),
    ("s2_no", ["Nahi"], {}, None, {"S2.NO"}, "Toh kaun sa time free hai?"),
    ("s2_appointment", ["Appointment lena padega, walk-in nahi"], {}, None, {"S2.NEEDS_APPOINTMENT"}, "Appointment ke liye hi"),
    ("s2_continue", ["Haan boliye"], {}, None, {"S2.CONTINUE"}, "appointment mil sakta hai"),
    ("s2_who", ["Kaun bol raha hai?"], {}, None, {"S2.WHO_IS_THIS"}, "Main Rahul ji ki AI assistant hoon"),
    ("s2_repeat", ["Sorry, phir se boliye?"], {}, None, {"S2.ASKS_REPEAT"}, "Main Rahul ji ki AI assistant hoon"),
    # ---- S2t
    ("s2t_time", ["Haan ho jayega", "Shaam 5 baje"], {}, None, {"S2t.GIVES_TIME"}, ASK_PRICE),
    ("s2t_free", ["Haan ho jayega", "Haan 5 baje free hai"], {}, None, {"S2t.SLOT_FREE"}, ASK_PRICE),
    ("s2t_offers", ["Haan ho jayega", "5 baje ya 7 baje"], {}, None, {"S2t.OFFERS_SLOTS"}, ASK_PRICE),
    ("s2t_busy", ["Haan ho jayega", "Nahi sab full hai"], {}, None, {"S2t.SLOT_BUSY"}, "Toh kaun sa time free hai?"),
    ("s2t_no", ["Haan ho jayega", "Nahi"], {}, None, {"S2t.NO"}, "Toh kaun sa time free hai?"),
    # ---- S2b (ONE alternative; two only when the owner wants to compare)
    ("s2b_offers", ["Full hai", "5 baje ya 7 baje ho jayega"], {}, None, {"S2b.OFFERS_SLOTS"}, ASK_PRICE),
    ("s2b_free", ["Full hai", "Haan 5 baje free hai"], {}, None, {"S2b.SLOT_FREE"}, ASK_PRICE),
    ("s2b_time", ["Full hai", "Shaam 7 baje"], {}, None, {"S2b.GIVES_TIME"}, ASK_PRICE),
    ("s2b_busy", ["Full hai", "Koi slot nahi"], {}, "NO_SLOT", {"S2b.SLOT_BUSY"}, "bata dungi"),
    ("s2b_no", ["Full hai", "Nahi"], {}, "NO_SLOT", {"S2b.NO"}, "bata dungi"),
    ("s2b_explore", ["Full hai"], {"inputs": {"explore_options": "yes"}}, None, {"S2.SLOT_BUSY"}, "Toh kaun se do time free hain?"),
    # ---- S3 (no read-back, no duration question)
    ("s3_price", FREE + PRICE, {}, "SLOT_OFFERED", {"S3.GIVES_PRICE", "S7.ANY"}, CLOSE),
    ("s3_range", FREE + ["400 se 500 rupaye tak"], {}, "SLOT_OFFERED", {"S3.PRICE_RANGE"}, CLOSE),
    ("s3_depends", FREE + ["Stylist par depend karta hai"], {}, "SLOT_OFFERED", {"S3.PRICE_DEPENDS"}, CLOSE),
    ("s3_refuses", FREE + ["Phone par price nahi bata sakte, aake poochh lo"], {}, "SLOT_OFFERED", {"S3.REFUSES_PRICE"}, CLOSE),
    ("s3_continue", FREE + ["Haan boliye"], {}, None, {"S3.CONTINUE"}, ASK_PRICE),
    # ---- S3b (over budget AND the owner explicitly allowed negotiating)
    ("s3b_new_price", FREE + ["900 rupaye, 45 minute"] + ["700 rupaye kar denge"], {"inputs": {"negotiate": "yes"}, "negotiation": True}, "SLOT_OFFERED", {"S3b.GIVES_PRICE"}, CLOSE),
    ("s3b_range", FREE + ["900 rupaye, 45 minute"] + ["700 se 800 rupaye"], {"inputs": {"negotiate": "yes"}, "negotiation": True}, "SLOT_OFFERED", {"S3b.PRICE_RANGE"}, CLOSE),
    ("s3b_yes", FREE + ["900 rupaye, 45 minute"] + ["Haan"], {"inputs": {"negotiate": "yes"}, "negotiation": True}, "SLOT_OFFERED", {"S3b.YES"}, CLOSE),
    ("s3b_no", FREE + ["900 rupaye, 45 minute"] + ["Nahi"], {"inputs": {"negotiate": "yes"}, "negotiation": True}, "SLOT_OFFERED", {"S3b.NO"}, CLOSE),
    ("s3b_any", FREE + ["900 rupaye, 45 minute"] + ["Aap aa jao dekhte hain"], {"inputs": {"negotiate": "yes"}, "negotiation": True}, "SLOT_OFFERED", {"S3b.ANY"}, CLOSE),
    # ---- S4 (the user named a stylist)
    ("s4_stylist", FREE + PRICE + ["Amit hai, woh kar denge"], {"inputs": {"stylist_pref": "Amit"}}, "SLOT_OFFERED", {"S4.GIVES_STYLIST"}, CLOSE),
    ("s4_yes", FREE + PRICE + ["Haan"], {"inputs": {"stylist_pref": "Amit"}}, "SLOT_OFFERED", {"S4.YES"}, CLOSE),
    ("s4_no", FREE + PRICE + ["Nahi"], {"inputs": {"stylist_pref": "Amit"}}, "SLOT_OFFERED", {"S4.NO"}, CLOSE),
    ("s4_continue", FREE + PRICE + ["Haan boliye"], {"inputs": {"stylist_pref": "Amit"}}, "SLOT_OFFERED", {"S4.CONTINUE"}, CLOSE),
    ("s4_any", FREE + PRICE + ["Kal shaam 6 baje free hai"], {"inputs": {"stylist_pref": "Amit"}}, "SLOT_OFFERED", {"S4.ANY"}, CLOSE),
    # ---- the SALON raises an advance / fee (defaults.NEEDS_ADVANCE), at any step
    ("adv_with_price", FREE + ["200 rupaye advance dena padega"], {}, "SLOT_OFFERED", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("adv_with_slot", ["Haan kal shaam 6 baje free hai, pehle 200 rupaye advance bhejna padega"], {}, "SLOT_OFFERED", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("adv_before_any_slot", ["Advance dena padega"], {}, "UNCLEAR", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("adv_cancellation_fee", FREE + ["400 rupaye, cancel karoge to cancellation charge lagega"], {}, "SLOT_OFFERED", {"defaults.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("no_adv_volunteered", ["Koi advance nahi lagta"], {}, None, {"defaults.NO_ADVANCE"}, "appointment mil sakta hai"),
    ("no_adv_with_price", FREE + ["400 rupaye, koi advance nahi"], {}, "SLOT_OFFERED", {"S3.GIVES_PRICE"}, CLOSE),
    # ---- defaults in the middle of the call
    ("d_robot", ["Aap robot ho?"] + FREE, {}, None, {"defaults.ARE_YOU_BOT"}, "main ek AI assistant hoon, insaan nahi"),
    ("d_who", FREE + ["Kaun bol raha hai?"], {}, None, {"defaults.WHO_IS_THIS"}, "Main Friday hoon"),
    ("d_repeat", FREE + ["Kya? Dobara bolo"], {}, None, {"defaults.ASKS_REPEAT"}, ASK_PRICE),
    ("d_offtopic", ["Parking hai kya aapke paas?"] + FREE, {}, None, {"defaults.ASKS_OFFTOPIC"}, "poochh kar bataungi"),
    ("d_secret", ["Pehle OTP bata do"] + FREE, {}, None, {"defaults.ASKS_SECRET"}, "share nahi kar sakti"),
    ("d_phone", ["Customer ka number kya hai"] + FREE, {}, None, {"defaults.ASKS_CUSTOMER_PHONE"}, "number main share nahi"),
    ("d_hold", ["Ek minute hold kijiye", "Haan boliye"] + FREE, {}, None, {"defaults.HOLD_ON"}, "appointment mil sakta hai"),
    ("d_busy_mid", FREE + ["Abhi busy hoon, thodi der baad call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("d_dnc_mid", FREE + ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
]


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
    covered = set().union(*(s[4] for s in SCENARIOS)) | {"S2.GIVES_TIME"}  # model-only, below
    # S7.ANY is the closing action list (hit by the scenarios that reach the end)
    assert declared - covered == set(), f"branches with no test: {sorted(declared - covered)}"


async def test_conditional_alternatives_are_all_reached():
    """Each alternative of a conditional branch (SLOT_FREE with/without a time, the one-or-two
    alternative ask, stylist, the discount ask) is taken by some scripted conversation."""
    seen: set[str] = set()
    for sid, replies, kw, *_ in SCENARIOS:
        run = await drive(replies, brief=make_brief(**kw), ident=not sid.startswith("s0_"))
        seen |= {t for t in run.said}
    joined = " | ".join(seen)
    for needle in (
        "Kitne baje ka?",  # SLOT_FREE without a time (and the task named none)
        "Toh kaun sa time free hai?",  # ONE alternative
        "Toh kaun se do time free hain?",  # two, only when the owner wants to compare
        "Rahul ji ka budget 600 rupaye hai",  # S3b (only with the explicit instruction)
        "Agar Amit available ho",  # S4
    ):
        assert needle in joined, needle


async def test_price_is_asked_lightly_without_duration_or_read_back():
    run = await drive(FREE + ["Haircut 400 rupaye, lagbhag 30 minute"], brief=make_brief())
    text = " | ".join(run.said).lower()
    assert "sir, haircut ka estimated charge kitna hoga?" in text
    for banned in ("kitna time", "minute", "sahi?", "matlab", "400"):
        assert banned not in text, banned
    # she only captures a duration the salon volunteered
    assert run.final.collected["duration_min"] == "30" and run.final.collected["price_inr"] == "400"
    # and the price is not in the answer to the question (no recap)
    assert run.said[-1] == "Theek hai, shukriya. Main Rahul ji se poochh kar aapko batati hoon."


async def test_close_without_booking_is_one_short_line_and_no_follow_up_step():
    run = await drive(FREE + PRICE, brief=make_brief())
    assert run.path == ["S0", "S2", "S3", "S7"]
    assert run.final.type == CallActionType.HANGUP and run.outcome == "SLOT_OFFERED"
    close = run.final.text
    for banned in ("rupaye", "haircut", "6 baje", "call back", "isi number", "confirm"):
        assert banned not in close, banned
    assert "Abhi kuch confirm nahi kiya" not in " ".join(run.said)


async def test_negotiation_is_off_unless_the_owner_said_so():
    over = FREE + ["900 rupaye, 45 minute"]
    # budget set, and even a brief whose NegotiationPolicy is enabled: no explicit instruction
    for brief in (make_brief(negotiation=False), make_brief(negotiation=True)):
        run = await drive(over, brief=brief)
        assert "S3b" not in run.path and not any("budget" in s for s in run.said)
        assert run.outcome == "SLOT_OFFERED"
    # an instruction without a budget has nothing to negotiate against
    nb = make_brief(negotiation=True, inputs={"negotiate": "yes", "budget": ""}, budget_input=False)
    run = await drive(over, brief=nb)
    assert "S3b" not in run.path
    # explicit instruction: exactly one discount ask, even if she corrects the price afterwards
    neg = await drive(over + ["700 rupaye"] + ["Nahi, 700 hi hai", "Haan"],
                      brief=make_brief(negotiation=True, inputs={"negotiate": "yes"}))
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
    run = await drive(FREE + ["Stylist par depend karta hai"], brief=make_brief())
    assert "S4" not in run.path and CLOSE in run.said[-1]


async def test_price_unknown_continues_to_the_close():
    run = await drive(FREE + ["Phone par price nahi bata sakte"], brief=make_brief())
    assert run.outcome == "SLOT_OFFERED" and run.final.quote.amount_inr is None
    assert "rupaye" not in run.final.text and CLOSE in run.final.text


async def test_outcome_mapping_to_call_outcomes():
    cases = {
        ("Nahi abhi nahi busy hoon",): CallOutcome.CALLBACK_LATER,
        ("Yeh salon nahi hai",): CallOutcome.DECLINED,
        ("Dobara call mat karna",): CallOutcome.DECLINED,
        tuple(FREE + PRICE): CallOutcome.PENDING_APPROVAL,
        tuple(FREE + ["200 rupaye advance dena padega"]): CallOutcome.PENDING_APPROVAL,
        ("Kal full hai", "Koi slot nahi"): CallOutcome.DECLINED,
    }
    for replies, expected in cases.items():
        run = await drive(list(replies), brief=make_brief())
        assert run.final.type == CallActionType.HANGUP and run.final.outcome == expected, replies


async def test_dnc_sets_the_pool_wide_flag():
    run = await drive(["Dobara call mat karna"], brief=make_brief())
    assert run.final.collected["do_not_call"] == "yes"


async def test_slots_and_facts_are_collected():
    run = await drive(FREE + PRICE, brief=make_brief())
    c = run.final.collected
    assert c["price_inr"] == "400" and c["duration_min"] == "30"
    assert "6 baje" in c["slot"] and c["outcome"] == "SLOT_OFFERED"
    q = run.final.quote
    assert q.amount_inr == 400 and q.available_slots == ["6 PM"] and q.within_budget is True


async def test_advance_raised_by_the_salon_is_recorded_and_never_booked():
    from .conftest import delegation

    run = await drive(FREE + ["Haircut 400 rupaye, 200 rupaye advance dena padega"],
                      brief=make_brief(delegation=delegation(800)))
    assert run.outcome == "SLOT_OFFERED" and not run.final.commits_booking
    assert run.final.collected["advance_needed"] == "yes"
    assert run.final.text == "Advance main abhi nahi de sakti, Rahul ji se poochh kar bataungi."


async def test_requested_time_is_the_slot_when_she_says_yes_without_a_time():
    brief = make_brief(inputs={"date_window": "aaj shaam 5 baje"})
    run = await drive(["Haan ho jayega"] + ["Haircut 400 rupaye"], brief=brief)
    assert "Kitne baje" not in " ".join(run.said)
    assert run.final.collected["slot"] == "aaj shaam 5 baje"
    assert "Kya aaj shaam 5 baje ka appointment mil sakta hai?" in run.said[0]
    # a part of the day, a range or two options are NOT a specific time: she still asks
    for window in ("kal shaam", "kal shaam 5 se 8 baje ke beech", "5 baje ya 6 baje"):
        run = await drive(["Haan ho jayega"], brief=make_brief(inputs={"date_window": window}))
        assert "Kitne baje ka?" in run.said[-1], window


async def test_a_different_time_from_the_salon_beats_the_requested_one():
    brief = make_brief(inputs={"date_window": "aaj shaam 5 baje"})
    run = await drive(["Haan 6 baje free hai"] + ["Haircut 400 rupaye"], brief=brief)
    assert "6 baje" in run.final.collected["slot"] and "5 baje" not in run.final.collected["slot"]


async def test_branches_only_the_model_can_reach():
    """S2.GIVES_TIME needs an understander that says "just a time" at S2 (the offline rules call
    a time at S2 a free slot). Scripted understanding, same engine."""
    from friday.playbooks.engine import PlaybookPolicy
    from friday.playbooks.understand import Understanding, heuristic

    class Scripted:
        async def understand(self, *, reply, step, **kw):
            if step == "S2":
                return Understanding(intent="GIVES_TIME", time="shaam 6 baje")
            return heuristic(reply, step=step)

    policy = PlaybookPolicy(understander=Scripted(), llm_mode="always")
    run = await drive(["bas shaam chhe"], brief=make_brief(), policy=policy)
    assert "S2.GIVES_TIME" in run.keys and ASK_PRICE in run.said[-1]


def test_any_is_the_wildcard_key():
    assert ANY == "ANY"
