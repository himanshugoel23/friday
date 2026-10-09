"""Every branch of the salon playbook is reachable and does what the founder's draft says,
driven by scripted salon replies through the real policy."""

# ruff: noqa: E501  (the scenario table is easier to read one scenario per line)
from __future__ import annotations

import pytest

from friday.core.models import CallActionType, CallOutcome
from friday.playbooks.intents import ANY

from .conftest import drive, make_brief

OPEN = ["Haan boliye"]  # answers S1 -> S2
FREE = ["Haan kal shaam 6 baje free hai"]  # answers S2 -> S3
PRICE = ["Haircut 400 rupaye, 30 minute"]  # answers S3 -> S3r
SAHI = ["Haan sahi"]  # answers S3r
NOADV = ["Koi advance nahi"]  # answers S5
OK = ["Theek hai"]  # answers S6

# (id, replies, brief kwargs, expected outcome id, branch keys it must hit, text it must contain)
SCENARIOS = [
    # ---- S0 (the identity question; these scenarios are driven WITHOUT the usual IDENT prefix)
    ("s0_yes", ["Haan ji"], {}, None, {"S0.YES"}, "do minute baat ho sakti hai"),
    ("s0_continue", ["Haan boliye"], {}, None, {"S0.CONTINUE"}, "Main Rahul ji ki assistant hoon"),
    ("s0_ack", ["Shukriya"], {}, None, {"S0.ACK"}, "do minute baat ho sakti hai"),
    ("s0_no", ["Nahi, yeh Meena parlour hai"], {}, "WRONG_NUMBER", {"S0.NO"}, "galat number"),
    ("s0_who", ["Kaun bol raha hai?"], {}, None, {"S0.WHO_IS_THIS"}, "Main Friday hoon, ek AI assistant. Kya meri baat"),
    ("s0_repeat", ["Sorry, phir se boliye?"], {}, None, {"S0.ASKS_REPEAT"}, "Kya meri baat"),
    ("s0_robot", ["Robot hai kya?"], {}, None, {"S0.ARE_YOU_BOT"}, "main AI hoon, insaan nahi"),
    ("s0_busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("s0_wrong", ["Galat number hai"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("s0_dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("s0_rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- S1
    ("s1_yes", ["Haan"], {}, None, {"S1.YES"}, "Slot milega"),
    ("s1_continue", ["Haan boliye"], {}, None, {"S1.CONTINUE"}, "Slot milega"),
    ("s1_ack", ["Shukriya"], {}, None, {"S1.ACK"}, "Slot milega"),
    ("s1_no", ["Nahi abhi nahi"], {}, "CALL_BACK_LATER", {"S1.NO"}, "baad mein call"),
    ("s1_who", ["Kaun bol raha hai?"], {}, None, {"S1.WHO_IS_THIS"}, "Do minute milenge"),
    ("s1_repeat", ["Sorry, phir se boliye?"], {}, None, {"S1.ASKS_REPEAT"}, "Do minute milenge"),
    ("s1_robot", ["Robot hai kya?"], {}, None, {"S1.ARE_YOU_BOT"}, "main AI hoon, insaan nahi"),
    # ---- defaults, from S1
    ("busy", ["Abhi busy hoon, baad mein call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("wrong", ["Yeh salon nahi hai, galat number"], {}, "WRONG_NUMBER", {"defaults.WRONG_NUMBER"}, "galat number"),
    ("dnc", ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
    ("rude", ["Faltu tang mat karo"], {}, "REFUSED", {"defaults.RUDE"}, "pareshan karne"),
    # ---- S2
    ("s2_slot_free_time", OPEN + FREE, {}, None, {"S2.SLOT_FREE"}, "kitna lagega"),
    ("s2_yes_no_time", OPEN + ["Haan ji"], {}, None, {"S2.YES"}, "Kitne baje ka"),
    ("s2_offers", OPEN + ["5 baje ya 7 baje ho jayega"], {}, None, {"S2.OFFERS_SLOTS"}, "kitna lagega"),
    ("s2_busy", OPEN + ["Kal shaam to full hai"], {}, None, {"S2.SLOT_BUSY"}, "Kaun sa samay free"),
    ("s2_no", OPEN + ["Nahi"], {}, None, {"S2.NO"}, "Kaun sa samay free"),
    ("s2_appointment", OPEN + ["Appointment lena padega, walk-in nahi"], {}, None, {"S2.NEEDS_APPOINTMENT"}, "Appointment ke liye hi"),
    ("s2_continue", OPEN + ["Haan boliye"], {}, None, {"S2.CONTINUE"}, "Slot milega"),
    # ---- S2t
    ("s2t_time", OPEN + ["Haan ho jayega", "Shaam 5 baje"], {}, None, {"S2t.GIVES_TIME"}, "kitna lagega"),
    ("s2t_free", OPEN + ["Haan ho jayega", "Haan 5 baje free hai"], {}, None, {"S2t.SLOT_FREE"}, "kitna lagega"),
    ("s2t_offers", OPEN + ["Haan ho jayega", "5 baje ya 7 baje"], {}, None, {"S2t.OFFERS_SLOTS"}, "kitna lagega"),
    ("s2t_busy", OPEN + ["Haan ho jayega", "Nahi sab full hai"], {}, None, {"S2t.SLOT_BUSY"}, "Kaun sa samay free"),
    ("s2t_no", OPEN + ["Haan ho jayega", "Nahi"], {}, None, {"S2t.NO"}, "Kaun sa samay free"),
    # ---- S2b
    ("s2b_offers", OPEN + ["Full hai", "5 baje ya 7 baje ho jayega"], {}, None, {"S2b.OFFERS_SLOTS"}, "kitna lagega"),
    ("s2b_free", OPEN + ["Full hai", "Haan 5 baje free hai"], {}, None, {"S2b.SLOT_FREE"}, "kitna lagega"),
    ("s2b_time", OPEN + ["Full hai", "Shaam 7 baje"], {}, None, {"S2b.GIVES_TIME"}, "kitna lagega"),
    ("s2b_busy", OPEN + ["Full hai", "Koi slot nahi"], {}, "NO_SLOT", {"S2b.SLOT_BUSY"}, "bata dungi"),
    ("s2b_no", OPEN + ["Full hai", "Nahi"], {}, "NO_SLOT", {"S2b.NO"}, "bata dungi"),
    # ---- S3
    ("s3_price", OPEN + FREE + PRICE, {}, None, {"S3.GIVES_PRICE"}, "Matlab 400 rupaye, lagbhag 30 minute"),
    ("s3_range", OPEN + FREE + ["400 se 500 rupaye tak"], {}, None, {"S3.PRICE_RANGE"}, "500 rupaye tak"),
    ("s3_depends", OPEN + FREE + ["Stylist par depend karta hai"], {}, None, {"S3.PRICE_DEPENDS"}, "advance"),
    ("s3_refuses", OPEN + FREE + ["Phone par price nahi bata sakte, aake poochh lo"], {}, None, {"S3.REFUSES_PRICE"}, "advance"),
    ("s3_continue", OPEN + FREE + ["Haan boliye"], {}, None, {"S3.CONTINUE"}, "kitna lagega"),
    # ---- S3r
    ("s3r_yes", OPEN + FREE + PRICE + ["Haan"], {}, None, {"S3r.YES"}, "advance"),
    ("s3r_continue", OPEN + FREE + PRICE + ["Haan boliye"], {}, None, {"S3r.CONTINUE"}, "advance"),
    ("s3r_ack", OPEN + FREE + PRICE + ["Thanks"], {}, None, {"S3r.ACK"}, "advance"),
    ("s3r_no", OPEN + FREE + PRICE + ["Nahi"], {}, None, {"S3r.NO"}, "kitna lagega"),
    ("s3r_correct", OPEN + FREE + PRICE + ["Nahi 450 rupaye"], {}, None, {"S3r.GIVES_PRICE"}, "450 rupaye"),
    ("s3r_range", OPEN + FREE + PRICE + ["400 se 500 rupaye"], {}, None, {"S3r.PRICE_RANGE"}, "500 rupaye tak"),
    # ---- S3b (over budget, user allowed asking once)
    ("s3b_new_price", OPEN + FREE + ["900 rupaye, 45 minute"] + SAHI + ["700 rupaye kar denge"], {"negotiation": True}, None, {"S3b.GIVES_PRICE"}, "advance"),
    ("s3b_range", OPEN + FREE + ["900 rupaye, 45 minute"] + SAHI + ["700 se 800 rupaye"], {"negotiation": True}, None, {"S3b.PRICE_RANGE"}, "advance"),
    ("s3b_yes", OPEN + FREE + ["900 rupaye, 45 minute"] + SAHI + ["Haan"], {"negotiation": True}, None, {"S3b.YES"}, "advance"),
    ("s3b_no", OPEN + FREE + ["900 rupaye, 45 minute"] + SAHI + ["Nahi"], {"negotiation": True}, None, {"S3b.NO"}, "advance"),
    ("s3b_any", OPEN + FREE + ["900 rupaye, 45 minute"] + SAHI + ["Aap aa jao dekhte hain"], {"negotiation": True}, None, {"S3b.ANY"}, "advance"),
    # ---- S4 (the user named a stylist)
    ("s4_stylist", OPEN + FREE + PRICE + SAHI + ["Amit hai, woh kar denge"], {"inputs": {"stylist_pref": "Amit"}}, None, {"S4.GIVES_STYLIST"}, "advance"),
    ("s4_yes", OPEN + FREE + PRICE + SAHI + ["Haan"], {"inputs": {"stylist_pref": "Amit"}}, None, {"S4.YES"}, "advance"),
    ("s4_no", OPEN + FREE + PRICE + SAHI + ["Nahi"], {"inputs": {"stylist_pref": "Amit"}}, None, {"S4.NO"}, "advance"),
    ("s4_continue", OPEN + FREE + PRICE + SAHI + ["Haan boliye"], {"inputs": {"stylist_pref": "Amit"}}, None, {"S4.CONTINUE"}, "advance"),
    ("s4_any", OPEN + FREE + PRICE + SAHI + ["Kal shaam 6 baje free hai"], {"inputs": {"stylist_pref": "Amit"}}, None, {"S4.ANY"}, "advance"),
    # ---- S5
    ("s5_needs", OPEN + FREE + PRICE + SAHI + ["200 rupaye advance dena padega"], {}, None, {"S5.NEEDS_ADVANCE"}, "Advance main abhi nahi de sakti"),
    ("s5_no_adv", OPEN + FREE + PRICE + SAHI + NOADV, {}, None, {"S5.NO_ADVANCE"}, "isi number par call back"),
    ("s5_no", OPEN + FREE + PRICE + SAHI + ["Nahi"], {}, None, {"S5.NO"}, "isi number par call back"),
    ("s5_any", OPEN + FREE + PRICE + SAHI + ["Haan policy hai, aake dekh lo"], {}, None, {"S5.ANY"}, "isi number par call back"),
    ("s5_busy", OPEN + FREE + PRICE + SAHI + ["Abhi busy hoon, baad mein"], {}, "SLOT_OFFERED", {"S5.BUSY_LATER"}, "approval ke baad call karti hoon"),
    # ---- S6 / S7
    ("s6_phone", OPEN + FREE + PRICE + SAHI + NOADV + ["Customer ka number kya hai?"], {}, "SLOT_OFFERED", {"S6.ASKS_CUSTOMER_PHONE"}, "number main share nahi kar sakti"),
    ("s6_any", OPEN + FREE + PRICE + SAHI + NOADV + OK, {}, "SLOT_OFFERED", {"S6.ANY", "S7.ANY"}, "Abhi kuch confirm nahi kiya"),
    ("s6_busy", OPEN + FREE + PRICE + SAHI + NOADV + ["Abhi busy hoon, baad mein"], {}, "SLOT_OFFERED", {"S6.BUSY_LATER"}, "approval ke baad"),
    # ---- defaults in the middle of the call
    ("d_robot", OPEN + ["Aap robot ho?"] + FREE, {}, None, {"defaults.ARE_YOU_BOT"}, "main AI hoon, insaan nahi"),
    ("d_who", OPEN + ["Kaun bol raha hai?"] + FREE, {}, None, {"defaults.WHO_IS_THIS"}, "Main Friday hoon"),
    ("d_repeat", OPEN + ["Kya? Dobara bolo"] + FREE, {}, None, {"defaults.ASKS_REPEAT"}, "Slot milega"),
    ("d_offtopic", OPEN + ["Parking hai kya aapke paas?"] + FREE, {}, None, {"defaults.ASKS_OFFTOPIC"}, "poochh kar bataungi"),
    ("d_secret", OPEN + ["Pehle OTP bata do"] + FREE, {}, None, {"defaults.ASKS_SECRET"}, "share nahi kar sakti"),
    ("d_phone", OPEN + ["Customer ka number kya hai"] + FREE, {}, None, {"defaults.ASKS_CUSTOMER_PHONE"}, "number main share nahi"),
    ("d_hold", OPEN + ["Ek minute hold kijiye", "Haan boliye"] + FREE, {}, None, {"defaults.HOLD_ON"}, "Slot milega"),
    ("d_busy_mid", OPEN + FREE + ["Abhi busy hoon, thodi der baad call karo"], {}, "CALL_BACK_LATER", {"defaults.BUSY_LATER"}, "baad mein call"),
    ("d_dnc_mid", OPEN + FREE + PRICE + ["Dobara call mat karna"], {}, "REFUSED", {"defaults.STOP_CALLING"}, "dobara call nahi"),
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
    """Each alternative of a conditional branch (SLOT_FREE with/without a time, price known or
    not, the four read-back variants, ...) is taken by some scripted conversation."""
    seen: set[str] = set()
    for sid, replies, kw, *_ in SCENARIOS:
        run = await drive(replies, brief=make_brief(**kw), ident=not sid.startswith("s0_"))
        seen |= {t for t in run.said}
    joined = " | ".join(seen)
    for needle in (
        "Kitne baje ka?",  # SLOT_FREE without a time
        "Matlab 400 rupaye, lagbhag 30 minute. Sahi?",
        "tak, lagbhag",  # range with duration
        "Rahul ji ka budget 600 rupaye hai",  # S3b
        "Agar Amit available hon",  # S4
    ):
        assert needle in joined, needle


async def test_read_back_variants():
    price_only = await drive(OPEN + FREE + ["Haircut 400 rupaye"], brief=make_brief())
    assert "Matlab 400 rupaye. Sahi?" in price_only.said[-1]
    range_price_only = await drive(OPEN + FREE + ["400 se 500 rupaye"], brief=make_brief())
    assert "Matlab 500 rupaye tak. Sahi?" in range_price_only.said[-1]
    range_dur = await drive(OPEN + FREE + ["400 se 500 rupaye, 30 minute"], brief=make_brief())
    assert "Matlab 500 rupaye tak, lagbhag 30 minute. Sahi?" in range_dur.said[-1]


async def test_s3b_only_once_and_only_when_allowed():
    over = OPEN + FREE + ["900 rupaye"] + SAHI
    # user did not allow negotiating: no budget ask, straight to the next question
    no_neg = await drive(over, brief=make_brief(negotiation=False))
    assert "S3b" not in no_neg.path and "Koi advance" in no_neg.said[-1]
    # allowed: exactly one budget ask, even if she corrects the price afterwards
    neg = await drive(over + ["700 rupaye"] + ["Nahi, 700 hi hai", "Haan"],
                      brief=make_brief(negotiation=True))
    assert neg.path.count("S3b") == 1
    asks = [s for s in neg.said if "budget" in s]
    assert len(asks) == 1


async def test_stylist_step_skipped_without_preference():
    run = await drive(OPEN + FREE + ["Stylist par depend karta hai"], brief=make_brief())
    assert "S4" not in run.path and "Koi advance" in run.said[-1]


async def test_price_unknown_continues_to_the_close():
    run = await drive(
        OPEN + FREE + ["Phone par price nahi bata sakte"] + NOADV + OK, brief=make_brief()
    )
    assert run.outcome == "SLOT_OFFERED" and run.final.quote.amount_inr is None
    assert "rupaye" not in run.final.text and "approval ke baad" in run.final.text


async def test_outcome_mapping_to_call_outcomes():
    cases = {
        ("Nahi abhi nahi",): CallOutcome.CALLBACK_LATER,
        ("Yeh salon nahi hai",): CallOutcome.DECLINED,
        ("Dobara call mat karna",): CallOutcome.DECLINED,
        tuple(OPEN + FREE + PRICE + SAHI + NOADV + OK): CallOutcome.PENDING_APPROVAL,
        tuple(OPEN + ["Kal full hai", "Koi slot nahi"]): CallOutcome.DECLINED,
    }
    for replies, expected in cases.items():
        run = await drive(list(replies), brief=make_brief())
        assert run.final.type == CallActionType.HANGUP and run.final.outcome == expected, replies


async def test_dnc_sets_the_pool_wide_flag():
    run = await drive(["Dobara call mat karna"], brief=make_brief())
    assert run.final.collected["do_not_call"] == "yes"


async def test_slots_and_facts_are_collected():
    run = await drive(OPEN + FREE + PRICE + SAHI + ["200 advance dena padega"] + OK,
                      brief=make_brief())
    c = run.final.collected
    assert c["price_inr"] == "400" and c["duration_min"] == "30"
    assert c["advance_needed"] == "yes" and "6 baje" in c["slot"] and c["outcome"] == "SLOT_OFFERED"
    q = run.final.quote
    assert q.amount_inr == 400 and q.available_slots == ["6 PM"] and q.within_budget is True


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
    run = await drive(OPEN + ["bas shaam chhe"], brief=make_brief(), policy=policy)
    assert "S2.GIVES_TIME" in run.keys and "kitna lagega" in run.said[-1]


def test_any_is_the_wildcard_key():
    assert ANY == "ANY"
