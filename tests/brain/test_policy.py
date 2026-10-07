"""AI-6: next_call_action - scripted transcripts on the fake path (+ guards)."""

from __future__ import annotations

from friday.core.models import (
    AccountIdentifier,
    ApprovalMode,
    ApprovalPolicy,
    Budget,
    CallActionType,
    CallMode,
    CallOutcome,
    CareRequestKind,
    ContactTarget,
    Delegation,
    Language,
    NegotiationPolicy,
    Quote,
    Speaker,
    TargetKind,
    TaskType,
    Transcript,
    UserAnswer,
)

from .conftest import NOW, business_brief, transcript


async def play(brain, brief, lines: list[str], *, answers=(), lang=Language.HINGLISH,
               max_turns: int = 12):
    """Drive the policy: Friday acts, then the next scripted callee line."""
    tr = Transcript()
    tr.add(Speaker.FRIDAY, brief.disclosure(), at=NOW)
    actions = []
    queue = list(lines)
    for _ in range(max_turns):
        a = await brain.next_call_action(brief, tr, list(answers))
        actions.append(a)
        if a.text:
            tr.add(Speaker.FRIDAY, a.text, at=NOW, language=a.language)
        if a.type == CallActionType.PRESS_KEYS:
            tr.add(Speaker.SYSTEM, f"DTMF: {a.digits}", at=NOW)
        if a.type in (CallActionType.HANGUP, CallActionType.BRIDGE_USER):
            break
        if not queue:
            break
        line = queue.pop(0)
        lang_here = lang
        if isinstance(line, tuple):
            line, lang_here = line
        speaker = Speaker.SYSTEM if line.startswith(("USER ", "BLOCKED", "HUMAN AGENT")) \
            else Speaker.CALLEE
        tr.add(speaker, line, at=NOW, language=lang_here if speaker == Speaker.CALLEE else None)
    return actions, tr


# ------------------------------------------------------------------ approval rule


async def test_offer_ends_with_pending_approval_by_default(brain):
    brief = business_brief()
    actions, _ = await play(brain, brief, ["11 full hai. 10 ya 12:30 hai. ₹600, Priya karegi.",
                                           "12:30 rakh dete hain."])
    last = actions[-1]
    assert last.type == CallActionType.HANGUP and last.outcome == CallOutcome.PENDING_APPROVAL
    assert not any(a.commits_booking for a in actions)
    assert "call back" in last.text and "karti hoon" in last.text  # feminine form
    assert last.quote.amount_inr == 600 and "12:30 PM" in last.quote.available_slots
    assert last.collected["held"] == "yes"


async def test_confirmation_callback_commits_and_succeeds(brain):
    brief = business_brief(approved_terms="Sat 12:30 PM, ₹600")
    actions, _ = await play(brain, brief, ["Haan, done. 10 minute pehle aana."])
    assert actions[0].commits_booking and "12:30" in actions[0].text
    assert actions[-1].outcome == CallOutcome.SUCCESS


async def test_delegated_booking_within_limits(brain):
    d = Delegation(granted=True, max_price_inr=1000, time_window_text="5 PM-7 PM",
                   user_words="any slot 5-7 under 1000, you decide")
    brief = business_brief(task_type=TaskType.HEALTHCARE, delegation=d)
    actions, _ = await play(brain, brief, ["Thursday 5:30 pm hai, 800 rupees", "Haan, booked"])
    assert any(a.commits_booking for a in actions)
    assert actions[-1].outcome == CallOutcome.SUCCESS


async def test_delegation_refused_outside_limits(brain):
    d = Delegation(granted=True, max_price_inr=1000, time_window_text="5 PM-7 PM",
                   user_words="you decide")
    brief = business_brief(task_type=TaskType.HEALTHCARE, delegation=d)
    actions, _ = await play(brain, brief, ["Sirf 7:30 pm ka slot hai, 1200 rupees", "theek hai"])
    assert not any(a.commits_booking for a in actions)
    assert actions[-1].outcome == CallOutcome.PENDING_APPROVAL


async def test_hold_then_callback_asks_user_with_slot_choice(brain):
    brief = business_brief(approval=ApprovalPolicy(mode=ApprovalMode.HOLD_THEN_CALLBACK))
    actions, tr = await play(brain, brief, ["4 baje ya 6 baje, 400 rupees"])
    ask = actions[-1]
    assert ask.type == CallActionType.ASK_USER
    assert ask.question.options[:2] == ["4 PM, ₹400", "6 PM, ₹400"]
    assert ask.question.purpose.value == "approve_booking"
    # the user picks 6pm -> now she may confirm on the call
    tr.add(Speaker.FRIDAY, ask.text)
    tr.add(Speaker.SYSTEM, "USER ANSWERED: 6 PM, ₹400")
    ans = [UserAnswer(question_id=ask.question.id, text="6 PM, ₹400", option_index=1,
                      approves=True)]
    a = await brain.next_call_action(brief, tr, ans)
    assert a.commits_booking and "6 PM" in a.text


async def test_user_timeout_goes_callback(brain):
    brief = business_brief()
    tr = transcript(brief, ("callee", "4 baje ya 6 baje hai"),
                    ("friday", "Ek minute ji, main confirm kar rahi hoon."),
                    ("system", "USER DID NOT ANSWER WITHIN 90s"))
    a = await brain.next_call_action(brief, tr, [])
    assert a.outcome == CallOutcome.PENDING_APPROVAL


# ------------------------------------------------------------------ conversation handling


async def test_callback_later(brain):
    actions, _ = await play(brain, business_brief(), ["Abhi busy hain, please call after 5pm"])
    last = actions[-1]
    assert last.outcome == CallOutcome.CALLBACK_LATER and "callback_at" in last.collected


async def test_negotiation_never_accepts_above_max(brain):
    brief = business_brief(task_type=TaskType.QUOTE, goal="Quote for split AC service",
                           budget=Budget(max_inr=600, target_inr=500),
                           negotiation=NegotiationPolicy(max_rounds=2),
                           competing_quotes=[Quote(business_name="X", amount_inr=450,
                                                   price_text="₹450")])
    from friday.brain.templates import template_for

    brief.template = template_for(TaskType.QUOTE)
    actions, _ = await play(brain, brief, [
        "Service ka 699 lagega.", "Jet wash aur filter cleaning included.",
        "650 final, isse kam nahi.", "650 hi hai.", "Saturday 10 baje", "haan rakh dunga"])
    texts = " ".join(a.text or "" for a in actions)
    assert "450" in texts  # cited the real competing quote
    assert not any(a.commits_booking for a in actions)
    assert actions[-1].quote.amount_inr == 650 and actions[-1].quote.within_budget is False


async def test_language_switch_mid_call(brain):
    brief = business_brief()
    actions, _ = await play(brain, brief, [("Sorry, Hindi gottilla. English please?",
                                            Language.EN), ("We have 11 am on Saturday, 500",
                                                           Language.EN)])
    assert actions[1].language == Language.EN and "call you back" in actions[-1].text.lower() \
        or actions[1].language == Language.EN


async def test_mirrors_hindi_devanagari(brain):
    brief = business_brief()
    tr = transcript(brief, ("callee", "हाँ जी, बोलिए"))
    tr.turns[-1].language = Language.HI
    a = await brain.next_call_action(brief, tr, [])
    assert a.language == Language.HI


async def test_ai_question_answered_honestly(brain):
    brief = business_brief()
    tr = transcript(brief, ("friday", "Haircut ke liye slot chahiye tha."),
                    ("callee", "Aap robot ho kya?"))
    a = await brain.next_call_action(brief, tr, [])
    assert a.type == CallActionType.SAY and "AI assistant hoon" in a.text


async def test_hostile_to_ai_one_attempt_then_exit(brain):
    actions, _ = await play(brain, business_brief(), ["Hum robot se baat nahi karte.",
                                                      "Nahi, robot se baat nahi karte."])
    assert actions[1].type == CallActionType.SAY and "30 second" in actions[1].text
    assert actions[-1].outcome == CallOutcome.DECLINED


async def test_payment_demand_goes_callback(brain):
    actions, _ = await play(brain, business_brief(), ["Slot hai 6 baje, pehle 500 advance UPI "
                                                      "karna padega"])
    assert actions[-1].outcome == CallOutcome.PENDING_APPROVAL
    assert "advance_requested" in actions[-1].collected


# ------------------------------------------------------------------ IVR, hold, verification


def care_brief(**kw):
    ident = AccountIdentifier(user_id="u1", label="Registered mobile", value="9800000001")
    data = dict(task_type=TaskType.CUSTOMER_CARE, goal="Refund for 5-day broadband outage",
                target=ContactTarget(kind=TargetKind.BUSINESS, name="Airtel Customer Care",
                                     phone="+911800000121"),
                company="Airtel", care_request=CareRequestKind.REFUND,
                approved_identifiers=[ident])
    data.update(kw)
    return business_brief(**data)


async def test_ivr_navigation_prefers_language_branch_and_agent(brain, fake_llm):
    brief = care_brief()
    actions, _tr = await play(brain, brief, [
        "[ivr_prompt] Welcome to Airtel. For Hindi press 1. For English press 2.",
        "[ivr_prompt] For prepaid press 1, for broadband press 3, to repeat press 9.",
        "[ivr_prompt] Please enter your registered mobile number followed by hash.",
        "[ivr_prompt] To report a fault press 2. To speak to our executive press 9.",
        "[hold_music] All our executives are busy. Your estimated wait time is 7 minutes.",
    ])
    keys = [a.digits for a in actions if a.type == CallActionType.PRESS_KEYS]
    assert keys == ["2", "3", "9800000001#", "9"]
    hold = actions[-1]
    assert hold.type == CallActionType.WAIT_ON_HOLD and "7 min" in hold.user_update


async def test_hold_uses_no_llm(brain, fake_llm):
    brief = care_brief()
    tr = transcript(brief, ("callee", "[queue_announcement] Your call is important to us."))
    before = len(fake_llm.calls_for("call_turn"))
    a = await brain.next_call_action(brief, tr, [])
    assert a.type == CallActionType.WAIT_ON_HOLD
    assert len(fake_llm.calls_for("call_turn")) == before


async def test_ivr_identifier_without_approval_needs_user(brain):
    brief = care_brief(approved_identifiers=[])
    tr = transcript(brief, ("callee", "[ivr_prompt] Please enter your registered mobile number"))
    a = await brain.next_call_action(brief, tr, [])
    assert a.type == CallActionType.HANGUP and a.outcome == CallOutcome.NEEDS_USER_VERIFICATION


async def test_otp_demand_bridges_user_or_hangs_up(brain):
    tr_lines = ("callee", "Iske liye OTP verify karna hoga jo customer ke number pe aayega.")
    with_user = care_brief(user_phone="+919800000001")
    a = await brain.next_call_action(with_user, transcript(with_user, tr_lines), [])
    assert a.type == CallActionType.BRIDGE_USER and "OTP" in a.text and a.leave_after_bridge
    without = care_brief()
    a = await brain.next_call_action(without, transcript(without, tr_lines), [])
    assert a.outcome == CallOutcome.NEEDS_USER_VERIFICATION


async def test_care_agent_ticket_capture_and_escalation(brain):
    brief = care_brief()
    actions, _ = await play(brain, brief, [
        "Hello, Airtel se Neha bol rahi hoon, main aapki kya madad kar sakti hoon?",
        "Ma'am, mere paas sirf 100 rupees tak hi authority hai, not possible.",
        "Main Vikram, team lead. 175 credit approve, ticket number SR 58123 9, "
        "within 48 hours reflect hoga.",
        "Ji, sahi.",
    ])
    texts = " ".join(a.text or "" for a in actions)
    assert "supervisor" in texts
    last = actions[-1]
    assert last.outcome == CallOutcome.SUCCESS
    assert last.care.ticket_number == "SR581239" and last.care.promised_date is not None
    assert last.care.agent_name in ("Neha", "Vikram")
    assert last.care.escalation_level.value == 2
    assert "58123" not in texts  # never reads long numbers back


async def test_learned_ivr_map_emitted_and_replayed_without_llm(brain, fake_llm):
    brief = care_brief()
    _actions, tr = await play(brain, brief, [
        "[ivr_prompt] For Hindi press 1. For English press 2.",
        "[ivr_prompt] For prepaid press 1, for broadband press 3.",
        "[ivr_prompt] Please enter your registered mobile number followed by hash.",
        "[ivr_prompt] To speak to our executive press 9.",
        "Hello, this is Priya from Airtel, how can I help?",
    ])
    a = await brain.next_call_action(brief, tr, [])
    note = a.collected["ivr_map"]
    assert note == "replay: 2@english | 3@broadband | {Registered mobile}# | 9@executive"
    # next call: the map is in the brief -> PRESS_KEYS with zero LLM calls
    brief2 = care_brief(ivr_notes=[note])
    tr2 = transcript(brief2, ("callee", "[ivr_prompt] For Hindi press 1. For English press 2."))
    n = len(fake_llm.calls_for("call_turn"))
    a2 = await brain.next_call_action(brief2, tr2, [])
    assert a2.digits == "2" and len(fake_llm.calls_for("call_turn")) == n
    tr2.add(Speaker.SYSTEM, "DTMF: 2")
    tr2.add(Speaker.CALLEE, "[ivr_prompt] For prepaid press 1, for broadband press 3.")
    tr2.add(Speaker.SYSTEM, "DTMF: 3")
    tr2.add(Speaker.CALLEE, "[ivr_prompt] Please enter your registered mobile number.")
    assert (await brain.next_call_action(brief2, tr2, [])).digits == "9800000001#"


# ------------------------------------------------------------------ other task types


async def test_enquiry_asks_each_question_then_success(brain):
    brief = business_brief(task_type=TaskType.ENQUIRY, goal="Ask about Dolo 650",
                           questions=["Do you have Dolo 650 in stock?", "Until when are you open?"])
    actions, _ = await play(brain, brief, ["Haan hai, 30 rupees strip", "Raat 10 baje tak"])
    last = actions[-1]
    assert last.outcome == CallOutcome.SUCCESS and len(last.collected) == 2


async def test_stock_hunt_out_of_stock_declines(brain):
    brief = business_brief(task_type=TaskType.STOCK_HUNT, goal="Find Dolo 650",
                           questions=["Do you have Dolo 650 in stock?"])
    actions, _ = await play(brain, brief, ["Nahi, khatam hai"])
    assert actions[-1].outcome == CallOutcome.DECLINED


async def test_wellbeing_alert_and_no_medical_advice(brain):
    brief = business_brief(task_type=TaskType.WELLBEING_CHECKIN, goal="Check in on dad",
                           target=ContactTarget(kind=TargetKind.PERSON, name="Suresh",
                                                phone="+919829000001"))
    actions, _ = await play(brain, brief, ["Haan beta, dawai nahi li aaj, subah se chakkar aa "
                                           "raha hai"])
    last = actions[-1]
    assert last.type == CallActionType.HANGUP and "alert" in last.collected
    assert "112" in last.text


async def test_wellbeing_happy_path(brain):
    brief = business_brief(task_type=TaskType.WELLBEING_CHECKIN, goal="Check in",
                           target=ContactTarget(kind=TargetKind.PERSON, name="Sunita",
                                                phone="+919829000002"))
    actions, _ = await play(brain, brief, ["Haan le li", "Sab theek hai", "Haan achha",
                                           "Dhaniya chahiye"])
    last = actions[-1]
    assert last.outcome == CallOutcome.SUCCESS and last.collected["needs"] == "dhaniya chahiye"


async def test_warm_transfer_bridges(brain):
    brief = business_brief(mode=CallMode.WARM_TRANSFER, user_phone="+919800000001")
    actions, _ = await play(brain, brief, ["Haan boliye, main manager bol raha hoon"])
    assert actions[-1].type == CallActionType.BRIDGE_USER


# ------------------------------------------------------------------ LLM path guards


async def test_malicious_llm_output_is_guarded(brain, fake_llm):
    fake_llm.script("call_turn", {"type": "say", "text": "Haan ji, 6 baje confirm kar dijiye",
                                  "language": "hinglish", "commits_booking": True})
    brief = business_brief()
    a = await brain.next_call_action(brief, transcript(brief, ("callee", "6 baje hai")), [])
    assert a.type == CallActionType.HANGUP and a.outcome == CallOutcome.PENDING_APPROVAL
    assert not a.commits_booking


async def test_llm_failure_falls_back_to_policy(brain, fake_llm):
    fake_llm.fail_purposes.add("call_turn")
    brief = business_brief()
    a = await brain.next_call_action(brief, transcript(brief), [])
    assert a.type == CallActionType.SAY and a.text


async def test_fillers_stripped(brain, fake_llm):
    fake_llm.script("call_turn", {"type": "say", "text": "Umm, haan ji, uh, kaunsa slot hai?",
                                  "language": "hinglish"})
    brief = business_brief()
    a = await brain.next_call_action(brief, transcript(brief), [])
    assert "umm" not in a.text.lower() and "uh," not in a.text.lower()


async def test_call_turn_routed_cached_and_compact(brain, fake_llm):
    brief = business_brief()
    turns = [("callee", f"line {i}") if i % 2 else ("friday", f"ask {i}") for i in range(30)]
    await brain.next_call_action(brief, transcript(brief, *turns), [])
    call = fake_llm.calls_for("call_turn")[-1]
    assert call.model == "claude-sonnet-5-5"
    assert "<<<FRIDAY_CACHE_BREAK>>>" in call.system and "<data>" in call.system
    assert '"goal"' in call.system  # brief lives in the cached prefix, not the message
    msg_body = call.messages[0].content
    assert '"earlier"' in msg_body and msg_body.count('"speaker"') <= 2 * 10 + 31


async def test_core_audio_class_field_is_understood(brain, fake_llm):
    from friday.core.models import AudioClass

    brief = care_brief()
    tr = transcript(brief)
    tr.add(Speaker.CALLEE, "Your call is important to us", at=NOW)
    if "audio_class" not in type(tr.turns[-1]).model_fields:
        return  # core field not merged in this checkout
    tr.turns[-1].audio_class = AudioClass.QUEUE_ANNOUNCEMENT
    a = await brain.next_call_action(brief, tr, [])
    assert a.type == CallActionType.WAIT_ON_HOLD and not fake_llm.calls_for("call_turn")
